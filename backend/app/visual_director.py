"""Narration meaning -> visual intent, and a diagnostic record for every visual decision.

Deterministic: intent comes from the narration and its source story, never from a model, and
it only steers choices among visuals whose evidence already exists. It never adds a fact.
"""
import re

# Intent -> (patterns, preferred visual states in order, footage class wanted).
INTENTS = [
    ('intensification', r'\b(strengthen\w*|intensif\w*|upgraded|rapid\w* (?:grow|deepen)\w*|deepen\w*|rose to|increased to|now a category|became a (?:major )?hurricane)\b',
     ['change_gauge', 'comparison_split', 'satellite_loop', 'question_reveal', 'stat_card', 'track_follow'], 'phenomenon'),
    ('weakening', r'\b(weaken\w*|downgraded|fell to|dropp\w* to|decreas\w*|lost strength|dissipat\w*)\b',
     ['change_gauge', 'comparison_split', 'stat_card', 'pull_out'], 'phenomenon'),
    ('landfall', r'\b(landfall|came ashore|come ashore|made landfall|crossed the coast|moves? inland)\b',
     ['place_focus', 'satellite_loop', 'radar_loop', 'place_callout', 'track_follow', 'split_facts'], 'phenomenon'),
    ('movement', r'\b(mov\w*|heading|head\w* (?:toward|for)|track\w*|path|toward|northward|southward|eastward|westward|forward speed|drift\w*)\b',
     ['track_follow', 'advisory_timeline', 'push_in', 'pan'], 'phenomenon'),
    ('tornado', r'\b(tornado\w*|twister|supercell|severe thunderstorm\w*|hail\w*|damaging winds?)\b',
     ['severe_outlook', 'radar_loop', 'warning_card', 'county_focus', 'quote_card', 'place_focus'], 'phenomenon'),
    ('flooding', r'\b(flood\w*|storm surge|surge|inundat\w*|river\w* (?:rise|rising|crest\w*)|flash flood\w*)\b',
     ['radar_loop', 'county_focus', 'place_focus', 'warning_card', 'stat_card', 'place_callout'], 'impact'),
    ('rainfall', r'\b(rain\w*|downpour\w*|inches of rain|precipitation|showers)\b',
     ['radar_loop', 'stat_card', 'warning_card', 'county_focus', 'split_facts'], 'phenomenon'),
    ('winter', r'\b(snow\w*|blizzard\w*|ice storm|freezing rain|sleet|whiteout)\b',
     ['stat_card', 'place_callout', 'wide'], 'phenomenon'),
    ('temperature', r'\b(heat\w*|heat index|temperatures?|record high|record low|cold\w*|wind chill|freez\w*)\b',
     ['stat_card', 'split_facts', 'wide'], 'establishing'),
    ('warning', r'\b(warning\w*|watch(?:es)?|advisor(?:y|ies) (?:is|are) in effect|in effect|issued|expires?|evacuation orders?|bulletins?|alerts?|threats?|life-threatening|risk)\b',
     ['warning_card', 'county_focus', 'place_focus', 'quote_card', 'source_card'], 'response'),
    ('uncertainty', r'\b(uncertain\w*|could|may|might|possible|possibly|models?|cone|spread|range of)\b',
     ['pull_out', 'wide', 'quote_card', 'pan'], 'phenomenon'),
    ('impact', r'\b(damag\w*|destroy\w*|debris|outage\w*|power lines?|homes?|roads?|collaps\w*|wreck\w*)\b',
     ['place_callout', 'stat_card', 'push_in'], 'impact'),
    ('response', r'\b(rescu\w*|crews?|responders?|emergency|shelters?|evacuat\w*|recover\w*|volunteers?|national guard|relief)\b',
     ['place_callout', 'quote_card', 'wide'], 'response'),
]
GENERIC = {'warning', 'uncertainty'}
HAZARDS = [
    ('tropical_cyclone', r'\b(hurricane|tropical (?:storm|depression|cyclone)|typhoon|cyclone|eyewall)\b'),
    ('tornado', r'\b(tornado\w*|twister|supercell)\b'),
    ('severe_storm', r'\b(severe thunderstorm\w*|thunderstorm\w*|hail\w*|damaging winds?|lightning)\b'),
    ('high_wind', r'\b(high winds?|wind (?:advisory|warning)|crosswinds?|blowing dust|dust storms?|lake wind)\b'),  # Not "damaging winds": a severe storm.
    ('flood', r'\b(flood\w*|surge|inundat\w*)\b'),
    ('winter', r'\b(snow\w*|blizzard\w*|ice storm|freezing rain|sleet|winter storm|winter weather)\b'),  # Alert titles name the hazard.
    ('heat', r'\b(heat\w*|record high|hot)\b'),
    ('cold', r'\b(cold\w*|wind chill|freez\w*|frigid)\b'),
    ('wildfire', r'\b(wildfire\w*|fire weather|red flag)\b'),
]
# What each visual state needs to be honest.
EVIDENCE = {
    'change_gauge': 'two source wind or pressure measurements', 'comparison_split': 'two source wind or pressure measurements',
    'question_reveal': 'two source wind or pressure measurements', 'stat_card': 'numeric source facts',
    'split_facts': 'numeric source facts', 'quote_card': 'original source wording', 'track_follow': 'reported storm positions',
    'advisory_timeline': 'two or more reported positions', 'place_callout': 'a catalogued place named by the story',
    'push_in': 'reported geography', 'pull_out': 'reported geography', 'pan': 'reported geography', 'wide': 'reported geography',
    'source_card': 'the source record', 'severe_outlook': 'an SPC outlook valid at the story time',
    'place_focus': 'a state or region named in this beat', 'county_focus': 'official NWS county outlines for the alert',
    'warning_card': 'an NWS alert text', 'radar_loop': 'radar frames within an hour of the story over its area',
    'satellite_loop': 'GOES frames within 90 minutes of the story over its area',
}


