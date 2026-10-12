"""Deterministic local suggestions. Catalogue declarations are not weather evidence."""
import math
import re
from . import regional

GROUPS = {
    'wind': ('wind', 'winds', 'gust', 'gusts', 'windy', 'crosswind', 'crosswinds', 'windblown'),
    'rain': ('rain', 'rainfall', 'raining', 'downpour', 'precipitation'),
    'flood': ('flood', 'floods', 'flooding', 'inundation'),
    'waves': ('wave', 'waves', 'sea', 'seas', 'surf', 'surge'),  # Not 'coast': place names (Gulf Coast) and calm beach shots are not waves.
    'snow': ('snow', 'snowfall', 'blizzard'),
    'lightning': ('lightning', 'thunder', 'thunderstorm', 'thunderstorms'),
    'storm': ('storm', 'storms', 'hurricane', 'cyclone', 'typhoon'),
    'wildfire': ('fire', 'fires', 'wildfire', 'wildfires', 'brushfire'),
    'tornado': ('tornado', 'tornadoes', 'twister'),
    'hail': ('hail', 'hailstorm'),
    'preparedness': ('planning','preparations','prepare','evacuation','evacuations','shelter','sheltered','evacuated','harbor'),
    # Concepts: what a paragraph is about beyond the weather itself.
    'damage': ('damage', 'damaged', 'destroyed', 'debris', 'collapsed', 'wreckage', 'impact', 'impacts'),
    'rescue': ('rescue', 'rescues', 'rescued', 'responders', 'emergency', 'crews', 'guard', 'firefighters'),
    'cleanup': ('cleanup', 'recovery', 'aftermath', 'rebuild', 'rebuilding', 'relief', 'aid', 'volunteers'),
    'power': ('power', 'outage', 'outages', 'electricity', 'utility', 'utilities', 'grid', 'powerlines'),
    'traffic': ('road', 'roads', 'highway', 'highways', 'traffic', 'bridge', 'bridges', 'interstate', 'travel'),
    'residents': ('residents', 'people', 'families', 'community', 'communities', 'neighborhood', 'neighborhoods', 'homes'),
    'sky': ('clouds', 'cloud', 'sky', 'skies', 'overcast', 'darkened'),
    'ice': ('ice', 'icy', 'sleet', 'glaze', 'frozen', 'freezing'),
    'heat': ('heat', 'heatwave', 'hot', 'scorching', 'swelter'),
    'cold': ('cold', 'frigid', 'freeze', 'chill', 'subzero'),
    'drought': ('drought', 'dry', 'parched', 'arid'),
}
CONCEPTS = {'damage', 'rescue', 'cleanup', 'power', 'traffic', 'residents', 'sky'}
# What a clip shows: the weather itself, what it did, the human response, or a general establishing shot.
SHOT_CLASSES = {
    'phenomenon': {'wind', 'rain', 'storm', 'tornado', 'snow', 'hail', 'lightning', 'waves', 'wildfire', 'ice', 'heat', 'cold', 'drought'},
    'impact': {'damage', 'flood', 'power', 'traffic'},
    'response': {'rescue', 'cleanup', 'preparedness', 'residents'},
    'establishing': {'sky'},
}


def shot_classes(tags):
    return {name for name, members in SHOT_CLASSES.items() if members & tags}


def location_confidence(asset):
    catalog = asset.get('catalog', {})
    if catalog.get('location_reviewed') and catalog.get('region_codes'):
        return 'reviewed'
    return 'provisional' if (catalog.get('location') or '').strip() else 'unknown'


def temporal_label(asset, advisory):
    """current: declared capture date is the advisory date; archival: an earlier date; unknown otherwise."""
    captured = asset.get('catalog', {}).get('captured_at') or ''
    issued = getattr(advisory, 'issued_at', None)
    if not captured or issued is None:
        return 'unknown'
    return 'current' if captured[:10] == issued.date().isoformat() else 'archival'
GRAPHICS = {'storm_track', 'cinematic_weather_map', 'what_changed', 'radar_animation', 'satellite_timelapse'}

