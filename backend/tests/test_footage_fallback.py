"""Automatic fallback searches and conservative screening in footage review: bounded, de-duplicated, honest."""
import asyncio
import random
from types import SimpleNamespace
from PIL import Image
from app import footage_review as fr
from app import visual_concepts as vc
from app.geo_gate import placement

US = SimpleNamespace(provider='NWS', title='Flash Flood Warning', event_key='urn:x', issued_at=None, area='', forecast_excerpt='', text='')
FLOOD = 'Flash flooding covered roads across parts of Alabama overnight.'
FORECAST = 'The National Weather Service forecast keeps the warning in effect, and the advisory was issued this morning.'


def clip(identity, title):
    return {'id': identity, 'kind': 'video', 'title': title, 'description': title, 'tags': sorted(vc_topics(title)), 'provider': 'pexels',
            'license': 'Pexels License https://www.pexels.com/license/', 'attribution': 'A / Pexels', 'source': f'https://www.pexels.com/video/{identity}/',
            'height': 1080, 'width': 1920, 'seconds': 20, 'reuse_basis': 'stock_license', 'thumbnail_url': f'https://images.pexels.com/{identity}.jpg', 'context': 'illustrative'}


def vc_topics(title):
    from app.media_selection import topics
    return topics(title)


class Discovery:
    """Stands in for media discovery: records every provider search; answers from a fixed table."""

    def __init__(self, scenes, answers, warnings=None):
        self.calls, self.answers, self.warnings = [], answers, warnings or {}
        plan = {'id': 'p', 'advisory_id': 'a', 'scenes': [{'id': str(i), 'script_segment': t, 'parameters': {}} for i, t in enumerate(scenes)]}
        store = SimpleNamespace(visual_plan=lambda _: plan, advisory=lambda _: US)
        self.production = SimpleNamespace(store=store, validate_plan=lambda *a, **k: None)
        self.stock_cache, self.cache = {}, {}

    def stock_cached(self, key):
        return self.stock_cache.get(key)

    async def search(self, request):
        self.calls.append(request.query)
        self.stock_cache[('pexels', request.query.casefold())] = True
        return {'results': self.answers.get(request.query, []), 'warnings': self.warnings.get(request.query, [])}


def previews(monkeypatch):
    """Distinct grey storm-like frames per URL (no sky, no saturation): previews never decide these tests."""
    async def fake(client, url):
        rng = random.Random(url)
        return Image.frombytes('L', (96, 54), bytes(rng.randrange(60, 200) for _ in range(96 * 54))).convert('RGB')
    monkeypatch.setattr(fr, 'preview', fake)


def run(discovery, **options):
    return asyncio.run(fr.review(discovery, 'p', **options))


def first_queries(text, occurrence=0):
    return vc.search_variants(vc.beat_need(text), occurrence, 'Alabama')


def test_ambiguous_street_scene_triggers_a_distinct_search_that_finds_a_clean_clip(monkeypatch):
    previews(monkeypatch)
    initial = first_queries(FLOOD)
    answers = {initial[0]: [clip('street', 'Urban street flooding with people after heavy rain'), clip('dhaka', 'Flooded street in dhaka bangladesh')]}
    alternatives = vc.fallback_searches('flash_flood', initial, ambiguous_urban=True)
    assert alternatives and not any(q in initial for q in alternatives)
    assert 'street' not in alternatives[0]  # location-neutral searches first for an urban-ambiguity problem
    answers[alternatives[0]] = [clip('road', 'Swollen river flood water rushing')]
    discovery = Discovery([FLOOD], answers)
    rows, _, stats = run(discovery)
    beat = rows[0]
    assert beat['status'] == 'ready' and beat['fallback']['queries'] == [alternatives[0]]  # stopped once clean
    assert beat['candidates'][0]['candidate_id'] == 'road'
    assert stats['extra_searches'] == 1 and len(discovery.calls) == len(set(discovery.calls))
    # The known conflict is never automatic and stays behind the clean clip; the street scene waits for review.
    dhaka = next(c for c in beat['candidates'] if c['candidate_id'] == 'dhaka')
    assert dhaka['tier'] != 'auto' and dhaka['location']['geography']['compatibility'] == 'conflict'
    street = next(c for c in beat['candidates'] if c['candidate_id'] == 'street')
    assert street['tier'] != 'auto' and not fr.clean(street)


