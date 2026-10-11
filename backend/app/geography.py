"""Places named in narration -> real boundaries, at the beat where they are spoken.

States come from the bundled Census-derived state outlines. Named regions (Gulf Coast, Panhandle,
Big Bend...) are defined as groups of states plus a labelled extent; they are drawn as the member
states' real outlines with a region label, never as an invented polygon. Counties come from the
story's own NWS alert county codes and the official NWS zone geometry for those codes; when a zone
outline cannot be fetched, the bundled Census 2024 county outline for the same code is used. Counties
named in the narration itself light up at the word where they are spoken.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from . import regional

# Named regions: label, member states, extent [W, S, E, N]. The extent frames the view only.
REGIONS = {
    'gulf coast': ('Gulf Coast', ['TX', 'LA', 'MS', 'AL', 'FL'], [-97.8, 25.0, -81.0, 31.5]),
    "florida's gulf coast": ('Florida Gulf Coast', ['FL'], [-87.7, 25.0, -81.0, 30.9]),
    'florida gulf coast': ('Florida Gulf Coast', ['FL'], [-87.7, 25.0, -81.0, 30.9]),
    'florida panhandle': ('Florida Panhandle', ['FL'], [-87.7, 29.5, -83.5, 31.1]),
    'panhandle': ('Florida Panhandle', ['FL'], [-87.7, 29.5, -83.5, 31.1]),
    'big bend': ('Big Bend', ['FL'], [-85.0, 29.0, -82.5, 30.8]),
    'southwest florida': ('Southwest Florida', ['FL'], [-82.9, 25.7, -81.0, 27.6]),
    'florida keys': ('Florida Keys', ['FL'], [-82.2, 24.4, -80.2, 25.4]),
    'tampa bay': ('Tampa Bay', ['FL'], [-83.0, 27.4, -82.2, 28.2]),
    'atlantic coast': ('Atlantic Coast', ['FL', 'GA', 'SC', 'NC', 'VA'], [-82.5, 25.0, -75.0, 37.5]),
    'east coast': ('East Coast', ['FL', 'GA', 'SC', 'NC', 'VA', 'MD', 'DE', 'NJ', 'NY'], [-82.5, 25.0, -71.5, 41.5]),
    'southeast': ('Southeast', ['FL', 'GA', 'AL', 'SC', 'NC', 'TN', 'MS'], [-91.7, 24.5, -75.4, 36.7]),
    'carolinas': ('Carolinas', ['NC', 'SC'], [-84.4, 32.0, -75.4, 36.6]),
    'mid-atlantic': ('Mid-Atlantic', ['VA', 'MD', 'DE', 'NJ', 'PA', 'WV'], [-83.7, 36.5, -73.9, 42.3]),
    'northeast': ('Northeast', ['NY', 'NJ', 'PA', 'CT', 'RI', 'MA', 'VT', 'NH', 'ME'], [-80.6, 38.9, -66.9, 47.5]),
    'new england': ('New England', ['CT', 'RI', 'MA', 'VT', 'NH', 'ME'], [-73.8, 40.9, -66.9, 47.5]),
    'ohio valley': ('Ohio Valley', ['OH', 'KY', 'IN', 'WV'], [-89.2, 36.4, -80.5, 42.0]),
    'tennessee valley': ('Tennessee Valley', ['TN', 'AL'], [-90.4, 33.5, -81.6, 36.7]),
    'midwest': ('Midwest', ['OH', 'IN', 'IL', 'MI', 'WI', 'MN', 'IA', 'MO'], [-97.3, 36.0, -80.5, 49.4]),
    'great plains': ('Great Plains', ['ND', 'SD', 'NE', 'KS', 'OK', 'TX'], [-104.1, 25.8, -94.4, 49.0]),
    'deep south': ('Deep South', ['LA', 'MS', 'AL', 'GA'], [-94.1, 28.9, -80.8, 35.0]),
    'texas coast': ('Texas Coast', ['TX'], [-97.8, 25.8, -93.5, 30.2]),
    'louisiana coast': ('Louisiana Coast', ['LA'], [-94.0, 28.8, -88.8, 30.5]),
}


def _state_index():
    return {r['code']: r for r in regional.catalogue()['regions']}


def mentions(text):
    """Places named in the text, in spoken order, with the word index where each is said.

    Regions are matched before the states inside them, so "Florida's Gulf Coast" is one region, not
    Florida plus the Gulf Coast."""
    found, taken = [], []
    lowered = text.lower().replace('’', "'")  # Same length, so match positions still index the original text.
    index = _state_index();states = '|'.join(re.escape(r['name'].lower()) for r in index.values())
    # "northeast Florida", "southern Alabama": a direction before a state describes part of that state,
    # never a separate multi-state region. The whole state is outlined; the view frames that part of it.
    for match in re.finditer(r'(?<!\w)(north|south|east|west|northeast|northwest|southeast|southwest|central|northern|southern|eastern|western)(?:ern)?\s+(' + states + r")(?:'s)?(?!\w)", lowered):
        code = next(c for c, r in index.items() if r['name'].lower() == match.group(2))
        b = index[code]['bounds'];direction = match.group(1)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        west, east = (cx, b[2]) if 'east' in direction else (b[0], cx) if 'west' in direction else (b[0], b[2])
        south, north = (cy, b[3]) if 'north' in direction else (b[1], cy) if 'south' in direction else (b[1], b[3])
        if direction == 'central':
            west, east, south, north = b[0] + (b[2] - b[0]) / 4, b[2] - (b[2] - b[0]) / 4, b[1] + (b[3] - b[1]) / 4, b[3] - (b[3] - b[1]) / 4
        found.append({'kind': 'state', 'name': text[match.start():match.end()].replace("'s", '').replace('’s', '').strip().title(),
                      'states': [code], 'extent': [west, south, east, north], 'start': match.start()})
        taken.append((match.start(), match.end()))
    for key in sorted(REGIONS, key=len, reverse=True):
        for match in re.finditer(r'(?<!\w)' + re.escape(key) + r'(?!\w)', lowered):
            if any(a < match.end() and match.start() < b for a, b in taken):
                continue
            label, states, extent = REGIONS[key]
            found.append({'kind': 'region', 'name': label, 'states': states, 'extent': extent, 'start': match.start()})
            taken.append((match.start(), match.end()))
    for code, region in _state_index().items():
        pattern = r'(?<!\w)' + re.escape(region['name'].lower()) + r"(?:'s)?(?!\w)" + (r'(?!\s+river\b)' if code == 'MS' else '')
        for match in re.finditer(pattern, lowered):
            if any(a < match.end() and match.start() < b for a, b in taken):
                continue
            found.append({'kind': 'state', 'name': region['name'], 'states': [code], 'extent': region['bounds'], 'start': match.start()})
            taken.append((match.start(), match.end()))
    found.sort(key=lambda m: m['start'])
    for m in found:
        m['word'] = len(text[:m['start']].split())
    return found


def zone_urls(advisory):
    """Official NWS zone links named by an alert (county, forecast or marine zones)."""
    props = (getattr(advisory, 'source_payload', None) or {}).get('properties', {})
    zones = props.get('affectedZones') or []
    if isinstance(zones, str):
        zones = re.findall(r'https://api\.weather\.gov/zones/[a-z]+/[A-Z]{2}[CZ]\d{3}', zones)
    return [z for z in zones if re.fullmatch(r'https://api\.weather\.gov/zones/(county|forecast|marine|coastal|offshore)/[A-Z]{2}[CZ]\d{3}', z)][:24]


def counties(advisory):
    """County codes and names from an NWS alert: (UGC code like GAC245, 'Richmond, GA')."""
    payload = getattr(advisory, 'source_payload', None) or {}
    props = payload.get('properties', {})
    geocode = props.get('geocode') or {}
    if isinstance(geocode, str):
        try:
            geocode = json.loads(geocode.replace("'", '"'))
        except ValueError:
            geocode = {}
    codes = [c for c in geocode.get('UGC', []) if re.fullmatch(r'[A-Z]{2}C\d{3}', c)]
    names = [n.strip() for n in (getattr(advisory, 'area', '') or '').split(';') if n.strip()]
    return list(zip(codes, names)) if len(codes) == len(names) else [(c, c) for c in codes]


def extent(states, padding=.8):
    index = _state_index()
    boxes = [index[s]['bounds'] for s in states if s in index]
    if not boxes:
        return None
    return [max(-179.9, min(b[0] for b in boxes) - padding), max(-84, min(b[1] for b in boxes) - padding),
            min(179.9, max(b[2] for b in boxes) + padding), min(84, max(b[3] for b in boxes) + padding)]


def rings(states):
    index = _state_index()
    return [(code, index[code]['name'], index[code]['rings']) for code in states if code in index]


def draw_places(image, places, bounds, t, warning=None):
    """Highlight the named states or region, label them, and show a small US locator."""
    from PIL import Image, ImageDraw
    from .broadcast import map_point, label, easing
    u = easing(min(1, t * 2.2))
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0));d = ImageDraw.Draw(layer)
    highlighted = []
    for place in places:
        for code, name, polygons in rings(place['states']):
            highlighted.append((code, name))
            for ring in polygons:
                points = [map_point(c, bounds) for c in ring]
                if len(points) >= 3:
                    d.polygon(points, fill=(101, 225, 209, int(70 * u)), outline=(130, 239, 220, 255))
                    d.line(points + [points[0]], fill=(130, 239, 220, 255), width=4)
    if warning:
        for feature in warning:
            geometry = feature['geometry']
            for polygon in (geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]):
                points = [map_point(c, bounds) for c in polygon[0]]
                if len(points) >= 3:
                    d.polygon(points, fill=(255, 200, 135, 90), outline=(255, 200, 135, 255))
    image.paste(Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB'))
    draw = ImageDraw.Draw(image)
    # Labels at each highlighted state's visual centre (bounding-box centre clipped to the view).
    index = _state_index();seen = set()
    for code, name in highlighted:
        if code in seen:
            continue
        seen.add(code);b = index[code]['bounds']
        x, y = map_point(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), bounds)
        left, _ = map_point((b[0], b[1]), bounds);right, _ = map_point((b[2], b[1]), bounds)
        # Only label states large enough on screen to hold their name; small ones stay outlined.
        if 60 < x < 1700 and 110 < y < 940 and u > .4 and right - left > 22 * len(name):
            label(draw, (x - 12 * len(name), y - 20), name.upper(), 40, '#ffffff')
    title = ' · '.join(dict.fromkeys(p['name'] for p in places))
    draw.rectangle((55, 120, 55 + max(1, int(min(1500, 26 * len(title) + 60) * u)), 190), fill='#061724')
    if u > .5:
        label(draw, (80, 133), title.upper(), 40, '#82efdc')
    # Locator: the whole lower 48 with the highlighted states.
    inset = Image.new('RGB', (360, 210), '#071c29');id_ = ImageDraw.Draw(inset)
    conus = [-125, 24, -66, 50]
    for code, region in index.items():
        if code in ('AK', 'HI', 'PR'):
            continue
        for ring in region['rings']:
            pts = [map_point(c, conus, size=(360, 210)) for c in ring]
            if len(pts) >= 3:
                id_.polygon(pts, fill='#65e1d1' if code in seen else '#1c3e48', outline='#46636a')
    image.paste(inset, (1500, 750))
    draw.rectangle((1500, 750, 1860, 960), outline='#365666', width=2)


def draw_counties(image, shapes, bounds, t, warning=None, spoken=None):
    """County outlines for the story, labelled, with the warning polygon on top. Counties named in this
    shot's narration (`spoken`: code -> fraction of the shot where the name is said) light up then."""
    from PIL import Image, ImageDraw
    from .broadcast import map_point, label, easing
    spoken = spoken or {}
    u = easing(min(1, t * 2));layer = Image.new('RGBA', image.size, (0, 0, 0, 0));d = ImageDraw.Draw(layer)
    centres = []
    for shape in shapes:
        geometry = shape['geometry'];at = spoken.get(shape['code'])
        lit = easing(min(1, max(0, (t - at) * 4))) if at is not None else 0
        fill = (101, 225, 209, int((30 if spoken else 55) * u + 140 * lit))
        for polygon in (geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]):
            points = [map_point(c, bounds) for c in polygon[0]]
            if len(points) >= 3:
                d.polygon(points, fill=fill, outline=(190, 240, 235, 255))
                d.line(points + [points[0]], fill=(130, 239, 220, 255) if lit else (190, 240, 235, 255), width=6 if lit else 3)
                xs, ys = zip(*points)
                full = _county_index().get(shape['code'], {}).get('label', shape['name'])  # "Orleans Parish", "Hillsborough County"
                centres.append((shape['name'], sum(xs) / len(xs), sum(ys) / len(ys), lit, at is not None, full))
    for feature in warning or []:
        geometry = feature['geometry']
        for polygon in (geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]):
            points = [map_point(c, bounds) for c in polygon[0]]
            if len(points) >= 3 and t > .35:
                d.polygon(points, fill=(255, 200, 135, 80), outline=(255, 200, 135, 255))
                d.line(points + [points[0]], fill=(255, 200, 135, 255), width=5)
    image.paste(Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB'))
    draw = ImageDraw.Draw(image);seen = set()
    # Spoken counties are labelled last (on top) and larger, once they have lit up.
    for name, x, y, lit, named, full in sorted(centres, key=lambda c: c[4]):
        if name in seen or not (40 < x < 1800 and 100 < y < 950) or (named and lit < .3):
            continue
        seen.add(name)
        if named:
            text = full.upper()
            draw.rectangle((x - 13 * len(text) - 12, y - 24, x + 13 * len(text) + 12, y + 30), fill='#061724')
            label(draw, (x - 13 * len(text), y - 20), text, 44, '#ffffff')
        else:
            label(draw, (x - 9 * len(name), y - 16), name.upper(), 30, '#ffffff')
    census = any(s.get('source') == 'census' for s in shapes);zones = any(s.get('source') != 'census' for s in shapes)
    title = 'COUNTY OUTLINES · US CENSUS 2024' if census and not zones else 'WARNED AREAS · NWS ZONE + CENSUS OUTLINES' if census else 'WARNED AREAS · NWS ZONE OUTLINES'
    draw.rectangle((55, 120, 80 + 19 * len(title), 176), fill='#061724')
    label(draw, (80, 130), title, 30, '#82efdc')
    if warning:
        label(draw, (80, 900), 'Orange: warning polygon issued by the NWS office', 22, '#ffc887')


async def fetch_counties(store, client, advisory):
    """Cache official NWS zone geometry for every zone an alert names. Missing zones are reported, not drawn."""
    import httpx
    problems = []
    for url in zone_urls(advisory):
        if any(a['source_url'] == url for a in store.visual_assets('nws_zone')):
            continue
        try:
            response = await client.get(url, headers={'Accept': 'application/geo+json'})
            response.raise_for_status()
            data = response.json();geometry = data.get('geometry');props = data.get('properties', {})
            if not geometry or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
                raise ValueError('no polygon')
            name = props.get('name') or url.rsplit('/', 1)[-1]
            if props.get('state') and props.get('type') == 'county':
                name += ', ' + props['state']
            store.save_visual_asset({'kind': 'nws_zone', 'source_url': url, 'observed_at': advisory.issued_at.isoformat(),
                'content_type': 'application/geo+json', 'metadata': {'ugc': url.rsplit('/', 1)[-1], 'name': name, 'zone_type': props.get('type'),
                'attribution': 'NOAA/NWS zone boundaries'}},
                json.dumps({'type': 'Feature', 'geometry': geometry, 'properties': {'ugc': url.rsplit('/', 1)[-1], 'name': name}}).encode())
        except (httpx.HTTPError, ValueError) as error:
            problems.append(f"{url.rsplit('/', 1)[-1]}: zone outline unavailable ({error.__class__.__name__})")
    return problems


def county_shapes(store, advisory):
    """Cached outlines for the zones this alert names (counties, coastal or marine zones)."""
    wanted = set(zone_urls(advisory));shapes = []
    for asset in store.visual_assets('nws_zone'):
        if asset['source_url'] in wanted:
            body = json.loads(store.visual_asset(asset['id'])['body'])
            shapes.append({'code': asset['metadata']['ugc'], 'name': asset['metadata']['name'], 'geometry': body['geometry']})
    # Alert counties whose NWS outline is not cached (offline, or the zone service failed) use the bundled Census outline.
    have = {s['code'] for s in shapes}
    shapes += [bundled_county(code) for code, _ in counties(advisory) if code not in have and code in _county_index()]
    return shapes


@lru_cache(maxsize=1)
def _county_index():
    return json.loads((Path(__file__).parent / 'data/us-counties.json').read_text())['counties']


def bundled_county(code):
    """Census 2024 outline for an NWS county code (e.g. FLC057), shaped like a cached zone outline."""
    county = _county_index()[code]
    return {'code': code, 'name': county['name'], 'source': 'census',
            'geometry': {'type': 'MultiPolygon', 'coordinates': [[ring] for ring in county['rings']]}}


def story_states(parameters, advisory, text=''):
    """States a story covers: its alert counties, states named in the text, and states its geography touches."""
    from .observations import intersects, story_bounds
    states = {code[:2] for code, _ in counties(advisory)} | {c for m in mentions(text) for c in m['states']}
    region = story_bounds(parameters)
    if region:
        states |= {code for code, r in _state_index().items() if intersects(r['bounds'], region)}
    return states


def alert_codes(parameters, advisory):
    """NWS county codes the story's own alert names, used to settle county names shared across states."""
    return {code for code, _ in counties(advisory)} | {s['code'] for s in parameters.get('county_shapes', [])}


def county_mentions(text, states, prefer=()):
    """Counties named in narration ("Hillsborough County", "Hillsborough and Pinellas counties"), only
    within `states`. A name shared by counties in several of those states is resolved by the story's own
    alert counties (`prefer`, NWS codes); if they do not settle it, it is ambiguous and skipped."""
    found = {};lowered = text.lower()
    lists = [m.span(1) for m in re.finditer(r"((?:[\w.'’-]+(?:\s+[\w.'’-]+)?(?:,\s*|,?\s+and\s+))+[\w.'’-]+(?:\s+[\w.'’-]+)?)\s+(?:counties|parishes)\b", lowered)]
    by_name = {}
    for code, county in _county_index().items():
        if county['state'] in states:
            by_name.setdefault(county['name'].lower(), []).append(code)
    for name, codes in by_name.items():
        if len(codes) > 1:
            codes = [c for c in codes if c in prefer]
            if len(codes) != 1:
                continue
        spans = [m.start() for m in re.finditer(r'(?<!\w)' + re.escape(name) + r'\s+(?:county|parish|borough)\b', lowered)]
        for a, b in lists:
            spans += [a + m.start() for m in re.finditer(r'(?<!\w)' + re.escape(name) + r'(?!\w)', lowered[a:b])]
        if spans:
            start = min(spans);found[codes[0]] = {'code': codes[0], 'name': _county_index()[codes[0]]['name'], 'start': start,
                                                'word': len(text[:start].split())}
    return sorted(found.values(), key=lambda m: m['start'])


def locator(places, size=(440, 280)):
    """Small lower-48 map with the story's named places lit, for footage shots. It marks where the story
    is, not where the footage was filmed, and says so."""
    from PIL import Image, ImageDraw
    from .broadcast import map_point, font
    index = _state_index();lit = {code for p in places for code in p['states']}
    image = Image.new('RGBA', size, (6, 23, 36, 235));d = ImageDraw.Draw(image)
    conus = [-125, 24, -66, 50];inner = (size[0] - 20, size[1] - 70)
    for code, region in index.items():
        if code in ('AK', 'HI', 'PR'):
            continue
        for ring in region['rings']:
            pts = [(x + 10, y + 10) for x, y in (map_point(c, conus, size=inner) for c in ring)]
            if len(pts) >= 3:
                d.polygon(pts, fill='#65e1d1' if code in lit else '#1c3e48', outline='#46636a')
    names = ' · '.join(dict.fromkeys(p['name'] for p in places))
    d.text((12, size[1] - 56), ('STORY AREA: ' + names.upper())[:40], font=font(20), fill='#ffffff')
    d.text((12, size[1] - 28), 'Not the filming location', font=font(16), fill='#a8c4d0')
    return image