# Hazard gate. A beat's hazard comes from visual_director.classify; a clip's from its own metadata. Generic
# damage/cleanup/rescue tags never establish a hazard, so hurricane cleanup cannot pass as snowstorm footage.
CLIP_HAZARD_TOPICS = {'tornado': 'tornado', 'hail': 'severe_storm', 'lightning': 'severe_storm', 'flood': 'flood',
                      'snow': 'winter', 'ice': 'winter', 'wildfire': 'wildfire', 'heat': 'heat', 'drought': 'heat', 'cold': 'cold'}
TROPICAL = re.compile(r'\b(hurricane|tropical (?:storm|depression|cyclone)|typhoon|cyclone|eyewall)\b|\b(?:al|ep|cp)\d{6}\b', re.I)
SURGE = re.compile(r'\bsurge\b', re.I)
# Hazards that show the same thing on screen. Flooding is split by kind: a river rising inland is not storm surge.
RELATED = {'tropical_cyclone': {'coastal_flood', 'flood'}, 'coastal_flood': {'tropical_cyclone', 'flood'},
           'river_flood': {'flood'}, 'flash_flood': {'flood', 'river_flood'}, 'flood': {'river_flood', 'flash_flood'},
           'tornado': {'severe_storm'}, 'severe_storm': {'tornado'}, 'winter': {'cold'}, 'cold': {'winter'}, 'high_wind': set()}
# Weather a clip without a named hazard may show on a beat of each hazard. Rough seas are not a snowstorm or a river flood.
COMPATIBLE = {'tropical_cyclone': {'storm', 'waves', 'wind', 'rain', 'flood', 'sky'},
              'coastal_flood': {'flood', 'waves', 'wind', 'rain', 'storm', 'sky'},
              'river_flood': {'flood', 'rain'}, 'flash_flood': {'flood', 'rain', 'storm', 'sky'}, 'flood': {'flood', 'rain', 'storm'},
              'tornado': {'storm', 'wind', 'sky', 'lightning', 'hail', 'rain'}, 'severe_storm': {'storm', 'wind', 'sky', 'lightning', 'hail', 'rain'},
              'high_wind': {'wind', 'sky', 'drought'},
              'winter': {'snow', 'ice', 'cold', 'wind', 'sky'}, 'cold': {'cold', 'ice', 'snow', 'sky', 'wind'},
              'heat': {'heat', 'drought', 'sky'}, 'wildfire': {'wildfire', 'drought', 'heat', 'wind', 'sky'}}
PHENOMENA = SHOT_CLASSES['phenomenon'] | {'flood', 'sky'}
# Topics that name one hazard precisely; generic weather words (storm, wind, rain, sky) do not.
SPECIFIC_HAZARDS = {'hail', 'ice', 'snow', 'tornado', 'flood', 'wildfire', 'drought', 'heat', 'lightning', 'cold'}
GENERIC_WEATHER = {'storm', 'wind', 'rain', 'sky'}
# Kinds of flooding, from words the beat, the alert or the clip's own metadata use.
COASTAL = re.compile(r'\b(storm surge|surge|coastal flood\w*|tides?|tidal|seawalls?|ocean|sea|seas|beach\w*|waves?|shore\w*|coast)\b', re.I)
FLASH = re.compile(r'\b(flash flood\w*|burn scars?|debris flows?|arroyos?|dry wash\w*|washes|slot canyons?|mudslides?|mud flows?|desert)\b', re.I)
RIVER = re.compile(r'\b(rivers?|creeks?|streams?|bayous?|river stage|flood stage|crest\w*|gauges?)\b', re.I)
TROPICAL_SETTING = re.compile(r'\b(palms?|palm trees?|coconut|tropical)\b', re.I)
TROPICAL_STATES = {'FL', 'HI', 'PR', 'VI', 'GU', 'AS', 'MP'}
# Disaster aftermath on screen. It needs a damage beat and damage the story itself reports as having happened.
AFTERMATH = re.compile(r'\b(destroyed|destruction|aftermath|wreckage|collapsed|rubble|demolished|devastat\w*|flattened|debris (?:field|clearance|removal)|'
                       r'road.clearance|temporary.roofs?|blue tarps?)\b', re.I)
