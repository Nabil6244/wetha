"""What a narration beat needs to show, and how well a clip shows it.

Visual relevance answers "does this footage depict the hazard, action, environment or consequence the
narration describes?". It is independent of provenance ("is this verified footage of that event?"),
which is recorded separately and only matters when footage is presented as authentic event footage.

Generic weather words ("storm", "weather", "clouds") never make a clip relevant on their own: a clip
must match the beat's concrete visual cues, or it stays a weak match.
"""
import re

# Beat concepts: how to recognise the beat in narration, what footage shows it (strong cues), what helps
# (support cues), what contradicts it, and whether footage or data graphics communicate it best.
CONCEPTS = {
    'storm_surge': {
        'beat': r'storm surge|surge|inundat\w*|coastal flood\w*|water rise|rising water|overtop\w*|seawall|water threat|the water',
        'strong': r'storm surge|surge|overtop\w*|seawall|sea ?wall|inundat\w*|water (?:entering|in|flooding) (?:the )?streets?|coastal flood\w*|waves? (?:crash\w* )?(?:over|through|onto) (?:the |a |an )?(?:wall|pier|road|seawall|street|promenade|boardwalk)|(?:pier|wall|seawall|promenade) with waves crashing over|waves crashing over it|flooded (?:coast|beach) ?road',
        'support': r'waves?|pier|coast\w*|shore\w*|sea|ocean|breakwater|jetty|spray|beach|hurricane|huge|massive',
        'contradict': r'calm|serene|tranquil|peaceful|sunny|sunset|sunrise|clear sky|blue sky|surf(?:ing|er)|swim\w*|vacation|resort|paradise',
        'shots': 'waves overtopping seawalls, coastal inundation, water entering streets', 'medium': 'footage'},
    'hurricane_wind': {
        'beat': r'winds?|gusts?|sustained|mph|miles per hour|category \d|knots|hurricane-force|bent|bend\w*|palms?|sideways|tore|blew',
        'strong': r'hurricane|palm(?: trees?)? (?:bend\w*|blow\w*|sway\w*|whip\w*)|(?:bending|swaying|blowing|whipping) palms?(?: trees?)?|(?:strong|high|intense|violent|storm) winds?|wind[- ]driven rain|gusts?|flying debris|trees? (?:bend\w*|thrash\w*|swaying violently)',
        'support': r'palms?|trees? sway\w*|windy|wind|storm|rain|debris',
        'contradict': r'calm|serene|gentle|breeze|sunny|sunset|clear sky|blue sky|grass|field|meadow|wheat|vacation',
        'shots': 'bending palms, wind-driven rain, flying debris, damaged trees', 'medium': 'footage'},
    'rainfall': {
        'beat': r'rain\w*|downpour\w*|inches of rain|precipitation|showers?|deluge',
        'strong': r'heavy rain|torrential|downpour|pouring rain|rain (?:on|falling|hitting|pounding)|wind[- ]driven rain|rainstorm|monsoon',
        'support': r'rain\w*|wet|puddles?|umbrella|storm|drops?',
        'contradict': r'sunny|clear sky|blue sky|drought|dry|desert|snow',
        'shots': 'heavy rain on streets and windows, wind-driven rain', 'medium': 'footage'},
    'flash_flood': {
        'beat': r'flash flood\w*|flood\w*|high water|submerged|swollen (?:creek|river)s?|underpass\w*|low-lying',
        'strong': r'flood(?:ed|ing|water)?|submerged|underwater (?:road|street|car)|fast[- ]moving water|rushing water|high water|swollen (?:river|creek)|water (?:on|over) (?:the )?road',
        'support': r'water|river|creek|street|road|cars?|vehicles?|rain',
        'contradict': r'calm lake|serene|pool|swim\w*|sunny|clear sky|kayak\w*|fishing',
        'shots': 'flooded roads, fast-moving water, submerged vehicles', 'medium': 'footage'},
    'evacuation': {
        'beat': r'evacuat\w*|leave|leaving|shelters?|flee\w*|get out',
        'strong': r'evacuat\w*|traffic jam|contraflow|shelter|sandbags?|boarding up|plywood|emergency (?:traffic|vehicles?)|leaving (?:town|home)',
        'support': r'traffic|highway|cars?|people|family|families|road|signs?',
        'contradict': r'vacation|holiday|road trip|scenic',
        'shots': 'people leaving, emergency traffic, evacuation signage, boarding up', 'medium': 'footage'},
    'damage': {
        'beat': r'damag\w*|destroy\w*|debris|outage\w*|power lines?|collaps\w*|aftermath',
        'strong': r'(?:storm|hurricane|wind|flood) damage|destroyed|debris|downed (?:trees?|power ?lines?)|collapsed|roof (?:torn|damage)|wreckage|aftermath',
        'support': r'damage\w*|trees? down|power lines?|utility|crews?|clean ?up|houses?|homes?',
        'contradict': r'construction site|demolition|renovation|sunny',
        'shots': 'storm damage, downed trees and lines, debris, aftermath', 'medium': 'footage'},
    'rescue': {
        'beat': r'rescu\w*|responders?|crews?|national guard|first responders?|emergency',
        'strong': r'rescue|responders?|national guard|coast guard|emergency crews?|fire ?fighters?|boat rescue|helicopter rescue',
        'support': r'emergency|crews?|boat|helicopter|ambulance|police',
        'contradict': r'training exercise|drill|movie|film scene',
        'shots': 'rescue boats, emergency crews, responders', 'medium': 'footage'},
    'forecast_warning': {
        'beat': r'advisor(?:y|ies)|forecast\w*|warning\w*|watch(?:es)?|national hurricane center|nhc|national weather service|latitude|longitude|millibars?|pressure|track|cone|issued|in effect',
        'strong': r'(?:weather |doppler )?radar (?:loop|map|image\w*|screen)|weather radar|satellite (?:view|image\w*|loop) of (?:a |the )?(?:hurricane|storm|cyclone|typhoon|clouds)|hurricane (?:from|seen from) space|weather map|forecast map|hurricane track|storm track|warning map|meteorologist|weather forecaster',
        'support': r'storm clouds|hurricane from space|clouds? (?:time ?lapse|timelapse)|storm system',
        'contradict': r'sunny|clear sky|blue sky|vacation|orbit\w*|spacecraft|space station|astronaut|planet|mountain\w*|tower',
        'shots': 'radar, satellite, warning graphics and maps (best made from data, not stock)', 'medium': 'graphics'},
    'general_context': {
        'beat': r'.',
        'strong': r'hurricane|tropical storm|storm surge|storm waves|stormy|rough seas?|angry sea|heavy surf|(?:big|huge|massive|crashing|dramatic|powerful) (?:sea |ocean )?waves|waves crashing|surge of sea waves|(?:swaying|bending|blowing) palms?(?: trees?)?|palm(?: trees?)? (?:sway|bend|blow)\w*|waves crashing over|storm clouds over (?:the )?(?:sea|ocean|coast)|coastal storm|storm debris|storm damage',
        'support': r'storm\w*|clouds?|waves?|coast\w*|sea|ocean|palms?|wind',
        'contradict': r'sunny|clear sky|blue sky|calm|serene|sunset|vacation|mountain\w*|desert|snow|meadow|field',
        'shots': 'stormy coast, dark clouds over the sea, establishing shots', 'medium': 'footage'},
}
# Provider searches per beat concept: several visually different shots, never a bare weather word.
SEARCHES = {
    'storm_surge': ['storm surge waves over seawall', 'coastal road flooding storm', 'sea water flooding street hurricane', 'waves crashing over pier storm',
                    'hurricane storm surge flooding', 'storm waves overtopping wall'],
    'hurricane_wind': ['palm trees bending hurricane wind', 'wind driven rain storm street', 'hurricane wind trees', 'flying debris strong wind',
                       'tropical storm wind palms', 'storm wind rain sideways'],
    'rainfall': ['heavy rain street', 'torrential rain city', 'rain pouring on road', 'heavy rain car windshield', 'rainstorm flooding street'],
    'flash_flood': ['flooded road cars', 'flash flood water rushing', 'submerged car flood', 'flooded street water', 'flood water over road', 'flooded underpass'],
    'damage': ['storm damage houses', 'downed trees after storm', 'damaged roof hurricane', 'utility crews power lines storm', 'debris after hurricane'],
    'evacuation': ['hurricane evacuation traffic', 'boarding up windows hurricane', 'sandbags flood', 'traffic leaving city highway storm', 'shelter storm preparation'],
    'rescue': ['flood rescue boat', 'emergency crews flood', 'rescue workers storm', 'national guard flood'],
    'forecast_warning': ['hurricane satellite view', 'weather radar storm', 'stormy coast dark clouds'],
    'general_context': ['stormy sea coast', 'rough sea waves storm', 'dark storm clouds over ocean', 'hurricane waves beach', 'stormy beach palm trees'],
}