def test_without_fallback_nothing_extra_is_searched(monkeypatch):
    previews(monkeypatch)
    initial = first_queries(FLOOD)
    discovery = Discovery([FLOOD], {initial[0]: [clip('street', 'Urban street flooding with people after heavy rain')]})
    rows, _, stats = run(discovery, fallback=False)
    assert stats['extra_searches'] == 0 and set(discovery.calls) == set(initial) and rows[0]['fallback'] is None


def test_forecast_beats_use_data_graphics_and_never_search_stock(monkeypatch):
    previews(monkeypatch)
    discovery = Discovery([FORECAST], {})
    rows, _, stats = run(discovery)
    assert vc.beat_need(FORECAST) == 'forecast_warning'
    assert discovery.calls == [] and rows[0]['status'] == 'graphics' and rows[0]['candidates'] == []
    assert vc.fallback_searches('forecast_warning', []) == []


def test_unresolved_beats_are_capped_never_repeat_a_search_and_are_reported(monkeypatch):
    previews(monkeypatch)
    scenes = [FLOOD, 'Heavy rain fell for hours across Alabama.', 'Storm surge pushed water over seawalls along the Alabama coast.',
              'Hurricane-force winds bent palms along the Alabama coast.', FLOOD, 'Downed trees and damage across Alabama.']
    discovery = Discovery(scenes, {})  # providers return nothing at all
    rows, _, stats = run(discovery, extra_searches=3)
    assert stats['extra_searches'] == 3
    assert len(discovery.calls) == len(set(discovery.calls))  # no duplicate provider searches, ever
    assert all(r['status'] == 'needs_attention' and r['candidates'] == [] for r in rows)
    assert any('cap (3) reached' in ((r['fallback'] or {}).get('note') or '') for r in rows)
    assert all(len((r['fallback'] or {}).get('queries', [])) <= fr.FALLBACK_PER_BEAT for r in rows)


def test_provider_limit_stops_further_fallback_searches(monkeypatch):
    previews(monkeypatch)
    initial = first_queries(FLOOD)
    discovery = Discovery([FLOOD, 'Heavy rain fell for hours across Alabama.'], {}, {initial[0]: ['Pexels request limit reached; try again later.']})
    rows, warnings, stats = run(discovery)
    assert stats['provider_limited'] and stats['extra_searches'] == 0
    assert 'Provider limit reached' in rows[0]['fallback']['note'] and 'request limit' in warnings[0]


def test_cache_reuse_is_counted_and_a_second_review_repeats_nothing_uncached(monkeypatch):
    previews(monkeypatch)
    discovery = Discovery([FLOOD], {})
    _, _, first = run(discovery)
    _, _, second = run(discovery)
    assert first['cache_hits'] == 0 and second['cache_hits'] == second['searches']


class Screener:
    """Stands in for Apple Vision: rickshaw label and Thai text on every frame."""

    def __init__(self):
        self.frames = []

    def screen(self, frames):
        self.frames += frames
        return {str(f): {'labels': [['rickshaw', .4], ['water', .8]], 'text': [['วลูส้เดอ', .9]], 'text_regions': 1} for f in frames}


