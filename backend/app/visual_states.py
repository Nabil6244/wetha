"""Vary graphic shots across distinct, source-bound visual states.

Every state is drawn only from data already pinned to the scene: reported geography,
named places, source facts, measured changes and original source wording. A state is
offered only when its data exists, so variety never invents a measurement or location.
"""
import copy
import re
from . import geography, graphic_styles, visual_director

WINDOW = 4          # A state may not return within this many shots.
CONTENT_WINDOW = 12  # The same card for the same story may not return within this many shots.
FACTS = {'wind_mph': ('SUSTAINED WIND', 'mph'), 'pressure_mb': ('CENTRAL PRESSURE', 'mb'),
         'rainfall_inches': ('RAINFALL', 'in'), 'category': ('CATEGORY', ''), 'movement_mph': ('MOVEMENT', 'mph')}
# State -> (family, base score). Families keep the rhythm alternating between maps and cards.
STATES = {
    'wide': ('map', 3), 'push_in': ('map', 5), 'pull_out': ('map', 4), 'pan': ('map', 4),
    'track_follow': ('map', 6), 'place_callout': ('map', 6), 'split_facts': ('split', 5),
    'stat_card': ('card', 5), 'quote_card': ('card', 4),
    'change_gauge': ('card', 6), 'comparison_split': ('card', 5), 'question_reveal': ('card', 5),
    'advisory_timeline': ('card', 5), 'source_card': ('card', 1), 'severe_outlook': ('map', 7),
    'place_focus': ('map', 6), 'county_focus': ('map', 5), 'warning_card': ('card', 6),
    'radar_loop': ('observation', 8), 'satellite_loop': ('observation', 7),
}
CAMERA_ONLY = {'wide', 'pan', 'push_in', 'pull_out', 'track_follow'}  # Moves over the same story map.
NWS_COLORS = {'Tornado Warning': '#ff2a2a', 'Severe Thunderstorm Warning': '#ffa500', 'Flash Flood Warning': '#b22222',
              'Flood Warning': '#00c853', 'Storm Surge Warning': '#b524f7', 'Special Marine Warning': '#ffa500',
              'Hurricane Warning': '#dc143c', 'Tropical Storm Warning': '#e0543c', 'Coastal Flood Warning': '#228b22'}


def layer_of(state, key, scene=None):
    """The underlying picture a shot shows. Camera moves over one map share a layer."""
    if state in CAMERA_ONLY or state == 'hold':
        return 'story_map'
    if state in ('place_focus', 'county_focus', 'warning_card'):
        return state + ':' + key
    if state == 'footage' and scene is not None:
        return 'footage:' + ','.join(sorted({c['media_id'] for c in scene.get('cuts', [])} | ({scene['media_id']} if scene.get('media_id') else set())))
    return state
# Neutral lower-third labels so consecutive map shots do not repeat one headline.
HEADLINES = {'wide': 'REGIONAL OVERVIEW', 'pan': 'ACROSS THE REGION', 'push_in': 'CLOSER LOOK',
             'pull_out': 'THE WIDER VIEW', 'track_follow': 'REPORTED STORM TRACK', 'split_facts': 'SOURCE FACTS',
             'stat_card': 'KEY SOURCE NUMBERS', 'quote_card': 'ORIGINAL SOURCE WORDING', 'severe_outlook': 'SEVERE WEATHER OUTLOOK',
             'radar_loop': 'RADAR', 'satellite_loop': 'SATELLITE VIEW'}
QUOTE_CUES = re.compile(r'\b(forecast|expected|warn\w*|advis\w*|said|says|according|urge\w*|official\w*)\b', re.I)
NUMBER = re.compile(r'\d')


def facts(parameters):
    values = parameters.get('facts', {})
    return [(key, values[key]) for key in FACTS if isinstance(values.get(key), (int, float)) and not isinstance(values.get(key), bool)]


def records(parameters):
    rows = [{**f['properties'], 'coordinates': f['geometry']['coordinates']} for f in parameters.get('geojson', {}).get('features', [])
            if f.get('properties', {}).get('kind') == 'reported_center' and f['geometry']['type'] == 'Point']
    return sorted(rows, key=lambda r: r.get('issued_at', ''))


def centroid(parameters):
    points = []
    def collect(value):
        if len(value) >= 2 and isinstance(value[0], (int, float)):
            points.append(value[:2])
        else:
            for child in value:
                collect(child)
    for feature in parameters.get('geojson', {}).get('features', []):
        collect(feature['geometry']['coordinates'])
    if not points:
        return None
    return [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]


def sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', ' '.join((text or '').split())) if len(s.split()) >= 6]


def eligible(scene):
    """Only automatic geographic graphic shots are varied; chosen media, maps, charts and observations stay as set."""
    direction = scene.get('direction', {})
    return (not scene.get('media_id') and not scene.get('cuts') and scene.get('map_mode', 'auto') == 'auto'
            and scene.get('graphic_style', 'auto') == 'auto' and not scene['parameters'].get('report_graphs')
            and not direction.get('asset_ids') and direction.get('scene_type') in ('region_focus', 'storm_track'))


def family_of(scene):
    if scene.get('media_id') or scene.get('cuts'):
        return 'footage'
    state = scene['parameters'].get('visual_state')
    if state in STATES:
        return STATES[state][0]
    if scene['parameters'].get('report_graphs'):
        return 'chart'
    if scene.get('direction', {}).get('asset_ids'):
        return 'observation'
    if scene.get('graphic_style', 'auto') != 'auto' or scene.get('direction', {}).get('scene_type') == 'statistics':
        return 'card'
    return 'map'


def candidates(scene, advisory):
    p = scene['parameters'];text = scene['script_segment'];story = p.get('source_advisory_id', '')
    mentioned = [(name, coord) for name, coord in p.get('places', []) if name.casefold() in text.casefold()]
    places = mentioned or p.get('places', [])
    track = records(p);numbers = facts(p);center = centroid(p)
    changes = [c for c in p.get('changes', []) if c['field'] in ('wind_mph', 'pressure_mb') and all(isinstance(c.get(k), (int, float)) for k in ('previous', 'current'))]
    quotes = sentences(advisory.forecast_excerpt) + [w for w in advisory.warnings if len(w.split()) >= 4]
    rows = [('wide', story, 0), ('pan', story, 0), ('pull_out', story, 0)]
    if center or track:
        rows.append(('push_in', story, 0))
    if track:
        rows.append(('track_follow', story, 2 if re.search(r'\b(mov\w*|track\w*|path|head\w*|north|south|east|west)\b', text, re.I) else 0))
    for name, coord in places[:3]:
        rows.append(('place_callout', story + name, 4 if (name, coord) in mentioned else 0))
    if numbers:
        cue = 3 if NUMBER.search(text) else 0
        rows += [('stat_card', story, cue), ('split_facts', story, cue)]
    for index, quote in enumerate(quotes[:4]):
        rows.append(('quote_card', story + str(index), 3 if QUOTE_CUES.search(text) else 0))
    if changes:
        cue = 3 if re.search(r'\b(strength\w*|weaken\w*|rose|rise|fell|drop\w*|increas\w*|decreas\w*|change\w*)\b', text, re.I) else 0
        rows += [('change_gauge', story, cue), ('comparison_split', story, cue), ('question_reveal', story, cue - 1)]
    if len(track) >= 2:
        rows.append(('advisory_timeline', story, 1))
    # Places named only for another story the beat cites are that story's shots, not this one's.
    cited = set(p.get('regional_cited_codes', []))
    places = [m for m in geography.mentions(text) if not set(m['states']) <= cited]
    if places:
        # Spoken place names get their own shot at the beat where they are said.
        rows.append(('place_focus', '|'.join(dict.fromkeys(m['name'] for m in places)), 9))
    if p.get('county_shapes'):
        names = [s['name'].split(',')[0].strip() for s in p['county_shapes']]
        rows.append(('county_focus', story, 5 if any(re.search(r'(?<!\w)' + re.escape(n) + r'(?!\w)', text, re.I) for n in names) else 2))
    spoken = geography.county_mentions(text, geography.story_states(p, advisory, text) - cited, geography.alert_codes(p, advisory))
    if spoken:
        # A county named in this beat is the most specific place on screen: it outranks its state.
        rows.append(('county_focus', 'spoken:' + ','.join(m['code'] for m in spoken), 10))
    if getattr(advisory, 'provider', '') == 'NWS' and (p.get('facts') or {}).get('description'):
        rows.append(('warning_card', story, 4 if re.search(r'\b(warn\w*|bulletin|alert|issued|in effect|until|expires?)\b', text, re.I) else 1))
    if p.get('radar_option'):
        rows.append(('radar_loop', ','.join(p['radar_option'].get('frames', [])[-2:]) or story, 5 if re.search(r'\b(rain\w*|storm\w*|thunder\w*|radar|downpour\w*|shower\w*|squall\w*)\b', text, re.I) else 2))
    if p.get('satellite_option'):
        rows.append(('satellite_loop', ','.join(p['satellite_option'].get('frames', [])[-2:]) or story, 4 if re.search(r'\b(clouds?|system|satellite|organiz\w*|develop\w*|storm)\b', text, re.I) else 1))
    if p.get('outlook'):
        rows.append(('severe_outlook', story + p['outlook']['id'], 3 if re.search(r'\b(tornado\w*|severe|thunderstorm\w*|hail|damaging winds?)\b', text, re.I) else 0))
    rows.append(('source_card', story, 0))
    return rows