def search_variants(concept, occurrence=0, place=''):
    """Three different searches for a beat, rotated by how many earlier beats shared its concept, plus a located one.
    Forecast beats get fewer stock searches: radar, satellite and warning maps from source data stay primary."""
    options = SEARCHES[concept];count = 2 if CONCEPTS[concept]['medium'] == 'graphics' else 3
    picks = [options[(occurrence * count + n) % len(options)] for n in range(count)]
    if place and concept not in ('forecast_warning', 'general_context'):
        picks.append(f"{place} {options[0].split()[0]} {options[0].split()[1] if len(options[0].split()) > 1 else ''}".strip())
    return list(dict.fromkeys(picks))


def fallback_searches(concept, used, ambiguous_urban=False, limit=2):
    """Up to `limit` more searches for a beat whose candidates were not clean: the concept's other searches,
    never one already run (case-insensitive). When the problem was a street scene of unknown location, searches
    that do not ask for crowds, traffic or city streets come first. Forecast beats get none: radar, satellite
    and warning maps from source data illustrate them."""
    if CONCEPTS[concept]['medium'] == 'graphics':
        return []
    done = {q.casefold() for q in used}
    options = [q for q in SEARCHES[concept] if q.casefold() not in done]
    if ambiguous_urban:
        options.sort(key=lambda q: bool(re.search(r'\b(street|city|urban|traffic|people|downtown)\b', q, re.I)))
    return options[:limit]


