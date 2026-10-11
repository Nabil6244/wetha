"""Archived radar, bundled county outlines with spoken-county timing, and SPC hazard probability outlooks."""
import asyncio
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app import broadcast, geography, radar_archive, spc
from app.main import create_app
from app.storage import Store
from app.visuals import VisualEvidence, region_extent, source_url
from test_visuals import synthetic_current

FIXTURES = Path(__file__).parent / 'fixtures'
# Synthetic archive composite: 0.05 degree grid over -100..-75 W, 25..45 N, like the IEM world-file layout.
DX, WEST, NORTH, SIZE = .05, -100.0, 45.0, (500, 400)
ECHO = (-87.75, 33.75)   # Centre of a 50 dBZ block (n0q index 164).
WEAK = (-84.75, 33.75)   # Centre of a 3 dBZ block (n0q index 70), below the transparency threshold.
WORLD = f'{DX}\n0.0\n0.0\n{-DX}\n{WEST}\n{NORTH}\n'.encode()


def composite():
    image = Image.new('P', SIZE, 0)
    image.putpalette([v for i in range(256) for v in ((255, 0, 0) if i == 164 else (0, 200, 0) if i == 70 else (i, i, 255 - i))])
    for (lon, lat), index in ((ECHO, 164), (WEAK, 70)):
        col, row = round((lon - WEST) / DX), round((NORTH - lat) / DX)
        image.paste(index, (col - 5, row - 5, col + 5, row + 5))
    out = io.BytesIO();image.save(out, 'PNG')
    return out.getvalue()


def archive_transport(calls, products=('n0q',)):
    body = composite()
    def handler(request):
        calls.append(str(request.url))
        name = request.url.path.rsplit('/', 1)[-1]
        if not name.startswith(products):
            return httpx.Response(404)
        return httpx.Response(200, content=body if name.endswith('.png') else WORLD,
                              headers={'content-type': 'image/png' if name.endswith('.png') else 'text/plain'})
    return httpx.MockTransport(handler)


def test_reprojected_archive_radar_is_georeferenced_and_transparent_without_echo():
    extent = [-90.0, 32.0, -84.0, 35.4]
    png = radar_archive.reproject(composite(), WORLD, extent, 'n0q')
    image = Image.open(io.BytesIO(png));rgba = image.convert('RGBA')
    assert image.mode == 'P' and image.width == radar_archive.WIDTH
    def at(coord):
        x, y = broadcast.map_point(coord, extent, size=image.size)
        return rgba.getpixel((int(x), int(y)))
    assert at(ECHO) == (255, 0, 0, 255)            # a source colour, unaltered, at the right place
    assert at(WEAK)[3] == 0                        # below 5 dBZ: transparent
    assert at((-89.0, 34.8))[3] == 0               # no echo: transparent
    with pytest.raises(ValueError, match='outside'):
        radar_archive.reproject(composite(), WORLD, [-120, 30, -110, 40], 'n0q')


def test_archive_falls_back_to_n0r_caches_frames_and_only_serves_past_stories(tmp_path):
    store = Store(tmp_path / 'db.sqlite3');store.initialize();calls = []
    evidence = VisualEvidence(store, transport=archive_transport(calls, products=('n0r',)))
    moment = datetime(2005, 8, 29, 12, 3, tzinfo=timezone.utc);region = [-89, 33, -86.5, 34.5]
    ids = asyncio.run(radar_archive.collect(evidence, moment, region))
    frames = sorted(store.visual_assets('radar'), key=lambda a: a['observed_at'])
    assert len(ids) == len(frames) == 6
    assert [a['observed_at'][11:16] for a in frames] == ['11:10', '11:20', '11:30', '11:40', '11:50', '12:00']
    meta = frames[-1]['metadata']
    assert meta['product'].endswith('(n0r)') and meta['projection'] == 'EPSG:3857' and meta['extent'] == region_extent(region)
    assert meta['original_sha256'] == hashlib.sha256(composite()).hexdigest() and 'Iowa Environmental Mesonet' in meta['attribution']
    assert store.visual_asset(meta['legend_asset_id'])['kind'] == 'radar_legend'
    requests = len(calls)
    assert asyncio.run(radar_archive.collect(evidence, moment, region)) == ids and len(calls) == requests   # served from cache
    with pytest.raises(ValueError, match='past stories'):
        asyncio.run(radar_archive.collect(evidence, datetime.now(timezone.utc), region))
    asyncio.run(evidence.client.aclose())


