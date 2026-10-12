"""Per-beat footage review before any import: search, rank, contact sheet. Nothing is downloaded but
small preview images; the editor chooses what to import.

Ranking per beat: topic match, the shot class the beat needs, resolution, duration, licence clarity and
provider priority. Internet Archive items keep their assessment verdict; only 'strong' Archive items and
licensed stock/Wikimedia/NASA items above the score threshold are marked recommended. Weak matches are shown
with their reasons but are never recommended.
"""
import io
import json
import re
from pathlib import Path
from uuid import uuid4
import httpx
from PIL import Image, ImageDraw
from . import media_selection
from .contracts import MediaDiscoveryRequest
from .footage_expansion import needs
from .visual_director import classify, story_text

PREVIEW_HOSTS = {'images.pexels.com', 'cdn.pixabay.com', 'i.vimeocdn.com', 'upload.wikimedia.org', 'archive.org', 'images-assets.nasa.gov'}
PRIORITY = {'pexels': 6, 'pixabay': 6, 'commons': 3, 'nasa': 2, 'stock': 2, 'archive': 0}
RECOMMEND = 24
TILE = (320, 180)


# What footage of each hazard shows, and settings that contradict it.
HAZARD_WORDS = {
    'tropical_cyclone': r'hurricane|tropical|typhoon|cyclone|storm surge|surge|palm|coast\w*|beach|ocean|sea|waves?|flood\w*',
    'flood': r'flood\w*|inundat\w*|submerged|high water|rain\w*',
    'tornado': r'tornado\w*|twister|funnel|supercell',
    'severe_storm': r'thunder\w*|lightning|hail|storm',
    'winter': r'snow\w*|blizzard|ice|icy|frozen|sleet',
    'heat': r'heat|hot|sun\w*|haze|drought',
}
WRONG_SETTING = {
    'tropical_cyclone': r'mountains?|alpine|snow\w*|desert|meadow|grass(?:land)?|field|prairie|farmland|forest|skyline|city lights|canyon',
    'flood': r'desert|snow\w*|mountains?|canyon',
}


ALLOWED_BASIS = {'stock_license', 'cc_by', 'public_domain'}
AUTO = 60
RECOMMEND = 45


def story_region(advisory):
    """US for NWS and NHC stories; otherwise unknown (no geographic gate)."""
    return 'US' if getattr(advisory, 'provider', None) in ('NWS', 'NHC') else None


def assess(candidate, scene, advisory, preview=None, earlier=(), geo_gate=True, vision=None):
    """Separate records for visual relevance, provenance, licensing and location, plus a tier.

    tier 'auto': high-confidence illustrative match with a clean preview, licensed, 720p+, 5 s+ (eligible for
    user-approved batch import); 'recommended': good match to check by eye; 'weak': demoted, still shown.
    `vision` (footage_vision findings) is weak evidence: it can only turn 'auto' into 'recommended'."""
    from . import visual_concepts as vc
    concept = vc.beat_need(scene['script_segment'])
    visual = vc.relevance(candidate, concept, preview, scene['script_segment'])
    if preview and any(vc.similar(preview, other) for other in earlier):
        visual['score'] = max(0, visual['score'] - 30);visual['preview_flags'].append('repeats a shot already offered');visual['reasons'].append('Near-identical to another candidate')
    origin = vc.provenance(candidate, getattr(advisory, 'title', ''))
    basis = candidate.get('reuse_basis')
    licensing = {'licence': candidate.get('license'), 'attribution': candidate.get('attribution'), 'reuse_basis': basis,
                 'verified': basis in ALLOWED_BASIS and bool(candidate.get('license')) and (candidate.get('provider') != 'archive' or candidate.get('archive_verdict') == 'strong')}
    place = re.search(r'\b(?:in|at|near|over)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b', candidate.get('title', ''))
    location = {'certainty': 'reviewed' if candidate.get('location_reviewed') else 'named_in_title' if place else 'unknown',
                'named_place': place.group(1) if place else None, 'note': 'Illustrative footage carries “location not verified” on screen.'}
    region = story_region(advisory)
    geo = vc.geography(candidate, region, concept) if geo_gate and region else None
    if geo:
        abroad = geo['compatibility'] == 'conflict'
        location['geography'] = geo
    else:
        # Previous behaviour, kept only for before/after evaluation: a named foreign place capped the tier.
        abroad = vc.ABROAD.search(candidate.get('title', '') + ' ' + candidate.get('description', '')[:400])
    if abroad:
        location['setting'] = f'Outside the story region ({(geo or {}).get("evidence", [""])[0] if geo else abroad.group(0)}); check before use'
    review_setting = bool(geo and geo['compatibility'] == 'possible_conflict')
    dark = vc.too_dark(preview)
    if dark:
        visual['reasons'].append('Preview too dark to confirm the content')
    uncertain = vc.bright_uncertain(preview, concept)
    if uncertain:
        visual['reasons'].append('Very bright scene: weather cannot be confirmed from the preview; review by eye')
    height = candidate.get('height') or 0;seconds = candidate.get('seconds') or 0
    usable = (not height or height >= 720) and (not seconds or seconds >= 5)
    # Auto needs a concrete visual need: procedural, context and forecast beats are at most recommended.
    concrete = concept not in ('general_context', 'forecast_warning') and '→' not in visual['concept']
    if (visual['score'] >= AUTO and visual['confidence'] == 'high' and not visual['preview_flags'] and licensing['verified'] and usable
            and height and seconds and concrete and not abroad and not dark and not uncertain and not review_setting):
        tier = 'auto'
    elif visual['score'] >= RECOMMEND and not visual['preview_flags'] and licensing['verified'] and usable:
        # A reliable setting conflict blocks auto-approval and routes to review; it does not erase visual relevance.
        tier = 'recommended'
    else:
        tier = 'weak'
    if geo and abroad:
        visual['reasons'].append(geo['reason'])
    elif review_setting:
        visual['reasons'].append(geo['reason'])
    if vision:
        from .footage_vision import weak_evidence
        if vision['setting_cues']:
            # Observable cues only (signage script, vehicle type); never a country, never a conflict verdict.
            location['visual_setting'] = {'cues': vision['setting_cues'], 'strength': 'weak', 'screener': vision['version'],
                                          'note': 'Possible setting outside the story region; check by eye. Not a location identification.'}
        held = weak_evidence(tier, vision)
        if held != tier:
            visual['reasons'].append('Held for review by preview screening: ' + '; '.join(vision['setting_cues']))
        tier = held
    return {'tier': tier, 'visual': visual, 'provenance': origin, 'licensing': licensing, 'location': location}


