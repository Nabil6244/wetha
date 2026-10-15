"""Time-matched radar and satellite options for a story, built from cached NOAA observations.

An option exists only when real frames cover the story's place and time: radar within an hour of the
advisory and intersecting the story region; GOES frames within 90 minutes over the Gulf/Atlantic
sector. Otherwise there is no option and the director picks another real visual.
"""
import copy
import hashlib
import io
import math
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


def radar_option(service, advisory, parameters, source, story_geojson=None):
    """Reuse the radar map scene with frames near the story time whose extent covers the story region."""
    from .map_scenes import prepare
    # The story's own geography: the region its frames were collected for (a scene's map may carry more).
    own = getattr(service, 'story_geography', None)
    region = (story_bounds({'geojson': story_geojson}) if story_geojson is not None else
              story_bounds({'geojson': own(advisory.id)}) if own else None) or story_bounds(parameters)
    if not region:
        return None
    # Frames from the hour up to the story time only: radar observed after the story is not its evidence.
    candidates = [a for a in service.store.visual_assets('radar')
                  if -RADAR_WINDOW <= (datetime.fromisoformat(a['observed_at']) - advisory.issued_at).total_seconds() <= 300
                  and a['metadata'].get('projection') == 'EPSG:3857' and intersects(a['metadata']['extent'], region)]
    if len(candidates) < 2:
        return None
    # Prefer an extent that holds the whole story region and is centred on it (another story's cached close-up
    # may only clip this one), then the tightest extent, then most frames.
    extents = {}
    for a in candidates:
        extents.setdefault(tuple(a['metadata']['extent']), []).append(a)
    cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
    def rank(e):
        holds = e[0] <= region[0] and e[1] <= region[1] and e[2] >= region[2] and e[3] >= region[3]
        return (not holds, round(math.hypot((e[0] + e[2]) / 2 - cx, (e[1] + e[3]) / 2 - cy), 1), (e[2] - e[0]) * (e[3] - e[1]), -len(extents[e]))
    best = min((e for e in extents if len(extents[e]) >= 2), key=rank, default=None)
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
    if not region:
        return None
    from .satellite import matching
    candidates = matching(service.store.visual_assets('goes'), advisory.issued_at, region)
    groups = {}
    for asset in candidates:
        groups.setdefault(asset['metadata'].get('sector', 'ga'), []).append(asset)
    loops = [sorted(group, key=lambda a:a['observed_at'])[-6:] for group in groups.values() if len(group)>=2]
    if not loops:
        return None
    # Never alternate incompatible sectors within the same observation loop.
    assets = min(loops, key=lambda group:(abs((datetime.fromisoformat(group[-1]['observed_at'])-advisory.issued_at).total_seconds()),
                 (group[0]['metadata'].get('extent', GOES_SECTOR)[2]-group[0]['metadata'].get('extent', GOES_SECTOR)[0])))
    coverage = assets[0]['metadata'].get('product','Gulf/Atlantic regional context') + '; event attribution unverified'
    pinned = []
    for asset in assets:
        pinned.append({**{k: asset[k] for k in ('id', 'source_url', 'observed_at', 'content_type', 'checksum', 'metadata')},
                       'filename': write_observation(service, asset), 'license': 'NOAA STAR image reuse with NOAA/NESDIS/STAR credit'})
    sources = [broadcast.VisualSource(**{**source.model_dump(), 'data_type': 'satellite_observation', 'source_url': a['source_url'], 'checksum': a['checksum'],
               'observation_start': datetime.fromisoformat(a['observed_at']), 'observation_end': datetime.fromisoformat(a['observed_at']),
               'projection': 'native_viewport', 'coverage': coverage,
               'attribution': 'CIRA / NOAA / NESDIS / STAR', 'license': a['license'], 'catalogue_url': a['source_url']}) for a in pinned]
    direction = broadcast.SceneDirection(scene_type='satellite_timelapse', event_id=advisory.event_key, duration=4, headline='SATELLITE VIEW',
        layers=['satellite'], asset_ids=[a['id'] for a in pinned], sources=sources,
        camera=broadcast.Camera(movement='smooth_zoom_in', end_zoom=1.06)).model_dump(mode='json')
    return {'direction': direction, 'parameters': {'map_observations': pinned,
            'credit': 'CIRA / NOAA / NESDIS / STAR GOES-19 GeoColor · regional context · observation times shown'},
            'frames': [a['observed_at'] for a in pinned]}
