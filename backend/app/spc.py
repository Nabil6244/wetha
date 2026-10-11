"""NOAA/NWS Storm Prediction Center convective outlooks: categorical risk areas (Days 1-3) and the
Day 1 tornado, damaging-wind and hail probability areas.

Public data, no key. SPC updates Day 1 several times a day; each issuance is cached under its own
issue time, so an outlook is never silently replaced. An outlook is only used for a story whose time
falls inside the outlook's valid period; outside it, no outlook is shown. A probability outlook with
no area ("less than 2% everywhere") is a real forecast of low risk and is not drawn as a map.
"""
import asyncio
import json
import re
from datetime import datetime
import httpx
from .visuals import valid_geometry

URLS = {day: f'https://www.spc.noaa.gov/products/outlook/day{day}otlk_cat.lyr.geojson' for day in (1, 2, 3)}
PROBABILITY = {'torn': 'TORNADO', 'wind': 'DAMAGING WIND', 'hail': 'HAIL'}  # Day 1 probability products
PRODUCT_URLS = {(1, product): f'https://www.spc.noaa.gov/products/outlook/day1otlk_{product}.lyr.geojson' for product in PROBABILITY}
CATALOGUE = 'https://www.spc.noaa.gov/products/outlook/'
ORDER = ['TSTM', 'MRGL', 'SLGT', 'ENH', 'MDT', 'HIGH']
NAMES = {'TSTM': 'General thunderstorms', 'MRGL': 'Marginal risk', 'SLGT': 'Slight risk', 'ENH': 'Enhanced risk', 'MDT': 'Moderate risk', 'HIGH': 'High risk'}
MAX_BYTES = 5 * 1024 * 1024


def parse(body, product='cat'):
    data = json.loads(body)
    features = []
    for feature in data.get('features', []):
        props = feature.get('properties', {})
        if product == 'cat':
            if props.get('LABEL') not in ORDER:
                continue
            name, rank = NAMES[props['LABEL']], ORDER.index(props['LABEL'])
        else:
            # Probability areas are labelled with the probability itself ("0.05"); every area is organized risk.
            if not re.fullmatch(r'0\.\d+', props.get('LABEL') or ''):
                continue
            name, rank = props.get('LABEL2') or f"{round(float(props['LABEL']) * 100)}% {PROBABILITY[product].lower()} risk", 1 + round(float(props['LABEL']) * 100)
        valid_geometry(feature['geometry'])
        features.append({'type': 'Feature', 'geometry': feature['geometry'],
                         'properties': {'label': props['LABEL'], 'name': name, 'fill': props.get('fill', '#cccccc'),
                                        'stroke': props.get('stroke', '#888888'), 'rank': rank}})
    if not data.get('features'):
        raise ValueError('The SPC outlook contained no areas.')
    props = data['features'][0]['properties']
    times = {k: datetime.fromisoformat(props[k + '_ISO']) for k in ('ISSUE', 'VALID', 'EXPIRE')}
    return features, times, props.get('FORECASTER', '')


async def collect(store, client=None, day=1, attempts=3, product='cat'):
    """Fetch and cache the current outlook for a day and product. Returns the cached asset id."""
    url = URLS[day] if product == 'cat' else PRODUCT_URLS[(day, product)]
    owned = client is None
    client = client or httpx.AsyncClient(timeout=20, headers={'User-Agent': 'WeatherIntelligenceStudio/0.6 (local weather video production)'})
    try:
        for attempt in range(attempts):
            try:
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > MAX_BYTES:
                    raise ValueError('SPC outlook exceeds the size limit.')
                break
            except httpx.HTTPError as error:
                if attempt == attempts - 1:
                    raise ValueError(f'SPC outlook is unavailable ({error.__class__.__name__}). No outlook will be shown.') from error
                await asyncio.sleep(2 ** attempt)
        features, times, forecaster = parse(response.content, product)
        if not features and product != 'cat':
            raise ValueError(f'The current SPC {PROBABILITY[product].lower()} outlook has no risk area.')
        body = json.dumps({'type': 'FeatureCollection', 'features': features}).encode()
        return store.save_visual_asset({'kind': 'spc_outlook', 'source_url': url + '#issued=' + times['ISSUE'].isoformat(),
            'observed_at': times['ISSUE'].isoformat(), 'content_type': 'application/geo+json',
            'metadata': {'day': day, 'product': product, 'issued_at': times['ISSUE'].isoformat(), 'valid_at': times['VALID'].isoformat(),
                         'expires_at': times['EXPIRE'].isoformat(),
                         'categories': [l for _, l in sorted({(f['properties']['rank'], f['properties']['label']) for f in features})],
                         'forecaster': forecaster, 'data_class': 'forecast', 'attribution': 'NOAA/NWS Storm Prediction Center',
                         'catalogue_url': CATALOGUE}}, body)
    finally:
        if owned:
            await client.aclose()