OBSERVED_DAMAGE = re.compile(r'\b(damage (?:was |has been |had been )?reported|reports? of (?:damage|destroyed|collapsed|structural)|(?:was|were|has been|have been|had been) '
                             r'(?:damaged|destroyed|flattened|swept away|washed away)|caused (?:extensive |major |significant |severe )?damage|'
                             r'damage (?:left|forced|closed|cut)|left (?:\w+ ){0,2}(?:damage|destruction)|major flooding is (?:occurring|ongoing)|catastrophic|devastat\w+)\b'
                             # A past-tense verb ("winds damaged homes"), never a forecast ("will be damaged or destroyed").
                             r'|(?<!will be )(?<!could be )(?<!may be )(?<!can be )(?<!would be )(?<!be )(?<!damaged or )(?<!damaged and )\b(?:damaged|destroyed|flattened|toppled)\b(?! or destroyed)', re.I)
# Response or context footage that names no hazard may stand in only where its subject fits: downed lines after wind or ice.
CONCEPT_FITS = {'power': {'tropical_cyclone', 'high_wind', 'severe_storm', 'tornado', 'winter', 'cold'}}
NEUTRAL_CONCEPTS = {'traffic', 'residents', 'preparedness'}


HAZARD_TOPICS = {'river_flood': {'flood'}, 'flash_flood': {'flood'}, 'coastal_flood': {'flood', 'waves'}, 'flood': {'flood'},
                 'tropical_cyclone': {'storm'}, 'high_wind': {'wind'}, 'winter': {'snow'}, 'cold': {'cold'}, 'tornado': {'tornado'},
                 'severe_storm': {'lightning', 'hail'}, 'wildfire': {'wildfire'}, 'heat': {'heat'}}


def flood_kind(text, order=('coastal_flood', 'flash_flood', 'river_flood')):
    patterns = {'coastal_flood': COASTAL, 'flash_flood': FLASH, 'river_flood': RIVER}
    return next((kind for kind in order if patterns[kind].search(text)), None)


def beat_hazard(scene, advisory, hazard):
    """A flood beat's kind of flooding: its own words first, then the alert's title, then the alert's text
    (where a river gauge outranks a passing mention of tides). Other hazards are unchanged."""
    if hazard != 'flood':
        return hazard
    title = str(getattr(advisory, 'title', '') or '')
    return (flood_kind(scene.get('script_segment', '')) or flood_kind(title, ('coastal_flood', 'flash_flood'))
            or flood_kind(str(getattr(advisory, 'text', '') or '')[:4000], ('river_flood', 'flash_flood', 'coastal_flood')) or 'flood')


def clip_hazards(asset, tags):
    """Hazards a clip's own metadata names: hazard tags, hurricane words or a tropical event ID, and the kind of flooding shown."""
    from .geo_gate import metadata_text
    text = metadata_text(asset) + ' ' + (asset.get('catalog', {}).get('event_id') or '')
    found = {CLIP_HAZARD_TOPICS[t] for t in tags if t in CLIP_HAZARD_TOPICS}
    if TROPICAL.search(text):
        found.add('tropical_cyclone')
    if 'flood' in found or SURGE.search(text):
        # One kind per clip: surge on a seawall is coastal, a muddy creek is a river, a desert wash is a flash flood.
        found.discard('flood')
        found.add(flood_kind(text) or 'flood')
    return found


def story_regions(scene, advisory):
    codes = set(regional.targets(scene)) | set(re.findall(r',\s*([A-Z]{2})\b', str(getattr(advisory, 'area', '') or '')))
    return codes | set(regional.named_regions(str(getattr(advisory, 'area', '') or '')))


