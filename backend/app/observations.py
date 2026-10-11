"""Time-matched radar and satellite options for a story, built from cached NOAA observations.

An option exists only when real frames cover the story's place and time: radar within an hour of the
advisory and intersecting the story region; GOES frames within 90 minutes over the Gulf/Atlantic
sector. Otherwise there is no option and the director picks another real visual.
"""
import copy
import hashlib
import io
from datetime import datetime
from uuid import uuid4
from PIL import Image
from . import broadcast

GOES_SECTOR = [-100, 15, -70, 34]  # Approximate coverage of the cached GOES-19 GeoColor sector.
SATELLITE_WINDOW = 5400
RADAR_WINDOW = 3600


def intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def story_bounds(parameters):
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
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def write_observation(service, asset):
    row = service.store.visual_asset(asset['id'])
    if hashlib.sha256(row['body']).hexdigest() != asset['checksum']:
        raise ValueError('Cached NOAA observation checksum changed.')
    with Image.open(io.BytesIO(row['body'])) as image:
        image.verify()
    path = service.root / 'observations' / (asset['checksum'] + '.image')
    if not path.exists():
        temporary = path.with_name(str(uuid4()) + '.part');temporary.write_bytes(row['body']);temporary.replace(path)
    return path.name


def radar_option(service, advisory, parameters, source):
    """Reuse the radar map scene with frames near the story time whose extent covers the story region."""
    from .map_scenes import prepare
    region = story_bounds(parameters)
    if not region:
        return None
    candidates = [a for a in service.store.visual_assets('radar')
                  if abs((datetime.fromisoformat(a['observed_at']) - advisory.issued_at).total_seconds()) <= RADAR_WINDOW
                  and a['metadata'].get('projection') == 'EPSG:3857' and intersects(a['metadata']['extent'], region)]
    if len(candidates) < 2:
        return None
    # Prefer the tightest extent around the story (sharper close-ups), then most frames.
    extents = {}
    for a in candidates:
        extents.setdefault(tuple(a['metadata']['extent']), []).append(a)
    best = min((e for e in extents if len(extents[e]) >= 2), key=lambda e: ((e[2] - e[0]) * (e[3] - e[1]), -len(extents[e])), default=None)
    if best is None:
        return None
    scene = {'map_mode': 'radar', 'seconds': 4, 'parameters': copy.deepcopy(parameters)}
    direction = prepare(service, scene, advisory, source, radar_assets=extents[best])
    p = scene['parameters']
    if not p.get('map_has_layer'):
        return None
    # Frame the story region inside the radar image instead of the whole extent.
    p['bounds'] = [max(best[0], region[0] - 1.2), max(best[1], region[1] - 0.9), min(best[2], region[2] + 1.2), min(best[3], region[3] + 0.9)]
    keys = ('radar_extent', 'bounds', 'map_observations', 'map_legend', 'map_mode', 'map_warning_text', 'map_source_label',
            'map_forecast_text', 'map_issue_time', 'fallback_label', 'map_has_layer', 'credit')
    return {'direction': direction, 'parameters': {k: p[k] for k in keys if k in p},
            'frames': [a['observed_at'] for a in extents[best]], 'extent': list(best)}


def satellite_option(service, advisory, parameters, source):
    """GOES GeoColor frames near the story time when the story lies in the sector. Native viewport, labelled context."""
    region = story_bounds(parameters)
    if not region or not intersects(region, GOES_SECTOR):
        return None
    assets = sorted([a for a in service.store.visual_assets('goes')
                     if abs((datetime.fromisoformat(a['observed_at']) - advisory.issued_at).total_seconds()) <= SATELLITE_WINDOW],
                    key=lambda a: a['observed_at'])[-12:]
    if len(assets) < 2:
        return None
    pinned = []
    for asset in assets:
        pinned.append({**{k: asset[k] for k in ('id', 'source_url', 'observed_at', 'content_type', 'checksum', 'metadata')},
                       'filename': write_observation(service, asset), 'license': 'NOAA STAR image reuse with NOAA/NESDIS/STAR credit'})
    sources = [broadcast.VisualSource(**{**source.model_dump(), 'data_type': 'satellite_observation', 'source_url': a['source_url'], 'checksum': a['checksum'],
               'observation_start': datetime.fromisoformat(a['observed_at']), 'observation_end': datetime.fromisoformat(a['observed_at']),
               'projection': 'native_viewport', 'coverage': 'Gulf/Atlantic regional context; event attribution unverified',
               'attribution': 'NOAA / NESDIS / STAR', 'license': a['license'], 'catalogue_url': a['source_url']}) for a in pinned]
    direction = broadcast.SceneDirection(scene_type='satellite_timelapse', event_id=advisory.event_key, duration=4, headline='SATELLITE VIEW',
        layers=['satellite'], asset_ids=[a['id'] for a in pinned], sources=sources,
        camera=broadcast.Camera(movement='smooth_zoom_in', end_zoom=1.06)).model_dump(mode='json')
    return {'direction': direction, 'parameters': {'map_observations': pinned,
            'credit': 'NOAA / NESDIS / STAR GOES-19 GeoColor · regional context · observation times shown'},
            'frames': [a['observed_at'] for a in pinned]}
