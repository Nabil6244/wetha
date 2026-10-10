import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import create_app
from app.report_graphs import prepare, draw
from app.broadcast import map_base
from test_production import prepare as prepare_report, upload


def sample():
    advisory = SimpleNamespace(id='test:2',title='Synthetic storm',issued_at=datetime(2026,1,1,12,tzinfo=timezone.utc))
    scene = {'type':'what_changed','parameters':{'facts':{'wind_mph':80,'pressure_mb':975},'geojson':{'features':[
        {'properties':{'kind':'reported_center','advisory_id':'test:1','issued_at':'2026-01-01T09:00:00+00:00','wind_mph':70,'pressure_mb':979}},
        {'properties':{'kind':'forecast_point','advisory_id':'test:2','issued_at':'2026-01-02T09:00:00+00:00','wind_mph':110,'pressure_mb':950}}]}}}
    return scene, advisory


def test_graph_values_times_and_units_are_pinned_observations(tmp_path):
    scene, advisory = sample();before=copy.deepcopy(scene)
    data=prepare(scene,advisory)
    assert [[p['value'] for p in c['points']] for c in data['charts']]==[[70,80],[979,975]]
    assert [c['unit'] for c in data['charts']]==['mph','mb']
    assert data['charts'][0]['points'][0]['issued_at']=='2026-01-01T09:00:00+00:00'
    first=map_base((-98,16,-78,33)).copy();last=first.copy()
    draw(first,data,0);draw(last,data,1)
    assert first.tobytes()!=last.tobytes()
    assert scene==before
    # A missing previous record must not manufacture a flat trend.
    scene['parameters']['geojson']['features']=[]
    assert all(c['kind']=='measurement' for c in prepare(scene,advisory)['charts'])
    scene['parameters']['facts']={}
    assert prepare(scene,advisory) is None


def test_default_graphs_persist_and_do_not_replace_footage_or_explicit_maps(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _,_,body=prepare_report(client);body['presentation']='broadcast'
        timeline=client.post('/api/production/timelines',json=body).json()
        assert timeline['automatic_graphs'] is True
        graphs=[s for s in timeline['scenes'] if s['parameters'].get('report_graphs')]
        assert graphs
        for scene in graphs:
            assert scene['parameters']['report_graphs']['source_advisory_id']==scene['parameters']['source_advisory_id']
        media=upload(client).json()
        target=next(s for s in body['scenes'] if s['id']==graphs[0]['id'])
        target['media_id']=media['id']
        edited=client.post('/api/production/timelines',json=body).json()
        assert not next(s for s in edited['scenes'] if s['id']==target['id'])['parameters'].get('report_graphs')
        body['automatic_graphs']=False
        legacy=client.post('/api/production/timelines',json=body).json()
        assert not any(s['parameters'].get('report_graphs') for s in legacy['scenes'])


def test_current_measurement_treatment_differs_from_update_trend():
    scene, advisory = sample()
    scene['type']='storm_track'
    scene['script_segment']='The advisory reports maximum sustained winds and central pressure.'
    scene['parameters']['facts']['movement_mph']=9
    current=prepare(scene,advisory)
    assert current['charts'][0]['bars']==[{'label':'Sustained wind','value':80},{'label':'Storm motion','value':9}]
    assert all(len(c['points'])==1 for c in current['charts'])
    scene['type']='what_changed'
    update=prepare(scene,advisory)
    assert len(update['charts'][0]['points'])==2
    assert 'bars' not in update['charts'][0]
