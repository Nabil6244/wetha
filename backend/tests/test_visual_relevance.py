"""Visual relevance vs provenance: labelled beats, false positives, provenance labelling, preview screening."""
import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image, ImageDraw
from app.footage_review import assess
from app import visual_concepts as vc

DATA = json.loads((Path(__file__).parent / 'fixtures/footage-relevance.json').read_text())
ADVISORY = SimpleNamespace(title='Hurricane Isaias Advisory 7A')


def clip(title):
    return {'id': title, 'title': title, 'tags': [], 'provider': 'pexels', 'height': 1080, 'seconds': 20, 'reuse_basis': 'stock_license', 'license': 'Pexels License'}


def evaluate():
    rows = []
    for beat in DATA['beats']:
        assert vc.beat_need(beat['narration']) == beat['concept'], beat['narration']
        for title, label in beat['candidates']:
            result = assess(clip(title), {'script_segment': beat['narration']}, ADVISORY)
            rows.append((beat['concept'], title, label, result['tier'] in ('auto', 'recommended'), result['visual']['score']))
    return rows


def test_labelled_beats_have_high_precision_and_no_never_items():
    rows = evaluate()
    chosen = [r for r in rows if r[3]];relevant = [r for r in rows if r[2]]
    precision = sum(r[2] for r in chosen) / len(chosen)
    recall = sum(r[3] for r in relevant) / len(relevant)
    false_positives = [r[1] for r in chosen if not r[2]]
    assert precision >= .9, false_positives
    assert recall >= .75, [r[1] for r in relevant if not r[3]]
    assert not any(('cartoon' in t.lower() or 'music video' in t.lower() or 'animat' in t.lower()) for t in [r[1] for r in chosen])


def test_generic_weather_words_never_make_a_clip_relevant():
    for title in ('Dramatic storm clouds', 'Storm clouds', 'Beautiful cinematic weather 4k', 'Cloudy sky footage'):
        result = assess(clip(title), {'script_segment': 'Storm surge pushed the Gulf over seawalls.'}, ADVISORY)
        assert result['tier'] == 'weak' and result['visual']['score'] <= 15, title


def test_provenance_is_separate_and_never_upgraded():
    claimed = assess(clip('Drone footage of Hurricane Isaias storm damage'), {'script_segment': 'Damage and debris covered the coast.'}, ADVISORY)
    assert claimed['provenance'] == {**claimed['provenance'], 'status': 'claimed_event', 'claimed_event': 'Hurricane Isaias', 'verified': False, 'matches_story': True}
    assert claimed['tier'] in ('auto', 'recommended')  # usable as illustration without provenance verification
    plain = assess(clip('Palm trees bending in hurricane force winds'), {'script_segment': 'Hurricane winds bent palms.'}, ADVISORY)
    assert plain['provenance']['status'] == 'illustrative' and plain['location']['certainty'] == 'unknown'
    assert set(plain) == {'tier', 'visual', 'provenance', 'licensing', 'location'}


def test_unlicensed_or_short_footage_is_demoted_not_hidden():
    good = clip('Storm surge waves overtopping a seawall')
    scene = {'script_segment': 'Storm surge pushed water over seawalls.'}
    assert assess({**good, 'reuse_basis': None}, scene, ADVISORY)['tier'] == 'weak'
    assert assess({**good, 'seconds': 3}, scene, ADVISORY)['tier'] == 'weak'
    assert assess({**good, 'provider': 'archive', 'archive_verdict': 'review', 'reuse_basis': 'public_domain'}, scene, ADVISORY)['tier'] == 'weak'


def picture(sky, sea, texture):
    image = Image.new('RGB', (320, 180), sky);d = ImageDraw.Draw(image)
    d.rectangle((0, 90, 320, 180), fill=sea)
    for x in range(0, 320, 6 if texture else 320):
        d.line((x, 95, x + 3, 180), fill=(240, 240, 240), width=2)
    return image


def test_preview_screening_flags_obvious_mismatches_and_promotes_clean_matches():
    stormy = vc.measure(picture((90, 95, 100), (80, 90, 95), True))
    sunny = vc.measure(picture((40, 120, 235), (30, 110, 200), True))
    calm = vc.measure(picture((120, 125, 130), (90, 100, 110), False))
    assert vc.preview_flags(stormy, 'storm_surge') == []
    assert 'clear blue sky' in vc.preview_flags(sunny, 'storm_surge')
    assert 'calm, smooth water' in vc.preview_flags(calm, 'storm_surge')
    scene = {'script_segment': 'Storm surge pushed water over seawalls.'}
    title = clip('Storm surge waves overtopping a seawall')
    assert assess(title, scene, ADVISORY, stormy)['tier'] == 'auto'
    assert assess(title, scene, ADVISORY, sunny)['tier'] == 'weak'
    assert assess(title, scene, ADVISORY)['tier'] == 'recommended'  # no preview: never auto
    assert any('repeats a shot' in f for f in assess(title, scene, ADVISORY, stormy, [stormy])['visual']['preview_flags'])