def hazard_fit(beat_hazard, asset, tags, scene=None, advisory=None):
    """(allowed, reason). The clip must show the beat's own hazard, a related one, or hazard-neutral content its metadata shows fits."""
    if beat_hazard not in COMPATIBLE:
        return True, ''
    label = beat_hazard.replace('_', ' ')
    from .geo_gate import metadata_text
    if TROPICAL_SETTING.search(metadata_text(asset)) and beat_hazard not in ('tropical_cyclone', 'coastal_flood') \
            and not (scene is not None and story_regions(scene, advisory) & TROPICAL_STATES):
        return False, f'Shows a tropical setting (palms), which does not fit a {label} story outside tropical states'
    named = clip_hazards(asset, tags)
    if named:
        if beat_hazard in named or named & RELATED.get(beat_hazard, set()):
            return True, ''
        return False, f"Shows {', '.join(sorted(h.replace('_', ' ') for h in named))}, not the {label} this beat reports"
    weather = tags & PHENOMENA
    if weather - COMPATIBLE[beat_hazard]:
        # Every kind of weather on screen must fit: rough seas with wind are still not a snowstorm.
        return False, f"Shows {', '.join(sorted(weather - COMPATIBLE[beat_hazard]))}, which does not fit a {label} beat"
    if weather:
        return True, ''
    # No hazard and no weather in its metadata: only subjects that fit any story of this hazard may stand in.
    concepts = tags & CONCEPTS
    unfit = {c for c in concepts if c not in NEUTRAL_CONCEPTS and beat_hazard not in CONCEPT_FITS.get(c, set())}
    if unfit or not concepts:
        return False, f"Names no hazard; {', '.join(sorted(unfit)) or 'its content'} footage alone cannot be shown as {label}"
    return True, ''


def severity_fit(scene, advisory, asset, tags):
    """(allowed, reason). Destruction and cleanup footage only on a damage beat of a story that reports damage as having happened."""
    from .geo_gate import metadata_text
    # Destruction on screen, from the clip's own words; snow-plow "cleanup" or river "debris" is not aftermath.
    if not (AFTERMATH.search(metadata_text(asset)) or 'damage' in tags):
        return True, ''
    beat = scene.get('script_segment', '')
    if not topics(beat) & {'damage', 'cleanup', 'rescue'}:
        return False, 'Shows damage or cleanup; this beat does not describe damage'
    if not (OBSERVED_DAMAGE.search(beat) or OBSERVED_DAMAGE.search(str(getattr(advisory, 'text', '') or ''))):
        return False, 'Shows damage or cleanup; the story reports no damage as having happened (forecast or threshold only)'
    return True, ''


def topics(text):
    words = set(re.findall(r'[a-z]+', text.lower()))
    return {topic for topic, variants in GROUPS.items() if words.intersection(variants)}