def apply(scene, state, key, advisory):
    p = scene['parameters'];direction = scene['direction'];camera = {'movement': 'camera_drift', 'easing': 'smoothstep'}
    p.pop('camera_span', None)  # A new state is a real cut; its motion runs from the start.
    for stale in ('visual_state', 'focus_coord', 'focus_label', 'state_quote', 'state_facts', 'state_places', 'place_warning', 'warning_card', 'spoken_counties'):
        p.pop(stale, None)
    p['visual_state'] = state
    if state in HEADLINES:
        direction['headline'] = HEADLINES[state]
    track = records(p)
    if state == 'wide':
        camera.update(start_zoom=1, end_zoom=1.05)
    elif state == 'pan':
        camera.update(movement='geographic_pan', start_zoom=1.3, end_zoom=1.3, start_center=(.36, .5), end_center=(.64, .5))
    elif state in ('push_in', 'pull_out', 'track_follow'):
        p['focus_coord'] = track[-1]['coordinates'] if track else centroid(p)
        zoom = (1, 1.55) if state != 'pull_out' else (1.55, 1)
        camera.update(movement='smooth_zoom_out' if state == 'pull_out' else 'smooth_zoom_in', start_zoom=zoom[0], end_zoom=zoom[1], easing='cubic' if state == 'track_follow' else 'smoothstep')
    elif state == 'place_callout':
        name, coord = next((n, c) for n, c in p.get('places', []) if key.endswith(n))
        p['focus_coord'] = coord;p['focus_label'] = name;direction['headline'] = name.upper()[:60]
        camera.update(movement='region_focus', start_zoom=1, end_zoom=1.45)
    elif state == 'place_focus':
        names = key.split('|')
        places = [m for m in geography.mentions(scene['script_segment']) if m['name'] in names]
        p['state_places'] = places
        boxes = [m['extent'] for m in places]
        p['bounds'] = [min(b[0] for b in boxes) - .8, min(b[1] for b in boxes) - .6, max(b[2] for b in boxes) + .8, max(b[3] for b in boxes) + .6]
        p['place_warning'] = [f for f in p.get('geojson', {}).get('features', []) if f.get('properties', {}).get('kind') == 'alert_area']
        direction['fallback'] = None;direction['headline'] = ' · '.join(names).upper()[:60]
        camera.update(start_zoom=1, end_zoom=1.06)
    elif state == 'county_focus':
        text = scene['script_segment'];states = geography.story_states(p, advisory, text) - set(p.get('regional_cited_codes', []))
        spoken = geography.county_mentions(text, states, geography.alert_codes(p, advisory))
        shapes = p.get('county_shapes', [])
        if key.startswith('spoken:'):
            codes = key.split(':', 1)[1].split(',');have = {s['code'] for s in shapes}
            # A new list: the story's alert outlines are shared by its other shots.
            p['county_shapes'] = shapes = shapes + [geography.bundled_county(c) for c in codes if c not in have]
            direction['headline'] = ' · '.join(m['name'].upper() for m in spoken)[:60]
        names = {s['code'] for s in shapes};words = max(1, len(text.split()))
        # Each named county lights up at the point in the shot where its name is said.
        p['spoken_counties'] = {m['code']: round(m['word'] / words, 3) for m in spoken if m['code'] in names}
        focus = [s for s in shapes if s['code'] in p['spoken_counties']] if key.startswith('spoken:') else shapes;points = []
        for shape in focus:
            for polygon in (shape['geometry']['coordinates'] if shape['geometry']['type'] == 'MultiPolygon' else [shape['geometry']['coordinates']]):
                points += polygon[0]
        p['bounds'] = [min(q[0] for q in points) - .5, min(q[1] for q in points) - .35, max(q[0] for q in points) + .5, max(q[1] for q in points) + .35]
        p['place_warning'] = [f for f in p.get('geojson', {}).get('features', []) if f.get('properties', {}).get('kind') == 'alert_area']
        direction['fallback'] = None
        if not key.startswith('spoken:'):
            direction['headline'] = (getattr(advisory, 'title', '') or 'Warned counties').upper()[:60]
        camera.update(start_zoom=1, end_zoom=1.08)
    elif state == 'warning_card':
        p['warning_card'] = warning_details(advisory)
        direction['headline'] = p['warning_card']['event'].upper()[:60]
    elif state in ('radar_loop', 'satellite_loop'):
        option = p['radar_option' if state == 'radar_loop' else 'satellite_option']
        scene['direction'] = copy.deepcopy(option['direction'])
        scene['direction']['duration'] = max(1, scene['seconds'])
        p.update(copy.deepcopy(option['parameters']))
        return
    elif state == 'severe_outlook':
        from . import spc
        p['bounds'] = spc.bounds(p['outlook'])
        camera.update(start_zoom=1, end_zoom=1.06)
        # The outlook itself is the source layer here, so the missing-imagery fallback label does not apply.
        direction['fallback'] = None
        issued = p['outlook'].get('issued_at', '')[:16].replace('T', ' ')
        p['credit'] = f"NOAA/NWS Storm Prediction Center · Day {p['outlook']['day']} outlook issued {issued} UTC"
    elif state == 'split_facts':
        p['state_facts'] = facts(p)
        camera.update(start_zoom=1.12, end_zoom=1.16, start_center=(.6, .5), end_center=(.6, .5))
    elif state == 'stat_card':
        p['state_facts'] = facts(p)
    elif state == 'quote_card':
        quotes = sentences(advisory.forecast_excerpt) + [w for w in advisory.warnings if len(w.split()) >= 4]
        p['state_quote'] = {'text': quotes[int(key[-1])], 'provider': advisory.provider, 'issued_at': advisory.issued_at.isoformat()}
    if state in graphic_styles.STYLES:
        scene['graphic_style'] = state
        graphic_styles.prepare(scene, advisory)
        scene['graphic_style'] = 'auto'  # Chosen automatically; the request still says automatic.
        return
    direction['camera'] = camera


