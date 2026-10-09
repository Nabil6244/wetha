"""Synthetic fixtures validate source integrity; no fictional media in the real demo."""
import hashlib
import io
import json
from datetime import datetime, timezone

import pytest
from PIL import Image
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.broadcast import Camera, Composer, SceneDirection, VisualSource, camera_pose, dissolve_filter, fit_bounds, map_point, project, register_raster
from app.main import create_app
from test_production import prepare, wait_render


def source(**changes):
    base={'source_url':'https://www.weather.gov/images/synthetic-test.gif','checksum':'a'*64,'event_id':'AL092020',
          'data_type':'satellite_observation','historical':True,'observation_start':'2020-08-03T12:00:00+00:00',
          'observation_end':'2020-08-04T09:00:00+00:00','coverage':'Synthetic test viewport','projection':'native_viewport',
          'attribution':'Synthetic fixture','license':'Synthetic test media','catalogue_url':'https://www.weather.gov/test'}
    return VisualSource.model_validate({**base,**changes})


def test_event_year_timezone_forecast_and_scene_attribution():
    for changes in ({'event_id':'AL092026'},{'observation_start':'2020-08-03T12:00:00'},
                    {'observation_end':'2020-08-02T12:00:00+00:00'}, {'data_type':'forecast'}):
        with pytest.raises(ValidationError):source(**changes)
    with pytest.raises(ValidationError):
        SceneDirection(scene_type='satellite_wide',event_id='AL092026',duration=5,headline='Test',sources=[source()])
    with pytest.raises(ValidationError):
        SceneDirection(scene_type='radar_animation',event_id='AL092020',duration=5,headline='Test',sources=[source()])
    with pytest.raises(ValidationError):
        SceneDirection(scene_type='satellite_wide',event_id='AL092020',duration=5,headline=' '.join(['word']*9),sources=[source()])
    d=SceneDirection(scene_type='radar_animation',event_id='AL092020',duration=5,headline='Test',fallback='No source radar available')
    assert d.fallback


def test_deterministic_camera_and_no_native_geographic_tracking():
    for movement in ('smooth_zoom_in','smooth_zoom_out','geographic_pan','storm_follow','camera_drift','region_focus','satellite_to_map','map_to_footage'):
        c=Camera(movement=movement,geographic_target=(-80,32),end_zoom=1.6)
        assert camera_pose(c,0)==(1,.5,.5)
        assert camera_pose(c,.5)==camera_pose(c,.5)
        assert camera_pose(c,1)[0]==1.6
    with pytest.raises(ValidationError):Camera(start_center=(2,.5))
    with pytest.raises(ValidationError):Camera(start_zoom=float('nan'))
    with pytest.raises(ValidationError):Camera(movement='storm_follow')
    with pytest.raises(ValidationError):
        SceneDirection(scene_type='satellite_timelapse',event_id='AL092020',duration=5,headline='Test',sources=[source()],camera=Camera(movement='storm_follow',geographic_target=(-80,32)))


def test_mercator_camera_preserves_aspect_and_radar_registration():
    bounds=fit_bounds((-84,28,-73,37))
    x0,y0=project(bounds[0],bounds[3]);x1,y1=project(bounds[2],bounds[1])
    assert (x1-x0)/(y1-y0)==pytest.approx(1920/1080)
    assert map_point((bounds[0],bounds[3]),bounds)==pytest.approx((0,0))
    assert map_point((bounds[2],bounds[1]),bounds)==pytest.approx((1920,1080))
    im=Image.new('RGBA',(40,40));im.paste((255,0,0,255),(0,0,20,40));im.paste((0,255,0,255),(20,0,40,40))
    result=register_raster(im,[-90,25,-70,40],[-90,25,-70,40])
    assert result.getpixel((20,500))==(255,0,0,255)
    assert result.getpixel((1900,500))==(0,255,0,255)
    with pytest.raises(ValueError):fit_bounds((20,30,10,40))


def test_source_checksum_and_real_sequence_requirement():
    buf=io.BytesIO();Image.new('RGB',(100,100),'red').save(buf,format='PNG');raw=buf.getvalue()
    s=source(checksum=hashlib.sha256(raw).hexdigest())
    d=SceneDirection(scene_type='satellite_timelapse',event_id='AL092020',duration=5,headline='Test',sources=[s],asset_ids=['test'])
    with pytest.raises(ValueError,match='at least two'):Composer(d.model_dump(mode='json'),{},lambda _:raw)
    with pytest.raises(ValueError,match='checksum'):Composer(d.model_dump(mode='json'),{},lambda _:b'changed')


def test_transition_handles_retain_exact_benchmark_duration():
    filters,out,duration=dissolve_filter([5]+[5.3]*5)
    assert duration==pytest.approx(30)
    assert filters.count('xfade')==5 and 'offset=24.700000' in filters
    assert out=='[transition5]'


def test_broadcast_integrates_existing_revision_bound_render_pipeline(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _,_,body=prepare(client)
        timeline=client.post('/api/production/timelines',json={**body,'presentation':'broadcast','scenes':[{**s,'transition':'fade'} for s in body['scenes']]}).json()
        assert all(s['direction']['max_words']==8 for s in timeline['scenes'])
        assert all(len(s['direction']['headline'].split())<=8 for s in timeline['scenes'])
        job=client.post('/api/production/renders',json={'timeline_id':timeline['id']}).json()
        completed=wait_render(client,job['id'])
        assert completed['status']=='succeeded',completed['error']
        assert completed['validation']['decoded']
        manifest=client.get('/api/production/renders/'+job['id']+'/manifest').json()
        assert manifest['scene_directions']


def test_observation_chronology_and_projection_alignment():
    with pytest.raises(ValidationError):source(observation_times=['2020-08-04T01:00:00+00:00','2020-08-03T15:00:00+00:00'])
    with pytest.raises(ValidationError):source(observation_times=['2020-08-05T01:00:00+00:00'])
    with pytest.raises(ValidationError):
        SceneDirection(scene_type='satellite_timelapse',event_id='AL092020',duration=5,headline='Test',sources=[source(),source(projection='EPSG:3857')])
    with pytest.raises(ValidationError):
        SceneDirection(scene_type='storm_track',event_id='AL092020',duration=5,headline='Test',layers=['forecast_cone'])


def test_schema_is_available_to_the_visual_director(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response=client.get('/api/visuals/scene-schema')
        assert response.status_code==200 and 'camera' in response.json()['properties']
        _,plan,_=prepare(client)
        assert all(scene['direction']['schema_version']==1 for scene in plan['scenes'])


def test_live_advisory_event_year_must_match_issue_year():
    from xml.etree import ElementTree as ET
    from pathlib import Path
    from app.weather import parse_nhc
    root=ET.fromstring((Path(__file__).parent/'fixtures/nhc-atlantic-2026-10-08.xml').read_bytes())
    public=next(item for item in root.findall('./channel/item') if 'Public Advisory' in item.findtext('title',''))
    description=public.findtext('description')
    wrong=description.replace('AL092026','AL092020')
    with pytest.raises(ValueError,match='event ID year'):
        parse_nhc(wrong,public.findtext('link'),'official_fetch')