SCREENER = 'heuristic-1'


def clean(row):
    """A candidate worth offering without first looking for something better: auto, or recommended with no
    setting doubt (no geographic conflict, no unknown-location street scene, no visual setting cue)."""
    geo = (row.get('location') or {}).get('geography') or {}
    return (row['tier'] == 'auto' or (row['tier'] == 'recommended' and geo.get('compatibility') not in ('conflict', 'possible_conflict')
                                      and not (row.get('location') or {}).get('visual_setting')))


def ambiguous_urban(row):
    location = row.get('location') or {}
    return (location.get('geography') or {}).get('compatibility') == 'possible_conflict' or bool(location.get('visual_setting'))


def score(candidate, scene, advisory, shown=()):
    """Compatibility view of assess(): (score, reasons, recommended) from metadata only."""
    result = assess(candidate, scene, advisory)
    value = result['visual']['score'] - (25 if candidate.get('id') in shown else 0)
    reasons = result['visual']['reasons'] + (['Already offered for an earlier beat'] if candidate.get('id') in shown else [])
    return value, reasons, result['tier'] in ('auto', 'recommended') and candidate.get('id') not in shown


EXTRA_SEARCHES = 10  # per review, across all beats
FALLBACK_PER_BEAT = 2
LIMITED = ('request limit reached', 'rejected the API key')


def cached_query(discovery, query):
    """Whether a search can be answered from the discovery caches (24-hour stock cache, 10-minute search cache)."""
    stock = getattr(discovery, 'stock_cached', None)
    if stock and any(stock((provider, query.casefold())) is not None for provider in ('pexels', 'pixabay')):
        return True
    return any(key[0] == query.strip().casefold() for key in getattr(discovery, 'cache', {}))