@pytest.mark.parametrize('url', ['https://mesonet.agron.iastate.edu/archive/data/2024/10/10/GIS/uscomp/n0q_202410100030.png',
                                 'https://mesonet.agron.iastate.edu/archive/data/2005/08/29/GIS/uscomp/n0r_200508291200.wld'])
def test_archive_frames_are_on_the_allowlist(url):
    assert source_url(url) == url


@pytest.mark.parametrize('url', ['https://mesonet.agron.iastate.edu/cgi-bin/anything.py',
                                 'https://mesonet.agron.iastate.edu/archive/data/2024/10/10/GIS/uscomp/n0q_202410100030.png?x=1',
                                 'https://evil.test/archive/data/2024/10/10/GIS/uscomp/n0q_202410100030.png'])
def test_other_archive_urls_are_rejected(url):
    with pytest.raises(ValueError):
        source_url(url)


def test_archived_radar_scene_renders_over_the_basemap(tmp_path):
    calls = []
    with TestClient(create_app(tmp_path, visual_transport=archive_transport(calls))) as client:
        a = synthetic_current(client).model_copy(update={'id': 'archived-story', 'issued_at': datetime.now(timezone.utc) - timedelta(days=2)})
        client.app.state.store.save_advisory(a)
        asyncio.run(radar_archive.collect(client.app.state.visuals, a.issued_at, [-89, 33, -86.5, 34.5]))
        script = client.post('/api/scripts', json={'advisory_id': a.id}).json()
        plan = client.post('/api/visuals/plans', json={'script_id': script['id'], 'expected_revision': 1}).json()
        body = {'plan_id': plan['id'], 'title': 'Archived radar', 'presentation': 'broadcast',
                'scenes': [{'id': s['id'], 'seconds': 1, 'map_mode': 'radar' if i == 0 else 'auto'} for i, s in enumerate(plan['scenes'])]}
        result = client.post('/api/production/timelines', json=body);assert result.status_code == 200, result.text
        scene = result.json()['scenes'][0]
        assert len(scene['parameters']['map_observations']) == 6 and not scene['direction']['fallback']
        assert all('Iowa Environmental Mesonet' in s['attribution'] for s in scene['direction']['sources'] if s['data_type'] == 'radar_reflectivity')
        assert scene['parameters']['credit'].endswith('Radar: ' + radar_archive.ATTRIBUTION)   # credited on screen
        composer = broadcast.Composer(scene['direction'], scene['parameters'], lambda id: client.app.state.production.map_asset(scene, id))
        frame = composer.frame(0)
        x, y = broadcast.map_point(ECHO, composer.bounds)
        assert frame.getpixel((int(x), int(y))) == (255, 0, 0)
        # Where there is no echo the basemap shows through instead of black.
        base = broadcast.map_base(composer.bounds)
        lines = broadcast.state_lines(composer.bounds)
        x, y = next((x, y) for y in range(400, 960, 7) for x in range(1100, 1900, 7) if lines.getpixel((x, y))[3] == 0)
        assert frame.getpixel((x, y)) == base.getpixel((x, y)) != (0, 0, 0)
        assert any(lines.getpixel((x, y))[3] for x in range(0, 1920, 4) for y in range(100, 980, 4))   # state lines drawn over the echo


def test_bundled_counties_are_source_pinned_and_keyed_by_nws_code():
    data = json.loads((Path(geography.__file__).parent / 'data/us-counties.json').read_text())
    assert data['year'] == 2024 and data['source_url'].endswith('cb_2024_us_county_20m.zip') and len(data['source_checksum']) == 64
    counties = data['counties']
    assert len(counties) == 3222
    assert counties['FLC057']['label'] == 'Hillsborough County' and counties['FLC057']['fips'] == '12057'
    assert counties['LAC071']['label'] == 'Orleans Parish' and counties['NMC013']['name'] == 'Doña Ana'