def assign(scenes, advisory_lookup):
    """Pick a state per shot: never the same state within WINDOW shots, never two cards in a row,
    never the same card content for a story within CONTENT_WINDOW shots."""
    history = [];content = [];usage = {};layers = [];shown = {}
    for scene in scenes:
        if not eligible(scene):
            family = family_of(scene)
            history.append((family, family));content.append(None)
            layers.append(layer_of('footage', '', scene) if family == 'footage' else family)
            continue
        advisory = advisory_lookup(scene['parameters'].get('source_advisory_id'))
        intent = visual_director.classify(scene['script_segment'], visual_director.story_text(advisory))
        scene['parameters']['visual_intent'] = intent
        recent_states = {s for s, _ in history[-WINDOW:]}
        recent_content = set(c for c in content[-CONTENT_WINDOW:] if c)
        previous_family = history[-1][1] if history else None
        best = None;scored = [];offered = candidates(scene, advisory)
        for state, key, cue in offered:
            family, base = STATES[state]
            # Each named place is new content, so place shots are limited by repeating the same place, not the state.
            if (state in recent_states and state != 'place_focus') or (state, key) in recent_content:
                continue
            if family == 'observation' and shown.get((state, key), 0) >= 2:
                continue  # The same radar or satellite frames at most twice per video, whichever story cites them.
            if family in ('card', 'split') and previous_family in ('card', 'split', 'chart'):
                continue
            layer = layer_of(state, key)
            if len(layers) >= 2 and layers[-1] == layers[-2] == layer:
                continue  # Never a third consecutive shot of the same underlying picture.
            if layers and layers[-1] == layer and state not in ('place_focus',):
                cue -= 5  # A camera move over the same picture is not a new visual.
            # Meaning first: states the narration calls for outrank generic variety.
            fit = visual_director.bonus(state, intent)
            score = base + cue + fit - usage.get(state, 0) * 1.5 - (3 if family == previous_family else 0)
            scored.append((score, state, fit))
            if best is None or score > best[0]:
                best = (score, state, key)
        scored.sort(key=lambda r: -r[0])
        scene['parameters']['state_meta'] = {'available': sorted({s for s, _, _ in offered}),
            'alternatives': [{'state': s, 'score': round(v, 1)} for v, s, _ in scored[1:4]]}
        if best is None:
            # Nothing new is available: hold the previous motion rather than repeat a look.
            history.append(('hold', 'map'));content.append(None);layers.append('story_map')
            continue
        _, state, key = best
        fit = next(f for _, s, f in scored if s == state)
        scene['parameters']['state_meta'].update(chosen=state, fallback='Regional overview map',
            reason=(f"{state.replace('_', ' ').capitalize()} suits a {intent['intent']} beat and its evidence exists" if fit else
                    f"{state.replace('_', ' ').capitalize()}: the most varied evidence-backed view; the preferred views were used recently or lack data"))
        apply(scene, state, key, advisory)
        usage[state] = usage.get(state, 0) + 1;shown[(state, key)] = shown.get((state, key), 0) + 1
        history.append((state, STATES[state][0]));layers.append(layer_of(state, key))
        scene['parameters']['visual_layer'] = layers[-1]
        content.append((state, key) if STATES[state][0] != 'map' or state in ('place_callout', 'place_focus') else None)
    return [h[0] for h in history]