async def review(discovery, plan_id, max_beats=10, per_beat=4, fallback=True, screener=None, frames=None, extra_searches=EXTRA_SEARCHES):
    """Per-beat footage review. Nothing is imported.

    With `fallback`, a beat without a clean candidate (see clean()) gets up to two more distinct searches for
    its concept, within a per-review cap; a search already run in this review is never repeated, and repeated
    searches across reviews come from the discovery caches. Forecast beats are not searched: radar, satellite
    and warning maps from source data illustrate them. Beats still without a clean candidate are reported as
    needing review or attention; the edit keeps its honest graphic for them."""
    store = discovery.production.store;plan = store.visual_plan(plan_id)
    discovery.production.validate_plan(plan, require_support=False)
    # Searches come from each beat's visual concept (what the shot must show), rotated across beats of the same concept.
    from .visual_concepts import beat_need, search_variants, fallback_searches, CONCEPTS
    from .footage_expansion import story_regions
    from . import regional
    names = {r['code']: r['name'] for r in regional.options()}
    by_scene, seen_concepts = {}, {}
    for scene in plan['scenes']:
        advisory = store.advisory(scene['parameters'].get('source_advisory_id') or plan['advisory_id'])
        concept = beat_need(scene['script_segment'])
        regions = story_regions(scene['script_segment'], advisory, names)
        place = names[regions[0]] if regions else ''
        graphics_first = fallback and CONCEPTS[concept]['medium'] == 'graphics'
        by_scene[scene['id']] = [] if graphics_first else search_variants(concept, seen_concepts.get(concept, 0), place)
        seen_concepts[concept] = seen_concepts.get(concept, 0) + 1
    beats = plan['scenes'][:max_beats]
    rows, warnings, searched, shown, offered, cache = [], [], {}, set(), [], {}
    stats = {'searches': 0, 'extra_searches': 0, 'cache_hits': 0, 'duplicates_skipped': 0, 'extra_cap': extra_searches, 'provider_limited': False}

    async def run_search(query):
        if query in searched:
            stats['duplicates_skipped'] += 1
            return
        stats['cache_hits'] += cached_query(discovery, query)
        result = await discovery.search(MediaDiscoveryRequest(query=query, provider='all', kind='video', plan_id=plan_id, live=True))
        searched[query] = result['results'];warnings.extend(result['warnings']);stats['searches'] += 1
        if any(text in w for w in result['warnings'] for text in LIMITED):
            stats['provider_limited'] = True

    for scene in beats:
        advisory = store.advisory(scene['parameters'].get('source_advisory_id') or plan['advisory_id'])
        need = beat_need(scene['script_segment']);queries = list(by_scene[scene['id']]);found = {}
        for query in queries:
            await run_search(query)

        async def rank():
            for query in queries:
                for candidate in searched.get(query, []):
                    if candidate['kind'] == 'video' and not candidate.get('local_media_id'):
                        found.setdefault(candidate['id'], candidate)
            # Metadata first, then preview screening for the most promising candidates of this beat.
            first = sorted(found.values(), key=lambda c: -assess(c, scene, advisory)['visual']['score'])[:8]
            features = [await preview_features(c.get('thumbnail_url'), cache, frames) for c in first]
            seen = await screen_frames(screener, features)
            ranked = []
            for candidate, measured in zip(first, features):
                vision = seen.get((measured or {}).get('frame_sha256'))
                found_by_vision = None
                if vision is not None:
                    from .footage_vision import findings
                    found_by_vision = findings(vision, need)
                result = assess(candidate, scene, advisory, measured, [f for f in offered if f], vision=found_by_vision)
                value = result['visual']['score'] - (25 if candidate['id'] in shown else 0)
                ranked.append({'candidate_id': candidate['id'], 'title': candidate['title'], 'provider': candidate.get('provider'),
                               'licence': candidate['license'], 'attribution': candidate['attribution'], 'source': candidate['source'],
                               'width': candidate.get('width'), 'height': candidate.get('height'), 'seconds': candidate.get('seconds'),
                               'bytes': candidate.get('bytes'), 'context': candidate.get('context'), 'thumbnail_url': candidate.get('thumbnail_url'),
                               'score': value, 'reasons': result['visual']['reasons'] + (['Already offered for an earlier beat'] if candidate['id'] in shown else []),
                               'recommended': result['tier'] in ('auto', 'recommended') and candidate['id'] not in shown,
                               'tier': result['tier'] if candidate['id'] not in shown else 'weak', **{k: result[k] for k in ('visual', 'provenance', 'licensing', 'location')},
                               'screening': {'frame_sha256': (measured or {}).get('frame_sha256'), 'screeners': [SCREENER] + ([found_by_vision['version']] if found_by_vision else []),
                                             'vision': found_by_vision},
                               '_features': measured})
            # With fallback, clean candidates come before ones with setting doubts; otherwise by score.
            ranked.sort(key=lambda r: ((not clean(r)) if fallback else 0, -r['score']))
            return ranked, len(first)

        ranked, screened = await rank()
        extra, note = [], None
        if fallback and queries and not any(clean(r) for r in ranked[:per_beat]):
            alternatives = fallback_searches(need, list(searched) + queries, any(ambiguous_urban(r) for r in ranked[:per_beat]), FALLBACK_PER_BEAT)
            for query in alternatives:
                if stats['provider_limited']:
                    note = 'Provider limit reached; no further searches this review';break
                if stats['extra_searches'] >= extra_searches:
                    note = f'Review search cap ({extra_searches}) reached';break
                stats['extra_searches'] += 1;extra.append(query);queries.append(query)
                await run_search(query)
                ranked, screened = await rank()
                if any(clean(r) for r in ranked[:per_beat]):
                    break
            if not extra and not note:
                note = 'No other distinct searches for this beat'
        for row in ranked[:per_beat]:
            offered.append(row.pop('_features'))
        for row in ranked[per_beat:]:
            row.pop('_features', None)
        offered_rows = ranked[:per_beat]
        shown.update(r['candidate_id'] for r in offered_rows)  # Later beats surface different clips first.
        if not queries:
            status, message = 'graphics', 'Forecast beat: radar, satellite and warning maps from source data; no stock search'
        elif any(clean(r) for r in offered_rows):
            status, message = 'ready', 'Clean candidate found' + (' after alternative searches' if extra else '')
        elif any(r['tier'] in ('auto', 'recommended') for r in offered_rows):
            status, message = 'review', 'Only candidates with setting doubts: check by eye before import'
        else:
            status, message = 'needs_attention', 'No suitable footage: the edit keeps its map or data graphic for this beat'
        rows.append({'scene_id': scene['id'], 'narration': scene['script_segment'], 'queries': queries, 'concept': need,
                     'candidates_found': len(found), 'screened': screened, 'status': status, 'status_note': message,
                     'fallback': {'queries': extra, 'note': note} if fallback and (extra or note) else None,
                     'needs': CONCEPTS[need]['shots'], 'best_medium': CONCEPTS[need]['medium'], 'candidates': offered_rows})
    return rows, sorted(set(warnings)), stats