ORDER = ['storm_surge', 'flash_flood', 'evacuation', 'rescue', 'damage', 'rainfall', 'hurricane_wind', 'forecast_warning', 'general_context']
GENERIC = re.compile(r'\b(storm\w*|weather|clouds?|cloudy|sky|skies|nature|dramatic|cinematic|beautiful|4k|hd|footage|video|stock)\b', re.I)
NEVER = re.compile(r'\b(cartoon|animat\w*|anime|music video|lyrics?|mtv|episode|trailer|video ?game|gameplay|minecraft|toy|lego|cgi render|3d render)\b', re.I)
NAMED_EVENT = re.compile(r'\b(hurricane|tropical storm|typhoon|cyclone|superstorm)\s+([a-z]{3,})\b', re.I)
NOT_NAMES = {'force', 'winds', 'wind', 'damage', 'season', 'warning', 'watch', 'center', 'centre', 'clouds', 'cloud', 'eye', 'from', 'over',
             'season', 'surge', 'rain', 'hunters', 'shutters', 'party', 'preparation', 'preparations', 'aftermath', 'footage', 'waves', 'coming',
             'approaching', 'hits', 'hitting', 'and', 'with', 'in', 'at', 'on', 'near', 'landfall', 'track', 'path', 'storm', 'strength', 'category'}


def beat_need(text):
    """The concept a beat most needs to show. Narration about advisories and coordinates is a forecast beat.
    In "the wind was low, but the water threat…", the clause after the contrast carries the meaning."""
    parts = re.split(r'\b(?:but|however|yet|instead)\b', text, maxsplit=1, flags=re.I)
    def count(name):
        if len(parts) == 2:
            return len(re.findall(CONCEPTS[name]['beat'], parts[0], re.I)) + 3 * len(re.findall(CONCEPTS[name]['beat'], parts[1], re.I))
        return len(re.findall(CONCEPTS[name]['beat'], text, re.I))
    hits = [(name, count(name)) for name in ORDER[:-1]]
    hits = [h for h in hits if h[1]]
    if not hits:
        return 'general_context'
    return max(hits, key=lambda h: (h[1], -ORDER.index(h[0])))[0]