@pytest.mark.parametrize('text,states,expected', [
    ('Hurricane warnings now cover Hillsborough County and Pinellas County.', {'FL'}, [('Hillsborough', 4), ('Pinellas', 7)]),
    ('Flooding hit Hillsborough and Pinellas counties overnight.', {'FL'}, [('Hillsborough', 2), ('Pinellas', 4)]),
    ('Orleans Parish is under a flash flood warning.', {'LA'}, [('Orleans', 0)]),
    ('Washington County saw damage.', {'FL', 'AL', 'GA'}, []),   # several Washington Counties: never guessed
    ('Hillsborough County flooded.', {'NH'}, [('Hillsborough', 0)]),
    ('Hillsborough County flooded.', {'TX'}, []),               # outside the story's states
    ('Polk was quiet.', {'FL'}, []),                             # a bare name is not a county mention
])
def test_spoken_counties_resolve_only_inside_the_story_states(text, states, expected):
    assert [(m['name'], m['word']) for m in geography.county_mentions(text, states)] == expected


def test_a_county_name_shared_across_states_is_settled_by_the_alert():
    # From a real bulletin: Macon County exists in both Alabama and Georgia; the flash flood warning named Macon, AL.
    text = 'Bullock, Macon and Russell counties, along'
    assert [m['name'] for m in geography.county_mentions(text, {'AL', 'GA'})] == ['Bullock', 'Russell']
    assert [m['code'] for m in geography.county_mentions(text, {'AL', 'GA'}, {'ALC011', 'ALC087', 'ALC113'})] == ['ALC011', 'ALC087', 'ALC113']


def warning(codes, area):
    return SimpleNamespace(source_payload={'properties': {'geocode': {'UGC': codes}, 'affectedZones': []}}, area=area)


def test_alert_counties_fall_back_to_census_outlines_when_zones_are_not_cached(tmp_path):
    store = Store(tmp_path / 'db.sqlite3');store.initialize()
    shapes = geography.county_shapes(store, warning(['FLC057', 'FLC103', 'CTC001'], 'Hillsborough, FL; Pinellas, FL; Fairfield, CT'))
    assert [(s['code'], s['source']) for s in shapes] == [('FLC057', 'census'), ('FLC103', 'census')]   # no 2024 outline for CTC001


def tampa_scenes(texts, advisory, shared):
    polygon = {'type': 'Feature', 'properties': {'kind': 'alert_area'},
               'geometry': {'type': 'Polygon', 'coordinates': [[[-82.9, 27.5], [-82.0, 27.5], [-82.0, 28.2], [-82.9, 28.2], [-82.9, 27.5]]]}}
    scenes = []
    for i, text in enumerate(texts):
        scene = {'id': f's{i}', 'type': 'region_focus', 'script_segment': text, 'seconds': 4, 'media_id': None, 'cuts': [], 'map_mode': 'auto',
                 'graphic_style': 'auto', 'parameters': {'source_advisory_id': 'h', 'geojson': {'features': [polygon]}, 'credit': 'NHC', 'county_shapes': shared}}
        scene['direction'] = broadcast.director(scene, 'urn:h', 4)
        scenes.append(scene)
    return scenes


def test_a_spoken_county_gets_its_own_shot_and_lights_up_when_it_is_said():
    from app.visual_states import assign
    advisory = SimpleNamespace(title='Hurricane Milton Advisory 18', event_key='AL142024', forecast_excerpt='', warnings=[], provider='NHC',
                               area='', issued_at=datetime(2024, 10, 9, 21, tzinfo=timezone.utc), facts={}, source_payload={})
    shared = [geography.bundled_county('FLC081')]   # the story's alert outlines, shared by all its shots
    scenes = tampa_scenes(['Hurricane warnings in Florida now cover Hillsborough County and Pinellas County.', 'Conditions worsened through the evening.'], advisory, shared)
    states = assign(scenes, lambda _: advisory)
    p = scenes[0]['parameters']
    assert states[0] == 'county_focus'   # the county outranks the state named in the same beat
    assert list(p['spoken_counties']) == ['FLC057', 'FLC103'] and p['spoken_counties']['FLC057'] < p['spoken_counties']['FLC103']
    assert scenes[0]['direction']['headline'] == 'HILLSBOROUGH · PINELLAS'
    assert -83.6 < p['bounds'][0] < p['bounds'][2] < -81.4 and 27 < p['bounds'][1] < p['bounds'][3] < 28.8
    assert len(shared) == 1 and {s['code'] for s in p['county_shapes']} == {'FLC081', 'FLC057', 'FLC103'}
    composer = broadcast.Composer(scenes[0]['direction'], p)
    x, y = broadcast.map_point((-82.3, 27.68), composer.bounds)   # inside Hillsborough, clear of its label
    before, after = composer.frame(.2).getpixel((int(x), int(y))), composer.frame(.9).getpixel((int(x), int(y)))
    assert sum(after) > sum(before) + 60   # lit only once its name has been said