async def screen_frames(screener, features):
    """Optional vision screening of saved preview frames, keyed by frame checksum ({} when unavailable)."""
    import asyncio
    frames = [f for f in features if f and f.get('frame_path')]
    if not screener or not frames:
        return {}
    raw = await asyncio.to_thread(screener.screen, [f['frame_path'] for f in frames])
    if not raw:
        return {}
    return {f['frame_sha256']: raw.get(str(f['frame_path'])) for f in frames if raw.get(str(f['frame_path']))}


async def preview_features(url, cache, frames=None):
    """Measurements of a provider preview frame (cached per URL), or None when no preview is available.
    With `frames`, the frame is kept there under its checksum so screening results are tied to that exact image."""
    from .visual_concepts import measure
    if url in cache:
        return cache[url]
    async with httpx.AsyncClient(headers={'User-Agent': 'WeatherIntelligenceStudio/0.6 (footage review)'}) as client:
        image = await preview(client, url)
    cache[url] = measure(image) if image else None
    if image and frames:
        import hashlib
        data = io.BytesIO();image.save(data, 'JPEG', quality=90);data = data.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        Path(frames).mkdir(parents=True, exist_ok=True)
        path = Path(frames) / f'{digest}.jpg'
        if not path.exists():
            path.write_bytes(data)
        cache[url] = {**cache[url], 'frame_sha256': digest, 'frame_path': str(path)}
    return cache[url]


async def preview(client, url):
    from urllib.parse import urlsplit
    try:
        if not url or urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in PREVIEW_HOSTS:
            return None
        response = await client.get(url, follow_redirects=True, timeout=15)
        response.raise_for_status()
        if len(response.content) > 3 * 1024 * 1024:
            return None
        return Image.open(io.BytesIO(response.content)).convert('RGB')
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def contact_sheet(discovery, rows, folder):
    """One row per beat: the narration, then each candidate's provider preview frame with its key facts."""
    from .broadcast import font
    columns = max([len(r['candidates']) for r in rows] + [1])
    width = 360 + columns * (TILE[0] + 16) + 16;height = 70 + len(rows) * (TILE[1] + 96)
    sheet = Image.new('RGB', (width, height), '#050f17');draw = ImageDraw.Draw(sheet)
    draw.text((16, 18), 'Footage review · nothing imported · green = auto (high confidence) · blue = recommended · amber = weak', font=font(24), fill='#e7f1f8')
    async with httpx.AsyncClient(headers={'User-Agent': 'WeatherIntelligenceStudio/0.6 (footage review)'}) as client:
        for i, row in enumerate(rows):
            y = 70 + i * (TILE[1] + 96)
            import textwrap
            for j, line in enumerate(textwrap.wrap(row['narration'], 34)[:7]):
                draw.text((16, y + j * 24), line, font=font(18), fill='#c9dbe3')
            for k, candidate in enumerate(row['candidates']):
                x = 360 + k * (TILE[0] + 16)
                image = await preview(client, candidate['thumbnail_url'])
                if image:
                    sheet.paste(image.resize(TILE, Image.Resampling.LANCZOS), (x, y))
                else:
                    draw.rectangle((x, y, x + TILE[0], y + TILE[1]), fill='#16303c');draw.text((x + 12, y + 80), 'No preview image', font=font(18), fill='#8fb0bf')
                draw.rectangle((x - 3, y - 3, x + TILE[0] + 2, y + TILE[1] + 2), outline={'auto': '#3ddc84', 'recommended': '#7fb8ff'}.get(candidate.get('tier'), '#ffb347'), width=4)
                facts = f"{candidate.get('tier', '?').upper()} · {candidate['provider']} · {candidate['height'] or '?'}p · {round(candidate['seconds']) if candidate['seconds'] else '?'} s · {candidate['score']}"
                draw.text((x, y + TILE[1] + 6), facts, font=font(16), fill='#e7f1f8')
                draw.text((x, y + TILE[1] + 28), candidate['title'][:38], font=font(15), fill='#c9dbe3')
                draw.text((x, y + TILE[1] + 50), candidate['licence'].split(' http')[0][:40], font=font(14), fill='#8fb0bf')
    folder.mkdir(parents=True, exist_ok=True)
    sheet.save(folder / 'footage-review.jpg', quality=86)