def footage_need(text):
    """For forecast or warning beats (best shown with maps and radar), the concept footage should illustrate:
    whatever hazard the beat's content describes, or the general storm context."""
    hits = [(name, len(re.findall(CONCEPTS[name]['beat'], text, re.I))) for name in ORDER[:-2]]
    hits = [h for h in hits if h[1]]
    return max(hits, key=lambda h: (h[1], -ORDER.index(h[0])))[0] if hits else 'general_context'


ACTIVE_STORM = ('storm_surge', 'hurricane_wind', 'rainfall')
# Geographic compatibility (US stories). Evidence only from metadata the provider or uploader wrote, never from
# skin colour, ethnicity, architecture style or impressions of a preview.
NON_US_VEHICLES = re.compile(r'\b(rickshaws?|tuk[- ]?tuks?|auto[- ]rickshaws?|jeepneys?|matatus?|cyclos?)\b', re.I)
US_PLACES = re.compile(r'\b(houston|miami|tampa|orlando|jacksonville|tallahassee|pensacola|key west|new orleans|baton rouge|mobile|biloxi|galveston|'
                       r'corpus christi|charleston|savannah|wilmington|outer banks|norfolk|atlanta|nashville|memphis|dallas|austin|san antonio|'
                       r'new york|new jersey|boston|philadelphia|chicago|los angeles|san diego|san francisco|seattle|denver|phoenix|las vegas|usa|u\.s\.|united states|america)\b', re.I)
DENSE_STREET = re.compile(r'\b(urban|city|downtown|market|vendors?|alley\w*|pedestrians?|people|crowd\w*|traffic|motorbikes?|scooters?|bicycles?|cycl\w*|shops?|swim\w*|commut\w*)\b', re.I)
PEOPLE_AND_STREETS = ('flash_flood', 'rainfall', 'evacuation', 'rescue', 'damage')


def geography(candidate, story_region, concept):
    """Is the clip's setting compatible with the story's location? Independent of visual relevance.

    conflict: metadata names a non-US place or a vehicle not found on US streets -> never auto; review with the conflict shown.
    possible_conflict: people-and-street beat, unknown location, dense-urban metadata -> review, not rejected.
    compatible: metadata names a US place. no_conflict_evident: everything else (waves, clouds, rain, palms...)."""
    if story_region != 'US':
        return {'compatibility': 'not_assessed', 'evidence': [], 'reason': 'Story region unknown; no geographic gate'}
    text = ' '.join([candidate.get('title', ''), candidate.get('description', '')[:600], ' '.join(candidate.get('tags', []))])
    foreign = ABROAD.search(text) or NON_US_VEHICLES.search(text)
    if foreign:
        return {'compatibility': 'conflict', 'evidence': [f'metadata: {foreign.group(0)}'],
                'reason': f'Clip metadata places it outside the US ({foreign.group(0)}); do not use it as if it were the story location'}
    if US_PLACES.search(text) or regional_names(text):
        return {'compatibility': 'compatible', 'evidence': [f'metadata: {(US_PLACES.search(text) or None) and US_PLACES.search(text).group(0) or regional_names(text)[0]}'],
                'reason': 'Clip metadata names a US place'}
    dense = DENSE_STREET.search(text)
    if concept in PEOPLE_AND_STREETS and dense:
        return {'compatibility': 'possible_conflict', 'evidence': [f'metadata: {dense.group(0)} scene, location unknown'],
                'reason': 'Street scene with people and an unknown location: check the setting fits a US story before use'}
    return {'compatibility': 'no_conflict_evident', 'evidence': [], 'reason': 'No evidence the setting conflicts with the story'}


def regional_names(text):
    from .regional import named_regions
    return named_regions(text)


ABROAD = re.compile(r'\b(mexico city|india|bangladesh|dhaka|mumbai|kolkata|delhi|pakistan|karachi|nepal|vietnam|thailand|bangkok|philippines|manila|'
                    r'indonesia|jakarta|china|japan|korea|rickshaws?|tuk[- ]?tuks?|europe|italy|spain|venice|london|paris|germany|russia|brazil|africa|african|'
                    # Added after a live review auto-rated "river thames flooding in uk". "Mexico" alone is not listed: New Mexico, Gulf of Mexico.
                    r'uk|united kingdom|(?<!new )england|britain|british|scotland|wales|ireland|thames|france|netherlands|amsterdam|portugal|greece|turkey|istanbul|'
                    r'canada|toronto|vancouver|australia|sydney|new zealand|sri lanka|myanmar|malaysia|singapore|taiwan|hong kong|cuba|haiti|'
                    r'jamaica|bahamas|cancun|tijuana|acapulco)\b', re.I)