# Failures demonstrated in the 5:19 impact-story review (real Pexels titles).
def test_contrast_clause_decides_the_beat():
    assert vc.beat_need('The wind forecast was relatively low, but the water threat told a very different story.') == 'storm_surge'


def test_pier_overtopping_is_a_strong_surge_match():
    scene = {'script_segment': 'Life-threatening storm surge was forecast along the coast.'}
    result = assess(clip('A pier with waves crashing over it and a building'), scene, ADVISORY)
    assert result['tier'] in ('auto', 'recommended') and result['visual']['score'] >= 45


def test_space_hardware_and_towers_are_not_weather_imagery():
    scene = {'script_segment': 'The National Weather Service in Tallahassee issued the listed storm surge warning.'}
    for title in ('Satellite orbiting the earth', 'Aerial view of mountain weather station tower', 'View from satellite on earth'):
        assert assess(clip(title), scene, ADVISORY)['tier'] == 'weak', title


def stormy_preview(**changes):
    return {'blue_sky': 0, 'saturation': 20, 'brightness': 120, 'lower_edges': 30, 'flat': .2, 'hash': 1, **changes}


def test_vague_beats_are_never_auto_even_with_a_clean_preview():
    for narration in ('Before we get into the details, please remember: this bulletin is marked expired.',
                      'The National Weather Service in Tallahassee issued the listed storm surge warning.'):
        result = assess(clip('Storm waves crashing over the sea wall'), {'script_segment': narration}, ADVISORY, stormy_preview())
        assert result['tier'] != 'auto', narration


def test_dark_previews_named_foreign_settings_and_sunlit_scenes_are_not_auto():
    flood = {'script_segment': 'Heavy rain raised flash-flood concerns across Alabama.'}
    good = clip('Cars passing through flood water on the side street')
    assert assess(good, flood, ADVISORY, stormy_preview())['tier'] == 'auto'
    assert assess(good, flood, ADVISORY, stormy_preview(brightness=20))['tier'] != 'auto'
    abroad = assess(clip('Urban flooding during rain in mexico city'), flood, ADVISORY, stormy_preview())
    # Story region unknown: a named foreign place still blocks auto and asks for review.
    assert abroad['tier'] == 'recommended' and 'Outside the story region' in abroad['location']['setting']
    wind = {'script_segment': 'Hurricane-force winds bent palms along the coast.'}
    palm = clip('Tall palm tree palmettos bend in the gusts of strong wind')
    # Bright with blue sky visible: sunlit, demoted. Bright without sky evidence: uncertain, kept for review.
    assert assess(palm, wind, ADVISORY, stormy_preview(brightness=175, blue_sky=.5))['tier'] == 'weak'
    assert assess(palm, wind, ADVISORY, stormy_preview(brightness=175))['tier'] == 'recommended'


def test_bright_white_town_in_a_storm_stays_a_review_candidate():
    # Regression: a good seawall-overtopping clip below white buildings under an overcast sky was demoted to weak.
    surge = {'script_segment': 'Life-threatening storm surge was forecast along the coast.'}
    seawall = clip('Waves crashing against the sea wall in a coastal town')
    result = assess(seawall, surge, ADVISORY, stormy_preview(brightness=180, blue_sky=0, saturation=31))
    assert result['tier'] == 'recommended' and not result['visual']['preview_flags']


US_STORY = SimpleNamespace(title='Flash Flood Warning', provider='NWS')


def test_us_story_geographic_gate():
    flood = {'script_segment': 'Across parts of Alabama, heavy rain raised flash-flood concerns.'}
    calm = stormy_preview()
    # Metadata places the clip abroad: auto blocked, routed to review with the conflict recorded.
    for title in ('Urban flooding during rain in mexico city', 'Urban flooded street with rickshaw and cars'):
        result = assess(clip(title), flood, US_STORY, calm)
        assert result['tier'] == 'recommended' and result['location']['geography']['compatibility'] == 'conflict', title
        assert any('outside the US' in r for r in result['visual']['reasons'])
    # Dense urban street scene, unknown location: review, not rejected.
    review = assess(clip('Urban street flooding after heavy rainfall'), flood, US_STORY, calm)
    assert review['tier'] == 'recommended' and review['location']['geography']['compatibility'] == 'possible_conflict'
    # Generic flooded road, unknown location: no conflict, and the gate never lowers its tier.
    road = clip('Street flooding')
    gated, before = assess(road, flood, US_STORY, calm), assess(road, flood, US_STORY, calm, geo_gate=False)
    assert gated['location']['geography']['compatibility'] == 'no_conflict_evident' and gated['tier'] == before['tier']
    # A named US place is compatible.
    us = assess(clip('Houston street flooding after heavy rain'), flood, US_STORY, calm)
    assert us['location']['geography']['compatibility'] == 'compatible' and us['tier'] == 'auto'
    # Nature scenes are never gated for an unknown location.
    surge = {'script_segment': 'Storm surge pushed water over seawalls.'}
    assert assess(clip('Storm surge waves overtopping a seawall'), surge, US_STORY, calm)['location']['geography']['compatibility'] == 'no_conflict_evident'