def product_for(text, hazard):
    """The outlook that matches a beat: tornado probabilities for tornadoes, hail or wind probabilities
    when the narration names them, otherwise the categorical risk."""
    if hazard == 'tornado':
        return 'torn'
    if re.search(r'\bhail\w*', text, re.I):
        return 'hail'
    if re.search(r'\b(damaging|destructive|straight[- ]line) winds?\b', text, re.I):
        return 'wind'
    return 'cat'


def find(store, moment, product='cat'):
    """The latest-issued outlook of this product whose valid period contains `moment`, or None."""
    for row in sorted(store.visual_assets('spc_outlook'), key=lambda r: r['metadata']['issued_at'], reverse=True):
        meta = row['metadata']
        if meta.get('product', 'cat') != product:
            continue
        if datetime.fromisoformat(meta['valid_at']) <= moment <= datetime.fromisoformat(meta['expires_at']):
            asset = store.visual_asset(row['id'])
            return {**meta, 'id': row['id'], 'checksum': row['checksum'], 'source_url': row['source_url'],
                    'features': json.loads(asset['body'])['features']}
    return None


def bounds(outlook):
    """Viewport around the organized-risk areas (marginal and above), or all areas if only thunder is forecast."""
    rings = []
    def collect_points(value):
        if len(value) >= 2 and isinstance(value[0], (int, float)):
            rings.append(value[:2])
        else:
            for child in value:
                collect_points(child)
    risky = [f for f in outlook['features'] if f['properties']['rank'] >= 1] or outlook['features']
    for feature in risky:
        collect_points(feature['geometry']['coordinates'])
    if not rings:
        return [-125, 24, -66, 50]
    west, east = min(p[0] for p in rings), max(p[0] for p in rings)
    south, north = min(p[1] for p in rings), max(p[1] for p in rings)
    return [max(-179, west - 3), max(-80, south - 2), min(179, east + 3), min(80, north + 2)]


def draw(image, outlook, bounds_, t):
    """Filled risk areas from lowest to highest category, with a legend and the valid period."""
    from PIL import Image, ImageDraw
    from .broadcast import map_point, label
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0));d = ImageDraw.Draw(layer)
    for feature in sorted(outlook['features'], key=lambda f: f['properties']['rank']):
        geometry = feature['geometry'];props = feature['properties']
        polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
        fill = tuple(int(props['fill'][i:i + 2], 16) for i in (1, 3, 5))
        stroke = tuple(int(props['stroke'][i:i + 2], 16) for i in (1, 3, 5))
        for polygon in polygons:
            points = [map_point(c, bounds_) for c in polygon[0]]
            if len(points) >= 3:
                d.polygon(points, fill=fill + (110,), outline=stroke + (255,))
                d.line(points + [points[0]], fill=stroke + (255,), width=3)
    image.paste(Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB'))
    draw_ = ImageDraw.Draw(image)
    present = sorted({(f['properties']['rank'], f['properties']['name'], f['properties']['fill']) for f in outlook['features']})
    draw_.rectangle((1380, 110, 1880, 140 + 44 * len(present) + 70), fill='#061724')
    kind = PROBABILITY.get(outlook.get('product', 'cat'))
    label(draw_, (1400, 122), f"SPC DAY {outlook['day']} · {kind} PROBABILITY" if kind else f"SPC DAY {outlook['day']} OUTLOOK · FORECAST", 24, '#65e1d1')
    for i, (_, name, fill) in enumerate(present):
        y = 165 + i * 44
        draw_.rectangle((1400, y, 1430, y + 28), fill=fill)
        label(draw_, (1445, y), name, 24)
    valid = datetime.fromisoformat(outlook['valid_at']).strftime('%d %b %H:%M');expires = datetime.fromisoformat(outlook['expires_at']).strftime('%d %b %H:%M UTC')
    label(draw_, (1400, 165 + 44 * len(present) + 8), f'Valid {valid} – {expires}', 20, '#a8c4d0')