def rank(scene, assets, advisory, unavailable=(), limit=5, allow_unverified=False, excluded=None):
    """Library clips that fit a beat, best first. Clips failing the geographic gate are never returned;
    when `excluded` is a list, each exclusion is recorded there with its reason."""
    from .geo_gate import placement
    # Only the words spoken on this shot; the rest of its paragraph never makes a clip eligible.
    wanted = topics(scene['script_segment'])
    if scene.get('parameters',{}).get('story',{}).get('beat') in ('context','reveal'):
        wanted |= {'storm','rain','wind','waves'}
    # A sentence without weather words still belongs to its story: add the story's own hazard topics (weaker when the
    # sentence names nothing at all). Topics from the rest of the paragraph are never used.
    story_only = not wanted
    if story_only:
        wanted = topics(' '.join(str(getattr(advisory, k, '') or '') for k in ('title', 'forecast_excerpt'))) - CONCEPTS
    from .visual_director import classify, story_text
    intent = scene.get('parameters', {}).get('visual_intent') or classify(scene['script_segment'], story_text(advisory))
    hazard = beat_hazard(scene, advisory, intent['hazard'])
    # Generic weather words ("storm rainfall keeps the river high") stand for the beat's hazard, its own words first, else
    # the story's: that line wants flood footage, not any storm clip.
    if wanted & GENERIC_WEATHER and not wanted & SPECIFIC_HAZARDS:
        wanted |= HAZARD_TOPICS.get(hazard, set())
    results = []
    for asset in assets:
        if asset['kind'] == 'audio' or asset['id'] in unavailable or not asset.get('rights_confirmed') or asset.get('quarantined'):
            continue
        gate = placement(asset, scene.get('script_segment', ''), advisory)
        if not gate['allowed']:
            if excluded is not None:
                excluded.append({'media_id': asset['id'], 'name': asset['name'], 'scene_id': scene.get('id'),
                                 'compatibility': gate['compatibility'], 'reason': gate['reason']})
            continue
        if 'images.nasa.gov' in asset.get('source','') and not topics(asset.get('name','')):
            # Query-derived tags alone cannot turn a space launch into weather footage.
            continue
        place = regional.location_status(scene, asset)
        if place == 'elsewhere' or (place in ('unverified', 'nearby') and not allow_unverified):
            continue
        catalog = asset.get('catalog', {})
        tags = topics(' '.join(catalog.get('tags', [])) + ' ' + asset['name'])
        shared = wanted & tags
        if not shared:
            continue
        fits, why = hazard_fit(hazard, asset, tags, scene, advisory)
        named_match = fits and hazard in clip_hazards(asset, tags)
        if fits:
            fits, why = severity_fit(scene, advisory, asset, tags)
        if not fits:
            # A different hazard is never placed, however plausible its place or weather; the beat keeps its map or graphic.
            if excluded is not None:
                excluded.append({'media_id': asset['id'], 'name': asset['name'], 'scene_id': scene.get('id'),
                                 'compatibility': 'hazard_mismatch', 'reason': why})
            continue
        classes = shot_classes(tags)
        seconds = min(4, max(3, asset.get('preferred_clip_seconds', 3.5)))
        start = catalog.get('preferred_trim_start', 0)
        if asset['kind'] == 'video' and start + seconds > asset['seconds'] + .01:
            continue
        reasons = (['Reviewed capture region matches script'] if place == 'reviewed' else ['Filming location not verified; labelled on screen'] if place == 'unverified'
                   else [f"Filmed in {catalog.get('location') or ', '.join(catalog.get('region_codes', []))}, a comparable region; labelled on screen"] if place == 'nearby' else []) + [('Story topics: ' if story_only else 'Weather topics: ') + ', '.join(sorted(shared))]
        # When the beat names a specific hazard, generic weather words count half for a clip that does not show it.
        diluted = (wanted & SPECIFIC_HAZARDS) and not (shared & SPECIFIC_HAZARDS)
        score = sum(6 if topic in CONCEPTS else 5 if diluted and topic in GENERIC_WEATHER else 10 for topic in shared) + (2 if asset['kind'] == 'video' else 0) - (6 if story_only else 0) - (8 if place == 'unverified' else 12 if place == 'nearby' else 0)
        specific = shared & SPECIFIC_HAZARDS
        if specific:
            score += 8  # Footage of the beat's own hazard (hail, ice, snow…) outranks hazard-neutral or same-category weather.
            reasons.append(f"Shows the beat's hazard: {', '.join(sorted(specific))}")
        elif named_match:
            score += 4  # Same hazard category only (snow on an ice-storm beat, lightning on a hail beat).
            reasons.append(f"Shows the beat's hazard category: {hazard.replace('_', ' ')}")
        event = catalog.get('event_id', '')
        if event and event.casefold() == advisory.event_key.casefold():
            score += 30
            reasons.append('Declared event ID matches; attribution remains contextual')
        elif event:
            score -= 5
            reasons.append('Different event: ' + event + '; archival context only')
        if catalog.get('captured_at'):
            if catalog['captured_at'] == advisory.issued_at.date().isoformat():
                score += 10
                reasons.append('Declared capture date matches advisory date')
            else:
                reasons.append('Capture date differs from advisory date')
        location = catalog.get('location', '').strip()
        if place == 'reviewed':
            score += 10  # Footage reviewed as filmed in the story's state outranks generic footage of the same hazard.
        if location and location.casefold() in scene['script_segment'].casefold():
            score += 10
            reasons.append('Declared location appears in script')
        elif place == 'unverified' and regional.named_regions(location) and not set(regional.named_regions(location)) & set(regional.targets(scene)):
            score -= 10
            reasons.append(f'Declared as filmed in {location}, not the place this beat names; labelled location not verified')
        # The beat's meaning decides what the shot should show.
        wanted_class = intent['footage_class']
        if wanted_class in classes:
            score += 8
            reasons.append(f'Shows {wanted_class}, as a {intent["intent"]} beat needs')
        elif wanted_class in ('impact', 'response') and classes <= {'phenomenon', 'establishing'}:
            score -= 4
            reasons.append(f'Shows the weather, not the {wanted_class} this beat describes')
        if classes == {'establishing'} and wanted_class != 'establishing':
            score -= 6  # General atmosphere never outranks specific evidence.
        width = asset.get('width') or 0
        if width >= 1920:
            score += 2
        elif width and width < 1280:
            score -= 3
            reasons.append('Below 720p')
        results.append({'media_id': asset['id'], 'name': asset['name'], 'score': score,
                        'reasons': reasons, 'seconds': seconds, 'trim_start': start,
                        'shot_classes': sorted(classes), 'location_confidence': location_confidence(asset), 'location_status': place,
                        'temporal': temporal_label(asset, advisory),
                        'context': asset['context'], 'source_provider': asset.get('source_provider', 'local'),
                        'attribution': asset['attribution'], 'source': asset['source'],
                        'label': asset['context'].upper() + ' FOOTAGE'})
    return sorted(results, key=lambda row: (-row['score'], row['media_id']))[:limit]


