from fastapi.testclient import TestClient
from app.main import create_app
from app.broadcast import Composer, map_point
from test_production import prepare


def test_story_keeps_source_claims_and_revision_gate(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        script, plan, body = prepare(client)
        response=client.post('/api/production/story',json={'plan_id':plan['id']})
        assert response.status_code==200,response.text
        story=response.json()
        assert story['story_review_required'] and not story['review_valid_at_creation']
        assert story['scenes'][0]['story_beat']=='hook'
        assert {s['claim_id'] for s in story['scenes']}=={s['claim_id'] for s in plan['scenes']}
        originals={s['claim_id']:s['script_segment'] for s in plan['scenes']}
        assert all(s['source_claim_text']==originals[s['claim_id']] for s in story['scenes'])
        assert all(s['parameters']['story']['source_label']=='training' for s in story['scenes'])
        assert client.post('/api/production/story',json={'plan_id':story['id']}).status_code==422
        body.update(plan_id=story['id'],presentation='broadcast',scenes=[{'id':s['id'],'seconds':3} for s in story['scenes']])
        timeline=client.post('/api/production/timelines',json=body)
        assert timeline.status_code==200,timeline.text
        assert not timeline.json()['broadcast_eligible']
        # An edit invalidates the revision binding of the derived storyboard too.
        edited=client.post(f"/api/scripts/{script['id']}/revisions",json={'expected_revision':1,'editor':'Test editor','note':'Test revision invalidation','text':script['text']+'\nAdditional editorial wording.'})
        assert edited.status_code==200,edited.text
        assert client.post('/api/production/story',json={'plan_id':plan['id']}).status_code==409


def test_map_auto_frames_source_positions_outside_old_default():
    from app.broadcast import SceneDirection
    direction=SceneDirection(scene_type='storm_track',event_id='TEST',duration=3,headline='SOURCE POSITIONS').model_dump(mode='json')
    params={'geojson':{'features':[{'geometry':{'type':'Point','coordinates':[-91.2,23.3]},'properties':{'issued_at':'2026-10-08T09:00:00Z'}}]}}
    composer=Composer(direction,params)
    x,y=map_point((-91.2,23.3),composer.bounds)
    assert 100<x<1820 and 250<y<820
    frame=composer.frame(.5)
    assert frame.size==(1920,1080)


def test_forecast_with_latitude_remains_forecast_and_warning_keeps_its_type():
    from types import SimpleNamespace
    from datetime import datetime,timezone
    from app.story import build
    advisory=SimpleNamespace(facts={'latitude':23.7,'longitude':-90.6,'wind_mph':80},title='Example storm',provider='NHC',issued_at=datetime(2026,10,8,tzinfo=timezone.utc),warnings=['A Hurricane Warning is in effect for: Example Coast'],forecast_excerpt='The center is near latitude 23.7 North. A turn northeast is expected later today.')
    texts=['Source introduction','Official watch and warning coverage: Example Coast','Official forecast guidance, quoted from this advisory: near latitude 23.7 North.','Follow official guidance.']
    plan={'id':'original','source_label':'historical','scenes':[{'id':str(i),'type':'storm_track' if i==2 else 'lower_third','parameters':{},'script_segment':t} for i,t in enumerate(texts)]}
    story=build(plan,advisory)
    assert story['scenes'][2]['story_beat']=='question'
    assert 'A turn northeast is expected later today.' in story['scenes'][2]['script_segment']
    assert 'Hurricane Warning' in story['scenes'][1]['script_segment']
    assert 'storm surge' not in story['scenes'][1]['script_segment']
