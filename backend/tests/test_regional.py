"""Regional matching must never infer capture location from weather tags."""
import copy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.regional import catalogue,named_regions,focus,targets
from app.media_selection import rank
from app.broadcast import Composer,fit_bounds
from test_media_selection import asset
from test_production import prepare,upload


def florida_scene(**changes):
    return {'id':'florida','type':'storm_track','script_segment':'Rain and winds affect Florida.',
            'media_id':None,'cuts':[],'regional_focus':'auto','map_mode':'auto','graphic_style':'auto',
            'direction':{'scene_type':'region_focus','event_id':'test','duration':3,'headline':'FLORIDA SOURCE VIEW','layers':['reported_track'],'sources':[], 'asset_ids':[]},
            'parameters':{'credit':'Synthetic fixture','facts':{'wind_mph':85},'geojson':{'features':[]}},**changes}


def test_named_states_do_not_parse_ordinary_words_as_postal_codes():
    assert named_regions('Rain in Florida, then North Carolina.') == ['FL','NC']
    assert named_regions('rain IN the sea OR snow for ME') == []
    assert named_regions('Floridana beach and Carolina') == []
    assert len(catalogue()['regions'])==52
    assert len(catalogue()['source_checksum'])==64
    with pytest.raises(ValueError,match='conflicts'):targets(florida_scene(regional_focus='NC'))


def test_florida_ranking_excludes_unknown_unreviewed_and_other_state_footage():
    source='https://example.org/synthetic-capture-record'
    def tagged(identity,codes,reviewed=True):
        return asset(identity,catalog={'tags':['rain','wind'],'region_codes':codes,'location_reviewed':reviewed,'reference':source})
    chosen=tagged('florida',['FL']);unknown=asset('generic',catalog={'tags':['rain','wind'],'event_id':'AL092020','location':'Florida'})
    choices=rank(florida_scene(),[unknown,tagged('nc',['NC']),tagged('unreviewed',['FL'],False),chosen],SimpleNamespace(event_key='AL092020',issued_at=datetime(2020,8,4,tzinfo=timezone.utc)))
    assert [c['media_id'] for c in choices]==['florida']
    assert 'Reviewed capture region matches script' in choices[0]['reasons']
    with pytest.raises(ValueError,match='needs a matching capture region'):focus(florida_scene(media_id='nc'),{'nc':tagged('nc',['NC'])},'broadcast')


def test_florida_map_rejects_unrelated_geometry_and_clears_storm_wide_stats():
    scene=florida_scene();scene['parameters']['geojson']['features']=[
        {'type':'Feature','properties':{'kind':'reported_center','issued_at':'2020-08-04T03:00:00+00:00'},'geometry':{'type':'Point','coordinates':[-78,34]}}]
    scene['parameters']['map_warning_text']=['North Carolina coast','Florida coast']
    outcome=focus(scene,{},'broadcast')
    assert outcome['status']=='missing_regional_weather'
    assert scene['parameters']['geojson']['features']==[]
    assert scene['parameters']['facts']=={}
    assert scene['parameters']['map_warning_text']==['Florida coast']
    assert scene['parameters']['regional_title']=='Florida'
    composer=Composer(scene['direction'],copy.deepcopy(scene['parameters']))
    assert composer.bounds==pytest.approx(fit_bounds(tuple(scene['parameters']['bounds'])))
    assert composer.frame(.5).size==(1920,1080)
    assert scene['parameters']['regional_cartography']['source_checksum']==catalogue()['source_checksum']
    with pytest.raises(ValueError,match='storm-wide'):focus(florida_scene(type='what_changed'),{},'broadcast')
    with pytest.raises(ValueError,match='no verified regional extent'):focus(florida_scene(direction={**scene['direction'],'asset_ids':['native']}),{},'broadcast')


def test_regional_catalog_save_timeline_and_retry_keep_reviewed_location(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        _,plan,body=prepare(client);media=upload(client,name='rain-fixture.png').json()
        url=f"/api/production/media/{media['id']}/catalog"
        metadata={'tags':['rain','wind'],'region_codes':['FL'],'location_reviewed':True,'reference':'https://example.org/synthetic-florida-location'}
        assert client.put(url,json={**metadata,'reference':''}).status_code==422
        assert client.put(url,json={**metadata,'region_codes':['ZZ']}).status_code==422
        assert client.put(url,json=metadata).status_code==200
        assert client.get('/api/production').json()['regions']
        body['presentation']='broadcast';body['scenes'][0].update(regional_focus='FL',media_id=media['id'])
        saved=client.post('/api/production/timelines',json=body)
        assert saved.status_code==200,saved.text
        snapshot=saved.json();assert snapshot['scenes'][0]['regional_relevance']['regions']==['FL']
        assert snapshot['scenes'][0]['selection_catalog']['location_reviewed']
        client.put(url,json={**metadata,'region_codes':['NC']})
        assert not client.post('/api/production/check',json=body).json()['ready']
        validated,_=app.state.production.validate_timeline(snapshot)
        assert validated['scenes'][0]['selection_catalog']['region_codes']==['FL']
        wrong=client.post('/api/production/assist',json={'plan_id':plan['id'],'regional_focus':{'bad-scene':'FL'}})
        assert wrong.status_code==422


def test_regional_discovery_does_not_offer_unlocated_stock_as_florida(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        found=client.post('/api/production/discovery/search',json={'query':'Florida storm rain','live':False})
        assert found.status_code==200,found.text
        result=found.json()
        assert result['required_regions']==['FL']
        assert result['results']==[]
        assert 'Florida%20storm%20rain' in result['links']['pexels']