def collect_spc(store, fixture, product):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=(FIXTURES / fixture).read_bytes()))) as client:
            return await spc.collect(store, client, 1, product=product)
    return asyncio.run(run())


def test_tornado_probability_outlook_is_cached_and_chosen_for_tornado_beats(tmp_path):
    store = Store(tmp_path / 'db.sqlite3');store.initialize()
    collect_spc(store, 'spc-day1-torn-2026-10-11.json', 'torn')
    inside = datetime(2026, 10, 11, 18, tzinfo=timezone.utc)
    outlook = spc.find(store, inside, 'torn')
    assert outlook['product'] == 'torn' and outlook['categories'] == ['0.02', '0.05']
    assert [f['properties']['name'] for f in outlook['features']] == ['2% Tornado Risk', '5% Tornado Risk']
    assert spc.find(store, inside) is None                      # never returned as the categorical outlook
    assert spc.find(store, datetime(2026, 10, 13, tzinfo=timezone.utc), 'torn') is None
    image = broadcast.map_base(tuple(spc.bounds(outlook))).copy()
    spc.draw(image, outlook, spc.bounds(outlook), .5)
    assert image.size == (1920, 1080)


def test_an_empty_probability_outlook_is_low_risk_not_a_map(tmp_path):
    store = Store(tmp_path / 'db.sqlite3');store.initialize()
    with pytest.raises(ValueError, match='no risk area'):
        collect_spc(store, 'spc-day1-hail-2026-10-11.json', 'hail')
    assert store.visual_assets('spc_outlook') == []


@pytest.mark.parametrize('text,hazard,product', [
    ('A tornado touched down near Moore.', 'tornado', 'torn'),
    ('Large hail pounded the city.', 'severe_storm', 'hail'),
    ('Damaging winds knocked out power.', 'severe_storm', 'wind'),
    ('Thunderstorms rolled through.', 'severe_storm', 'cat'),
])
def test_the_beat_picks_its_hazard_outlook(text, hazard, product):
    assert spc.product_for(text, hazard) == product


def test_old_stories_use_archived_radar_when_nowcoast_has_moved_on(monkeypatch):
    from app import orchestrator
    advisory = SimpleNamespace(id='a', provider='NHC', title='Hurricane Milton', issued_at=datetime(2024, 10, 10, 0, 30, tzinfo=timezone.utc))
    async def gone(moment, region):
        raise ValueError('Radar for 10 Oct 00:30 UTC is not served any more.')
    async def archive(service, moment, region, frames=6):
        assert moment == advisory.issued_at;return ['f1', 'f2', 'f3']
    async def no_goes(identity):
        raise ValueError('offline')
    monkeypatch.setattr(radar_archive, 'collect', archive)
    geojson = {'features': [{'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Point', 'coordinates': [-82.5, 27.3]}}]}
    job = {'issues': [], 'stages': [{'key': 'data', 'label': 'Data', 'status': 'queued'}]}
    fake = SimpleNamespace(visuals=SimpleNamespace(collect_radar_at=gone, collect=no_goes, geography=lambda identity: {'geojson': geojson}),
                           store=SimpleNamespace(visual_plan=lambda _: {'advisory_id': 'a', 'scenes': [{'script_segment': 'Rain bands moved ashore.', 'parameters': {}}]},
                                                 advisory=lambda _: advisory),
                           stage=lambda job, key, status, detail='': job.update(detail=detail))
    asyncio.run(orchestrator.Orchestrator.collect_data(fake, job, 'plan'))
    assert '3 archived radar frames at 10 Oct 2024 00:30 UTC' in job['data']['collected']
    assert not any(m.startswith('Radar') for m in job['data']['unavailable'])