def default_screener(root):
    """Apple Vision on macOS as weak evidence; None elsewhere (screening then uses the heuristics only)."""
    import platform
    if platform.system() != 'Darwin':
        return None
    from .footage_vision import VisionScreen
    return VisionScreen(root)


async def run(discovery, plan_id, screener='default'):
    identity = str(uuid4());root = discovery.production.root / 'footage-reviews';folder = root / identity
    if screener == 'default':
        screener = default_screener(root)
    rows, warnings, stats = await review(discovery, plan_id, screener=screener, frames=root / 'frames')
    await contact_sheet(discovery, rows, folder)
    for row in rows:
        for candidate in row['candidates']:
            candidate['screening'].pop('frame_path', None)
    result = {'id': identity, 'plan_id': plan_id, 'beats': rows, 'warnings': warnings,
              'recommended': sum(c['recommended'] for r in rows for c in r['candidates']),
              'auto': sum(c['tier'] == 'auto' for r in rows for c in r['candidates']),
              'searches': stats, 'unresolved': [{'scene_id': r['scene_id'], 'status': r['status'], 'note': r['status_note'], 'needs': r['needs']}
                                                 for r in rows if r['status'] in ('review', 'needs_attention')],
              'note': 'Nothing was imported. Import chosen clips individually; the existing download limits apply. '
                      'Screening never clears a clip\'s setting: only a reviewer can, in Media Library.'}
    (folder / 'review.json').write_text(json.dumps(result, indent=2))
    return result


async def import_auto(discovery, identity, max_clips=8):
    """User-approved batch import of a review's 'auto' tier: high-confidence, licensed illustrative stock.

    Keeps the existing limits: at most 12 clips per request, the 500 MiB batch budget, the per-file limit,
    licence checks and checksum de-duplication in import_candidate. Weak or merely recommended clips are
    never included."""
    from uuid import UUID
    from .contracts import DiscoveryImportRequest
    from .footage_expansion import BUDGET
    folder = discovery.production.root / 'footage-reviews' / str(UUID(identity))
    review = json.loads((folder / 'review.json').read_text())
    picks, seen = [], set()
    for beat in review['beats']:
        for candidate in beat['candidates']:
            if candidate.get('tier') == 'auto' and candidate['licensing']['verified'] and candidate['candidate_id'] not in seen:
                picks.append(candidate);seen.add(candidate['candidate_id'])
    picks = picks[:max(1, min(12, max_clips))]
    results, used = [], 0
    for candidate in picks:
        if used + (candidate.get('bytes') or 0) > BUDGET:
            results.append({'title': candidate['title'], 'status': 'skipped', 'message': 'Batch download budget reached'});continue
        try:
            asset = await discovery.import_candidate(DiscoveryImportRequest(candidate_id=candidate['candidate_id'], rights_confirmed=True))
            used += asset.get('bytes') or 0
            results.append({'title': candidate['title'], 'status': 'duplicate' if asset.get('duplicate') else 'imported', 'media_id': asset['id'],
                            'provenance': candidate['provenance']['status'], 'licence': candidate['licence']})
        except (ValueError, KeyError) as error:
            results.append({'title': candidate['title'], 'status': 'failed', 'message': str(error)})
    return {'review_id': identity, 'requested': len(picks), 'results': results, 'bytes': used}