def test_vision_cues_are_weak_evidence_only(monkeypatch, tmp_path):
    previews(monkeypatch)
    initial = first_queries(FLOOD)
    road = clip('road', 'Swollen river flood water rushing')
    discovery = Discovery([FLOOD], {initial[0]: [road]})
    plain, _, _ = run(discovery, fallback=False)
    assert plain[0]['candidates'][0]['tier'] == 'auto'
    screener = Screener()
    rows, _, stats = run(Discovery([FLOOD], {initial[0]: [road]}), screener=screener, frames=tmp_path)
    held = rows[0]['candidates'][0]
    # Held back from automatic selection, still offered for review, never a geographic conflict, never a country.
    assert held['tier'] == 'recommended' and held['location']['visual_setting']['strength'] == 'weak'
    assert held['location']['geography']['compatibility'] != 'conflict'
    assert not any(country in str(held['location']).lower() for country in ('thailand', 'india', 'bangladesh'))
    # The evidence is tied to the exact frame and screener version; it triggers alternative searches first.
    assert held['screening']['frame_sha256'] and (tmp_path / f"{held['screening']['frame_sha256']}.jpg").exists()
    assert held['screening']['screeners'] == [fr.SCREENER, 'apple-vision-1']
    assert stats['extra_searches'] >= 1 and rows[0]['status'] == 'review'


def test_vision_never_demotes_or_excludes(monkeypatch):
    from app.footage_vision import weak_evidence
    cue = {'setting_cues': ['signage in a non-Latin script'], 'issues': ['sunlit blue sky'], 'version': 'apple-vision-1'}
    assert weak_evidence('auto', cue) == 'recommended'
    assert weak_evidence('recommended', cue) == 'recommended' and weak_evidence('weak', cue) == 'weak'
    assert weak_evidence('auto', {'setting_cues': [], 'issues': []}) == 'auto' and weak_evidence('auto', None) == 'auto'
    # Sky and night-sky labels alone never hold a clip back (they held back valid clips on the labelled frames).
    assert weak_evidence('auto', {'setting_cues': [], 'issues': ['space or night-sky imagery'], 'version': 'apple-vision-1'}) == 'auto'


def test_screening_and_import_never_count_as_clearance():
    street = {'id': 's', 'kind': 'video', 'name': 'pexels-5.mp4', 'source': 'https://www.pexels.com/video/urban-street-flooding-after-heavy-rainfall-5/',
              'catalog': {'tags': ['flood', 'rain']}}
    assert not placement(street, FLOOD, US)['allowed']
    # Whatever a review recorded (no cues, high relevance, auto tier), the gate still needs a reviewer.
    screened = {**street, 'catalog': {**street['catalog'], 'screening': {'vision': {'setting_cues': []}}, 'tier': 'auto', 'location_reviewed': True}}
    assert not placement(screened, FLOOD, US)['allowed']


def test_generic_weather_footage_stays_eligible_without_a_location(monkeypatch):
    previews(monkeypatch)
    text = 'Hurricane-force winds bent palms along the Alabama coast.'
    first = first_queries(text)
    discovery = Discovery([text], {first[0]: [clip('palms', 'Palm trees bending in hurricane wind')]})
    rows, _, stats = run(discovery)
    assert rows[0]['status'] == 'ready' and rows[0]['candidates'][0]['tier'] == 'auto' and stats['extra_searches'] == 0
    assert rows[0]['candidates'][0]['provenance']['verified'] is False  # illustrative, never verified event footage


def test_named_uk_and_other_foreign_places_are_conflicts_but_us_lookalikes_are_not():
    # Found in a live review: auto-rated although its own metadata names the UK.
    thames = clip('thames', 'Aerial view of river thames flooding in uk')
    assert fr.assess(thames, {'script_segment': FLOOD}, US)['location']['geography']['compatibility'] == 'conflict'
    asset = {'id': 't', 'kind': 'video', 'name': 'pexels-1.mp4', 'source': 'https://www.pexels.com/video/aerial-view-of-river-thames-flooding-in-uk-1/', 'catalog': {'tags': ['flood']}}
    assert not placement(asset, FLOOD, US)['allowed']
    for title in ("New England nor'easter coastal flooding", 'Waves in the gulf of mexico', 'New mexico flash flood', 'Whales breaching in a storm'):
        assert not vc.ABROAD.search(title), title