def unique(excluded):
    """One exclusion record per clip, for review and debugging."""
    seen = {}
    for row in excluded:
        seen.setdefault(row['media_id'], row)
    return list(seen.values())


def draft(plan, assets, advisory, unavailable=(), template='short_30'):
    """Preserve every claim once, protecting geographic/data scenes and closing."""
    scenes = plan['scenes']
    if template != 'short_30':
        return report(plan, assets, advisory, unavailable, template)
    if not 1 <= len(scenes) <= 30:
        raise ValueError('The 30-second template needs 1–30 source-linked scenes. Use manual timing for this plan.')
    used = set();excluded = []
    edits, suggestions, issues = [], [], []
    for i, scene in enumerate(scenes):
        choices = rank(scene, assets, advisory, unavailable, excluded=excluded)
        protected = scene['type'] in GRAPHICS or i == len(scenes) - 1
        selected = next((c for c in choices if c['media_id'] not in used), None) if not protected else None
        if selected:
            used.add(selected['media_id'])
        elif not protected:
            issues.append({'scene_id': scene['id'], 'code': 'missing_footage', 'message': 'No unused matching clip; source graphic retained.'})
        if scene.get('parameters', {}).get('unavailable_requested_layer'):
            issues.append({'scene_id': scene['id'], 'code': 'missing_observation', 'message': scene['parameters'].get('reason', 'Requested observation unavailable.')})
        suggestions.append({'scene_id': scene['id'], 'protected_graphic': protected, 'candidates': choices})
        edits.append({'id': scene['id'], 'media_id': selected['media_id'] if selected else None,
                      'seconds': selected['seconds'] if selected else 1,
                      'trim_start': selected['trim_start'] if selected else 0, 'transition': 'cut'})
    # Reserve one second per graphic. If the plan has too many short cuts, keep
    # earlier claims as graphics rather than shrinking footage below three seconds.
    for row in reversed(edits):
        if sum(round(e['seconds'] * 30) for e in edits) <= 900:
            break
        if row['media_id']:
            row.update(media_id=None, seconds=1, trim_start=0)
            issues.append({'scene_id': row['id'], 'code': 'timing_fallback', 'message': 'Source graphic retained to fit all claims into 30 seconds.'})
    graphics = [i for i, row in enumerate(edits) if not row['media_id']]
    extra = 900 - sum(round(e['seconds'] * 30) for e in edits)
    weights = [max(1, len(scenes[i]['script_segment'].split())) for i in graphics]
    # Avoid a long script quotation dominating the edit. Six seconds per
    # graphic is the normal cap; sparse plans need longer holds to reach 30s.
    capacity = max(180, math.ceil((extra + 30 * len(graphics)) / len(graphics))) - 30
    frames = [0 for _ in graphics]
    remaining = extra
    while remaining:
        active = [i for i in range(len(frames)) if frames[i] < capacity]
        weight_sum = sum(weights[i] for i in active)
        exact = {i: remaining * weights[i] / weight_sum for i in active}
        added = {i: min(capacity - frames[i], int(exact[i])) for i in active}
        if not sum(added.values()):
            for i in sorted(active, key=lambda i: (-exact[i], i))[:remaining]:
                added[i] = 1
        for i, count in added.items():
            frames[i] += count
            remaining -= count
    if capacity > 150:
        issues.append({'code': 'sparse_plan', 'message': 'This plan has few graphic scenes; some holds exceed six seconds. A fuller scene plan gives a faster edit.'})
    for index, count in zip(graphics, frames):
        edits[index]['seconds'] = (30 + count) / 30
    return {'template': 'short_30', 'seconds': 30, 'scenes': edits, 'suggestions': suggestions, 'issues': issues, 'excluded_footage': unique(excluded),
            'presentation': 'broadcast', 'music': True, 'satellite_context': False,
            'note': 'Local library suggestions; catalogue matches do not verify event attribution. Every source-linked claim is preserved. Review the draft before saving.'}


