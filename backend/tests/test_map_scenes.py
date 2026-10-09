import io,json
from datetime import timedelta
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app
from app.broadcast import Composer
from test_production import prepare,wait_render
from test_visuals import synthetic_current


def test_four_maps_keep_explicit_fallbacks_and_survive_save_reload(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _,plan,body=prepare(client)
        body['presentation']='broadcast'
        for i,mode in enumerate(['track','warnings','radar','forecast']):body['scenes'][i]['map_mode']=mode
        result=client.post('/api/production/timelines',json=body)
        assert result.status_code==200,result.text
        timeline=result.json()
        assert [s['parameters']['map_mode'] for s in timeline['scenes'][:4]]==['track','warnings','radar','forecast']
        assert 'polygon' in timeline['scenes'][1]['direction']['fallback']
        assert 'Rainfall' in timeline['scenes'][2]['direction']['fallback']
        assert 'predicted path' in timeline['scenes'][3]['direction']['fallback']
        assert not any(s['direction']['asset_ids'] for s in timeline['scenes'])
        for s in timeline['scenes'][:4]:
            assert s['parameters']['map_source_label']=='TRAINING'
            assert Composer(s['direction'],s['parameters']).frame(.5).size==(1920,1080)
        job=client.post('/api/production/renders',json={'timeline_id':timeline['id']}).json()
        finished=wait_render(client,job['id']);assert finished['status']=='succeeded',finished['error']
        saved=client.get('/api/production').json()['timelines'][0]
        assert saved['scenes'][3]['map_mode']=='forecast'
        body['presentation']='captioned'
        assert not client.post('/api/production/check',json=body).json()['ready']


def test_source_radar_frames_legend_and_forecast_geometry_are_pinned(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        a=synthetic_current(client)
        store=client.app.state.store
        buf=io.BytesIO();Image.new('RGBA',(64,64),(12,80,30,120)).save(buf,format='PNG');raw=buf.getvalue()
        legend=store.save_visual_asset({'kind':'radar_legend','source_url':'https://nowcoast.noaa.gov/legend','observed_at':a.issued_at.isoformat(),'content_type':'image/png','metadata':{}},raw)
        for i in range(2):
            stamp=(a.issued_at-timedelta(minutes=5-i)).isoformat()
            store.save_visual_asset({'kind':'radar','source_url':f'https://nowcoast.noaa.gov/frame/{i}','observed_at':stamp,'content_type':'image/png','metadata':{'projection':'EPSG:3857','extent':[-126,23,-65,51],'legend_asset_id':legend}},raw)
        geometry={'features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[[[-92,24],[-88,24],[-90,28],[-92,24]]]}}]}
        store.save_visual_asset({'kind':'forecast_cone','source_url':'https://www.nhc.noaa.gov/test.kmz','observed_at':a.issued_at.isoformat(),'content_type':'application/geo+json','metadata':{'advisory_id':a.id,'advisory_checksum':a.checksum,'forecast_valid_time':(a.issued_at+timedelta(hours=24)).isoformat()}},json.dumps(geometry).encode())
        script=client.post('/api/scripts',json={'advisory_id':a.id}).json()
        plan=client.post('/api/visuals/plans',json={'script_id':script['id'],'expected_revision':1}).json()
        body={'plan_id':plan['id'],'title':'Synthetic map layers','presentation':'broadcast','scenes':[{'id':s['id'],'seconds':1,'map_mode':'radar' if i==0 else 'forecast' if i==1 else 'auto'} for i,s in enumerate(plan['scenes'])]}
        result=client.post('/api/production/timelines',json=body);assert result.status_code==200,result.text
        scene=result.json()['scenes'][0]
        assert len(scene['parameters']['map_observations'])==2
        assert not scene['direction']['fallback']
        composer=Composer(scene['direction'],scene['parameters'],lambda id:client.app.state.production.map_asset(scene,id))
        assert composer.legend is not None and len(composer.sources)==2
        assert composer.frame(.5).size==(1920,1080)
        forecast=result.json()['scenes'][1]
        assert 'forecast_cone' in forecast['direction']['layers']
        assert forecast['parameters']['map_valid_time']
        Composer(forecast['direction'],forecast['parameters']).frame(.5)
        pinned=scene['parameters']['map_observations'][0]
        client.app.state.production.observation_path(pinned).write_bytes(b'changed')
        assert client.post('/api/production/renders',json={'timeline_id':result.json()['id']}).status_code==422