def test_radar_for_a_story_is_its_own_area_and_never_from_after_it(tmp_path):
    # From a real bulletin: a Georgia-coast marine warning (06:40) was shown an Alabama close-up from 07:20.
    from app import observations
    with TestClient(create_app(tmp_path)) as client:
        a = synthetic_current(client).model_copy(update={'id': 'coast', 'issued_at': datetime(2026, 10, 10, 6, 40, tzinfo=timezone.utc)})
        store = client.app.state.store;png = io.BytesIO();Image.new('RGBA', (64, 36), (0, 0, 0, 0)).save(png, 'PNG')
        coast, inland = [-82.0, 30.5, -80.5, 31.5], [-87.5, 31.5, -84.5, 33.5]
        for name, region, start in (('coast', coast, 6 * 60), ('inland', inland, 6 * 60 + 30)):
            for k in range(6):
                stamp = datetime(2026, 10, 10, tzinfo=timezone.utc) + timedelta(minutes=start + 10 * k)
                store.save_visual_asset({'kind': 'radar', 'source_url': f'https://example.test/{name}/{k}', 'observed_at': stamp.isoformat(), 'content_type': 'image/png',
                                         'metadata': {'projection': 'EPSG:3857', 'extent': region_extent(region)}}, png.getvalue() + name.encode() + bytes([k]))
        geojson = {'features': [{'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-81.6, 30.7], [-80.9, 30.7], [-80.9, 31.3], [-81.6, 31.3], [-81.6, 30.7]]]}}]}
        source = broadcast.VisualSource(source_url='https://api.weather.gov/alerts/x', checksum='0' * 64, event_id=a.event_key, data_type='reported_center', historical=True,
                                        observation_start=a.issued_at, observation_end=a.issued_at, coverage='test', projection='EPSG:4326',
                                        attribution='NWS', license='Public domain', catalogue_url='https://api.weather.gov/alerts/x')
        option = observations.radar_option(client.app.state.production, a, {'geojson': geojson}, source)
        assert option['extent'] == region_extent(coast)
        assert option['frames'] and max(option['frames']) <= (a.issued_at + timedelta(minutes=5)).isoformat()


def test_a_cited_story_warning_never_leaks_into_another_storys_scene():
    # From a real bulletin: a beat about the Altamaha Sound marine warning also cited an Alabama flash flood warning,
    # and the timeline merged both polygons into the marine story's map, radar region and warning overlay.
    from app.observations import story_bounds
    from app.production import scene_geography
    from app.visual_states import assign
    def area(advisory, ring):
        return {'type': 'Feature', 'properties': {'kind': 'alert_area', 'advisory_id': advisory}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}
    marine = area('marine', [[-81.36, 30.58], [-80.35, 30.58], [-80.35, 31.28], [-81.36, 31.28], [-81.36, 30.58]])
    marine_update = area('marine-update', [[-81.2, 30.7], [-80.6, 30.7], [-80.6, 31.1], [-81.2, 31.1], [-81.2, 30.7]])   # same story, overlapping
    flood = area('flood', [[-86.5, 31.95], [-84.89, 31.95], [-84.89, 32.74], [-86.5, 32.74], [-86.5, 31.95]])
    stories = {'marine': {'features': [marine, marine_update]}, 'flood': {'features': [flood]}}
    own, cited = scene_geography('marine', ['marine', 'flood'], stories.__getitem__)
    assert [f['properties']['advisory_id'] for f in own['features']] == ['marine', 'marine-update']   # own overlap kept
    assert [(f['properties']['advisory_id'], f['properties']['cited_by_advisory_id']) for f in cited['features']] == [('flood', 'marine')]
    assert scene_geography('marine', ['marine'], stories.__getitem__)[1] is None
    p = {'source_advisory_id': 'marine', 'geojson': own, 'cited_geojson': cited, 'credit': 'NWS'}
    assert story_bounds(p) == [-81.36, 30.58, -80.35, 31.28]   # framing and radar region: this story only
    advisory = SimpleNamespace(title='Special Marine Warning', event_key='urn:m', forecast_excerpt='', warnings=[], provider='NWS', area='Coastal waters',
                               issued_at=datetime(2026, 10, 10, 6, 40, tzinfo=timezone.utc), facts={}, source_payload={})
    scene = {'id': 's0', 'type': 'region_focus', 'script_segment': 'Off the Georgia coast, a strong thunderstorm threatened small boats.', 'seconds': 4,
             'media_id': None, 'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto', 'parameters': p}
    scene['direction'] = broadcast.director(scene, 'urn:m', 4)
    assert assign([scene], lambda _: advisory) == ['place_focus']
    assert {f['properties']['advisory_id'] for f in p['place_warning']} == {'marine', 'marine-update'}   # drawn warnings: own only