# Capitalised names of landforms and waterways ("Snowy Range", "Thunder Basin", "Flood Creek"): never a hazard on their own.
PLACE_NAME = re.compile(r'\b(?:[A-Z][a-z]+ ){1,2}(?:Range|Mountains?|Foothills|Creek|River|Basin|Lake|Peaks?|Pass|Canyons?|Valley|Bay|Island|Plateau|Hills|Butte|Mesa)\b')


def classify(text, story_text=''):
    """Primary intent, secondary intents, hazard and wanted footage class for one beat of narration."""
    hits = []
    for name, pattern, preferred, footage in INTENTS:
        count = len(re.findall(pattern, text, re.I))
        if count:
            hits.append((count, name, preferred, footage))
    # The first listed intent wins ties; listing order runs from most to least specific.
    order = {name: i for i, (name, *_rest) in enumerate(INTENTS)}
    # Generic framing ("in effect", "could") never outranks a specific hazard or event in the same beat.
    hits.sort(key=lambda h: (h[1] in GENERIC, -h[0], order[h[1]]))
    spoken = PLACE_NAME.sub(' ', text)  # "North Snowy Range Foothills" is a place, not snow.
    hazard = next((name for name, pattern in HAZARDS if re.search(pattern, spoken, re.I)), None) \
        or next((name for name, pattern in HAZARDS if re.search(pattern, story_text or '', re.I)), 'general')
    if not hits:
        return {'intent': 'context', 'secondary': [], 'hazard': hazard, 'preferred': ['place_focus', 'satellite_loop', 'radar_loop', 'wide', 'pan'],
                'footage_class': 'establishing', 'confidence': .3}
    top = hits[0]
    return {'intent': top[1], 'secondary': [h[1] for h in hits[1:3]], 'hazard': hazard, 'preferred': top[2],
            'footage_class': top[3], 'confidence': round(min(.95, .55 + .15 * top[0] + .05 * len(hits)), 2)}


def story_text(advisory):
    return ' '.join(str(getattr(advisory, key, '') or '') for key in ('title', 'event_key', 'forecast_excerpt'))


def bonus(state, intent):
    preferred = intent['preferred']
    return max(0, 7 - 2 * preferred.index(state)) if state in preferred else 0


def evidence(scene):
    p = scene['parameters']
    found = []
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) for k, v in p.get('facts', {}).items() if k not in ('latitude', 'longitude')):
        found.append('source facts')
    if p.get('changes'):
        found.append('measured changes')
    if p.get('places'):
        found.append('named places')
    kinds = {f.get('properties', {}).get('kind') for f in p.get('geojson', {}).get('features', [])}
    if 'reported_center' in kinds:
        found.append('reported positions')
    if 'alert_area' in kinds:
        found.append('warning polygons')
    if 'forecast_cone' in kinds:
        found.append('forecast cone')
    if p.get('report_graphs'):
        found.append('chart data')
    if scene.get('direction', {}).get('asset_ids'):
        found.append('observations')
    return found