def warning_details(advisory):
    """Verbatim fields from an NWS alert for the warning card. Nothing is paraphrased or computed."""
    facts = advisory.facts or {};text = ' '.join((facts.get('description') or '').split())
    props = (getattr(advisory, 'source_payload', None) or {}).get('properties', {})
    def section(name):
        match = re.search(name + r'\.\.\.(.+?)(?= [A-Z]{4,}\.\.\.| \* |$)', text)
        return match.group(1).strip() if match else ''
    lead = next((s for s in re.split(r'(?<=\.)\s+', text) if re.match(r'At \d', s)), '')
    rain = re.search(r'((?:Between [\d.]+ and [\d.]+|[\d.]+(?: to [\d.]+)?) inches of rain (?:have|has) fallen\.?)', text)
    places = re.search(r'include(?:s)?\.\.\.\s*(.+?)(?:\.|$)', text)
    return {'event': advisory.title.split(' issued')[0], 'office': props.get('senderName') or 'National Weather Service',
            'issued_at': advisory.issued_at.isoformat(), 'expires_at': advisory.expires_at.isoformat() if advisory.expires_at else None,
            'areas': [a.strip() for a in (advisory.area or '').split(';') if a.strip()][:6],
            'hazard': section('HAZARD'), 'source': section('SOURCE'), 'impact': section('IMPACT'), 'lead': lead,
            'rain': rain.group(1) if rain else '', 'places': [x.strip() for x in places.group(1).split(',')][:8] if places else [],
            'color': NWS_COLORS.get(advisory.title.split(' issued')[0], '#65e1d1')}