def provenance(candidate, story_title=''):
    """'illustrative' unless the clip itself claims a named event; a claim is never treated as verified."""
    text = candidate.get('title', '') + ' ' + candidate.get('description', '')
    event = None
    for claim in NAMED_EVENT.finditer(text):
        if claim.group(2).lower() not in NOT_NAMES:
            event = f'{claim.group(1).title()} {claim.group(2).title()}';break
    return {'status': 'claimed_event' if event else 'illustrative', 'claimed_event': event, 'verified': False,
            'matches_story': bool(event and event.split()[-1].lower() in (story_title or '').lower()),
            'rule': 'Usable as illustrative footage. Presenting it as authentic footage of a named event requires verification.'}


def relevance(candidate, concept, preview=None, text_for_beat=''):
    """Visual relevance 0-100 with confidence and reasons, from metadata plus preview screening when available.

    Forecast and warning beats are scored for data graphics (radar, satellite) and, separately, for footage that
    illustrates what the beat is about; the footage score is capped below the automatic-import threshold."""
    if CONCEPTS[concept]['medium'] == 'graphics':
        direct = _relevance(candidate, concept, preview)
        # Footage for a forecast beat illustrates its hazard, or at least the storm it is about.
        options = [footage_need(text_for_beat), 'general_context']
        illustrated = max((_relevance(candidate, c, preview) for c in dict.fromkeys(options)), key=lambda r: r['score'])
        backup = illustrated['concept']
        if illustrated['score'] > direct['score']:
            illustrated['score'] = min(illustrated['score'], 55)
            illustrated['reasons'].append(f"Forecast beat: footage illustrates its {backup.replace('_', ' ')}; maps and radar stay primary")
            illustrated['confidence'] = 'medium' if illustrated['confidence'] == 'high' else illustrated['confidence']
            illustrated['concept'] = f'{concept}→{backup}'
            return illustrated
        return direct
    primary = _relevance(candidate, concept, preview)
    if concept != 'general_context':
        # General storm context (rough seas, swaying palms) can illustrate any beat of a storm story, demoted:
        # below the recommendation threshold, so it is offered as a weak match, never auto-selected.
        context = _relevance(candidate, 'general_context', preview)
        if context['score'] > primary['score'] and not context['preview_flags']:
            context['score'] = min(context['score'], 40)
            context['reasons'].append(f"General storm context rather than the beat's {concept.replace('_', ' ')}")
            context['concept'] = f'{concept}→general_context'
            return context if context['score'] > primary['score'] else primary
    return primary


def _relevance(candidate, concept, preview=None):
    spec = CONCEPTS[concept]
    text = ' '.join([candidate.get('title', ''), candidate.get('description', '')[:600], ' '.join(candidate.get('tags', []))])
    reasons, flags = [], []
    if NEVER.search(text):
        return {'score': 0, 'confidence': 'high', 'concept': concept, 'matched': [], 'contradictions': [NEVER.search(text).group(0)],
                'preview_flags': [], 'reasons': ['Not real-world footage: ' + NEVER.search(text).group(0)]}
    strong = sorted({m.group(0).lower() for m in re.finditer(r'\b(?:' + spec['strong'] + r')\b', text, re.I)})
    support = sorted({m.group(0).lower() for m in re.finditer(r'\b(?:' + spec['support'] + r')\b', text, re.I)} - set(strong))
    contradict = sorted({m.group(0).lower() for m in re.finditer(r'\b(?:' + spec['contradict'] + r')\b', text, re.I)})
    score = 0
    if strong:
        score += 45 + 10 * min(2, len(strong) - 1);reasons.append('Shows ' + ', '.join(strong[:3]))
    score += 8 * min(3, len(support))
    if support:
        reasons.append('Related: ' + ', '.join(support[:3]))
    # Only generic words ("storm", "dramatic clouds") cannot make a clip relevant.
    if not strong and not [s for s in support if not GENERIC.fullmatch(s)]:
        score = min(score, 15);reasons.append('Only generic weather words in its description')
    if contradict:
        score -= 25 * len(contradict[:2]);reasons.append('Contradicts the beat: ' + ', '.join(contradict[:2]))
    if spec['medium'] == 'graphics':
        score = min(score, 55);reasons.append('Radar, satellite and warning maps from source data communicate this beat best')
    confidence = 'medium' if strong else 'low'
    if preview:
        flags = preview_flags(preview, concept)
        if flags:
            score -= 20 * len(flags);reasons.append('Preview shows ' + ', '.join(flags));confidence = 'high'
        elif strong:
            confidence = 'high'
    else:
        reasons.append('No preview image; judged from metadata only')
    return {'score': max(0, min(100, score)), 'confidence': confidence, 'concept': concept, 'matched': strong + support,
            'contradictions': contradict, 'preview_flags': flags, 'reasons': reasons}