def annotate(scenes, advisory_lookup, media=None):
    """Attach a decision record to every scene: timing, meaning, evidence, choice, reason and warnings."""
    media = media or {}
    cursor = 0.0
    for index, scene in enumerate(scenes):
        p = scene['parameters'];advisory = advisory_lookup(p.get('source_advisory_id'))
        intent = p.get('visual_intent') or classify(scene['script_segment'], story_text(advisory))
        meta = p.pop('state_meta', None) or {}
        warnings = []
        if scene.get('media_id') or scene.get('cuts'):
            clips = [scene['media_id']] if scene.get('media_id') else [c['media_id'] for c in scene['cuts']]
            assets = [media.get(c, {}) for c in clips]
            contexts = sorted({a.get('context', 'unknown') for a in assets})
            chosen, family = 'footage', 'footage'
            reason = f"{intent['footage_class'].capitalize()} footage for a {intent['intent']} beat"
            if any(not a.get('catalog', {}).get('location_reviewed') for a in assets):
                warnings.append('Footage location is not reviewed; shown as contextual imagery.')
            if 'archival' in contexts:
                warnings.append('Archival footage; labelled with its original context, not as the current event.')
            fallback = 'Map or data graphic if the clip becomes unavailable'
        elif p.get('report_graphs'):
            chosen, family, reason, fallback = 'chart', 'chart', 'Source values for this claim are plotted as a chart', 'Key-numbers card'
        elif scene.get('map_mode', 'auto') != 'auto' or scene.get('graphic_style', 'auto') != 'auto':
            chosen, family, reason, fallback = scene.get('map_mode') if scene.get('map_mode', 'auto') != 'auto' else scene['graphic_style'], 'manual', 'Chosen by the editor', 'Labelled source card'
        elif scene.get('direction', {}).get('asset_ids'):
            chosen, family, reason, fallback = scene['direction']['scene_type'], 'observation', 'Timestamped observations for this story', 'Reported geography map'
        else:
            chosen = p.get('visual_state') or meta.get('chosen') or 'hold'
            family = 'map' if chosen in ('wide', 'pan', 'push_in', 'pull_out', 'track_follow', 'place_callout', 'severe_outlook', 'place_focus', 'county_focus', 'hold') else 'observation' if chosen in ('radar_loop', 'satellite_loop') else 'card'
            reason = meta.get('reason') or ('Continues the previous camera move; no new evidence-backed view was available' if chosen == 'hold' else 'Best available evidence-backed view')
            fallback = meta.get('fallback') or 'Regional overview map'
            preferred = [s for s in intent['preferred'] if s in EVIDENCE]
            if preferred and chosen not in preferred and intent['intent'] != 'context':
                missing = next((s for s in preferred if s not in meta.get('available', [])), None)
                if missing:
                    warnings.append(f"Preferred {missing.replace('_', ' ')} needs {EVIDENCE[missing]}; not available, so {chosen.replace('_', ' ')} was used.")
            if intent['footage_class'] in ('impact', 'response') and intent['intent'] in ('impact', 'response', 'flooding'):
                warnings.append(f"No {intent['footage_class']} footage was placed on this beat; a graphic stands in.")
        scene['parameters']['visual_decision'] = {
            'beat': index + 1, 'scene_id': scene['id'], 'parent_scene_id': scene.get('parent_scene_id'),
            'start': round(cursor, 3), 'end': round(cursor + scene['seconds'], 3), 'narration': scene['script_segment'],
            'story': p.get('source_advisory_id'), 'claim_id': scene.get('claim_id'),
            'intent': intent['intent'], 'secondary_intents': intent['secondary'], 'hazard': intent['hazard'],
            'footage_class': intent['footage_class'], 'preferred': intent['preferred'], 'evidence': evidence(scene),
            'chosen': chosen, 'family': family, 'alternatives': meta.get('alternatives', []), 'reason': reason,
            'fallback': fallback, 'transition_in': p.get('transition_in') or ('fade' if index and scenes[index-1].get('transition') == 'fade' else 'cut' if index else None),
            'confidence': intent['confidence'], 'warnings': warnings,
        }
        cursor += scene['seconds']
    return [s['parameters']['visual_decision'] for s in scenes]