def draw(image, p, t):
    """Render the card or panel for a state. Values are the pinned source values, revealed, never interpolated."""
    import textwrap
    from datetime import datetime
    from PIL import ImageDraw
    from .broadcast import label, easing
    state = p.get('visual_state');d = ImageDraw.Draw(image)
    if state == 'stat_card':
        rows = p.get('state_facts', [])[:3]
        d.rectangle((0, 82, 1920, 970), fill='#081d2c')
        label(d, (110, 190), 'BY THE NUMBERS', 40, '#65e1d1')
        width = 1700 / max(1, len(rows))
        for i, (key, value) in enumerate(rows):
            title, unit = FACTS[key];x = 110 + i * width
            u = easing(min(1, max(0, (t - i * .12) * 3)))
            if u <= 0:
                continue
            label(d, (x, 330), title, 30, '#a8c4d0')
            label(d, (x, 400), f'{value:g}', 170, '#ecf6fa')
            label(d, (x + 8, 610), unit.upper(), 40, '#65e1d1')
            d.rectangle((x, 690, x + (width - 80) * u, 700), fill='#65e1d1')
        label(d, (110, 820), 'Values as reported in the source record', 26, '#a8c4d0')
    elif state == 'quote_card':
        quote = p['state_quote'];lines = textwrap.wrap(quote['text'], 44)[:6]
        d.rectangle((0, 82, 1920, 970), fill='#0a2230')
        label(d, (110, 150), '“', 220, '#65e1d1')
        label(d, (230, 205), 'IN THE SOURCE’S WORDS', 32, '#65e1d1')
        shown = max(1, min(len(lines), 1 + int(t / .6 * len(lines))))
        for i, line in enumerate(lines[:shown]):
            label(d, (230, 300 + i * 78), line, 62)
        stamp = datetime.fromisoformat(quote['issued_at']).strftime('%d %b %Y / %H:%M UTC').upper()
        d.rectangle((230, 300 + len(lines) * 78 + 20, 230 + 400 * easing(min(1, t * 2)), 300 + len(lines) * 78 + 26), fill='#65e1d1')
        label(d, (230, 300 + len(lines) * 78 + 50), f"{quote['provider']} · ISSUED {stamp}", 28, '#a8c4d0')
    elif state == 'warning_card':
        w = p['warning_card'];u = easing(min(1, t * 2))
        d.rectangle((0, 82, 1920, 970), fill='#081d2c')
        d.rectangle((0, 82, int(1920 * u), 100), fill=w['color'])
        label(d, (110, 140), w['event'].upper(), 64, w['color'])
        label(d, (110, 225), 'ISSUED BY ' + w['office'].upper(), 28, '#a8c4d0')
        issued = datetime.fromisoformat(w['issued_at'])
        when = issued.strftime('%d %b %H:%M UTC')
        if w['expires_at']:
            when += '  →  UNTIL ' + datetime.fromisoformat(w['expires_at']).astimezone(issued.tzinfo).strftime('%H:%M UTC')
        label(d, (110, 275), when, 34)
        y = 350
        if w['areas']:
            label(d, (110, y), 'AREAS', 24, '#65e1d1');label(d, (300, y - 4), ' · '.join(w['areas'])[:90], 32);y += 70
        rows = [('HAZARD', w['hazard']), ('SOURCE', w['source']), ('IMPACT', w['impact'])]
        for i, (name, value) in enumerate(r for r in rows if r[1]):
            if t < .15 + i * .12:
                continue
            label(d, (110, y), name, 24, '#65e1d1')
            for j, line in enumerate(textwrap.wrap(value, 78)[:2]):
                label(d, (300, y - 4 + j * 40), line, 32)
            y += 100
        if w['rain'] and t > .5:
            d.rectangle((110, y, 1810, y + 74), fill='#0f2c3c')
            label(d, (135, y + 18), '“' + w['rain'] + '” — ' + w['office'], 32, '#ffffff')
    elif state == 'split_facts':
        rows = p.get('state_facts', [])[:4]
        d.rectangle((1200, 130, 1880, 930), fill='#061724')
        d.rectangle((1200, 130, 1208, 930), fill='#65e1d1')
        label(d, (1250, 170), 'SOURCE FACTS', 32, '#65e1d1')
        for i, (key, value) in enumerate(rows):
            if t < i * .12:
                continue
            title, unit = FACTS[key];y = 260 + i * 165
            label(d, (1250, y), title, 26, '#a8c4d0')
            label(d, (1250, y + 40), f'{value:g} {unit}'.strip(), 76)
    elif state == 'place_callout' and p.get('focus_label'):
        u = easing(min(1, t * 2.5))
        d.rectangle((55, 130, 55 + max(1, 900 * u), 215), fill='#061724')
        if u > .6:
            label(d, (85, 148), p['focus_label'].upper(), 44, '#82efdc')


def transitions(scenes):
    """Choose how each graphic shot enters. Footage keeps hard cuts; continuous holds stay invisible.

    Changing story: a branded push. Map into a card: push. Card or chart back to a map: wipe.
    Map to map: alternate dissolves with hard cuts so the pace does not soften everywhere."""
    for index, scene in enumerate(scenes):
        scene['parameters'].pop('transition_in', None)
        if not index:
            continue
        previous = scenes[index - 1]
        footage = lambda s: s.get('media_id') or s.get('cuts')
        if footage(scene) or footage(previous) or 'fade' in (scene.get('transition'), previous.get('transition')):
            continue
        if scene['parameters'].get('camera_span') and scene.get('parent_scene_id') and scene.get('parent_scene_id') == previous.get('parent_scene_id'):
            continue
        before, after = family_of(previous), family_of(scene)
        if previous['parameters'].get('source_advisory_id') != scene['parameters'].get('source_advisory_id'):
            kind = 'story'
        elif before == 'map' and after in ('card', 'split'):
            kind = 'push'
        elif before in ('card', 'split', 'chart') and after == 'map':
            kind = 'wipe'
        elif 'chart' in (before, after) or 'observation' in (before, after):
            kind = 'dissolve'
        elif before == after == 'map':
            kind = 'dissolve' if index % 2 else None
        else:
            kind = 'dissolve'
        if kind:
            scene['parameters']['transition_in'] = kind