# Preview screening: cheap, explainable image measurements for obvious mismatches. Not a classifier.
def measure(image):
    from PIL import ImageFilter, ImageStat
    small = image.convert('RGB').resize((96, 54))
    pixels = list(small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata());w, h = small.size
    top = pixels[:w * (h // 3)];bottom = pixels[w * (h // 2):]
    def blue_sky(p):
        r, g, b = p
        return b > 140 and b > r + 25 and b > g + 5 and max(p) - min(p) > 45
    hsv = small.convert('HSV');saturation = ImageStat.Stat(hsv).mean[1];brightness = ImageStat.Stat(hsv).mean[2]
    edges = small.convert('L').filter(ImageFilter.FIND_EDGES)
    lower_edges = ImageStat.Stat(edges.crop((0, h // 2, w, h))).mean[0]
    quantised = small.quantize(colors=48)
    counts = sorted(quantised.getcolors(), reverse=True)
    flat = sum(c for c, _ in counts[:6]) / (w * h)
    gray = small.convert('L').resize((9, 8))
    bits = [gray.getpixel((x, y)) > gray.getpixel((x + 1, y)) for y in range(8) for x in range(8)]
    return {'blue_sky': round(sum(map(blue_sky, top)) / max(1, len(top)), 3), 'saturation': round(saturation, 1),
            'brightness': round(brightness, 1), 'lower_edges': round(lower_edges, 1), 'flat': round(flat, 3),
            'hash': sum(1 << i for i, bit in enumerate(bits) if bit)}


def preview_flags(features, concept):
    flags = []
    severe = concept in ('storm_surge', 'hurricane_wind', 'rainfall', 'flash_flood', 'damage', 'general_context')
    if severe and features['blue_sky'] > .35 and features['brightness'] > 100:
        flags.append('clear blue sky')
    # Active-storm footage is grey and muted; bright saturated colour means fair weather. (Damage after a storm can be sunny.)
    if concept in ACTIVE_STORM and features['saturation'] > 70 and features['brightness'] > 100:
        flags.append('bright fair-weather colour')
    if concept == 'storm_surge' and features['lower_edges'] < 9 and features['saturation'] < 90:
        flags.append('calm, smooth water')
    # Brightness alone cannot tell sunshine from white buildings or bright overcast: only a bright scene with
    # visible blue sky counts as sunlit. A bright scene without that evidence is uncertain (see bright_uncertain).
    if concept in ACTIVE_STORM and features['brightness'] > 160 and features['blue_sky'] > .15:
        flags.append('bright, sunlit sky')
    if features['flat'] > .72 and features['saturation'] > 110:
        flags.append('flat cartoon-like colours')
    return flags


def bright_uncertain(features, concept):
    """Very bright active-storm scene without blue-sky evidence: weather cannot be judged, so review by eye."""
    return bool(features) and concept in ACTIVE_STORM and features['brightness'] > 160 and features['blue_sky'] <= .15


def too_dark(features):
    """A near-black preview cannot confirm what a clip shows."""
    return bool(features) and features['brightness'] < 40


def similar(a, b, threshold=6):
    """Perceptual-hash near-duplicate check between two previews."""
    return bin(a['hash'] ^ b['hash']).count('1') <= threshold