def report(plan, assets, advisory, unavailable, template):
    target = {'report_60': 60, 'report_90': 90}[template]
    scenes = plan['scenes']
    if not 3 <= len(scenes) <= 15:
        raise ValueError('Report templates need 3–15 source-linked scenes. Prepare a fuller scene plan or use manual timing.')
    edits, suggestions, slots, issues, excluded = [], [], [], [], []
    for i, scene in enumerate(scenes):
        protected = i in (0, len(scenes)-1) or scene['type'] in GRAPHICS
        choices = rank(scene, assets, advisory, unavailable, excluded=excluded)
        suggestions.append({'scene_id': scene['id'], 'protected_graphic': protected, 'candidates': choices})
        edits.append({'id': scene['id'], 'media_id': None, 'trim_start': 0, 'seconds': 3 if i in (0,len(scenes)-1) else 6, 'transition': 'cut', 'cuts': []})
        if not protected and choices:
            slots.append(i)
            edits[-1]['seconds'] = 0
    remaining = target*30 - sum(round(s['seconds']*30) for s in edits)
    if remaining < 0:
        raise ValueError('This report has too many graphic scenes for the selected duration. Use the longer template or manual timing.')
    by_id = {a['id']: a for a in assets}
    offsets, uses = {}, {}
    count = math.ceil(remaining/120) if remaining else 0
    lengths = [remaining//count + (1 if i < remaining%count else 0) for i in range(count)] if count else []
    ready = bool(slots) and (not lengths or min(lengths) >= 90)
    filled = 0
    for frames in lengths if ready else []:
        found = None
        for step in range(len(slots)):
            index = slots[(filled+step)%len(slots)]
            choices = sorted(suggestions[index]['candidates'], key=lambda c: (uses.get(c['media_id'],0),-c['score'],c['media_id']))
            for candidate in choices:
                asset = by_id[candidate['media_id']]
                start = offsets.get(asset['id'], round(candidate['trim_start']*30))
                if asset['kind'] == 'image' and uses.get(asset['id'],0):
                    continue
                if asset['kind'] == 'video' and start+frames > math.floor(asset['seconds']*30):
                    continue
                found = index, candidate, start
                break
            if found:
                break
        if not found:
            ready = False
            break
        index, candidate, start = found
        edits[index]['cuts'].append({'media_id':candidate['media_id'],'seconds':frames/30,'trim_start':start/30})
        edits[index]['seconds'] += frames/30
        offsets[candidate['media_id']] = start+frames
        uses[candidate['media_id']] = uses.get(candidate['media_id'],0)+1
        filled += 1
    for row in edits:
        if not row['cuts'] and not row['seconds']:
            row['seconds'] = 1
    actual = sum(round(s['seconds']*30) for s in edits)/30
    ready = ready and actual == target
    if not ready:
        issues.append({'code':'insufficient_footage','message':f'Not enough matching, unused footage to build {target} seconds with 3–4 second cuts. Add clips or choose the shorter template.'})
    return {'template':template,'target_seconds':target,'seconds':actual,'ready':ready,'scenes':edits,'suggestions':suggestions,'issues':issues,'excluded_footage':unique(excluded),
            'presentation':'broadcast','music':True,'satellite_context':False,
            'note':'Report draft preserves claim order. Multiple footage cuts share each script scene; source ranges are never repeated or looped. Graphic holds stay at six seconds or less.'}
