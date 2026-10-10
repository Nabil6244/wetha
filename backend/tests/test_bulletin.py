"""Connected bulletins preserve per-topic provenance without padding narration."""
import re
import hashlib
from fastapi.testclient import TestClient
from app.main import create_app


def load_sources(client):
    client.post('/api/training/load')
    store=client.app.state.store
    item=store.advisory('training:cyclone:1')
    text='Synthetic flood fixture. Flood conditions are described for testing only.'
    store.save_advisory(item.model_copy(update={'id':'training:flood:1','event_key':'training:flood','title':'Training Flood','facts':{},'text':text,'checksum':hashlib.sha256(text.encode()).hexdigest()}))


def build(client, minutes=60):
    load_sources(client)
    return client.post('/api/newsroom/runs',json={'advisory_id':'training:cyclone:2','advisory_ids':['training:cyclone:2','training:flood:1'],'bulletin':True,'target_minutes':minutes})


def test_connected_order_sources_and_honest_length(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response=build(client)
        assert response.status_code==200,response.text
        s=response.json()
        assert s['selected_advisory_ids']==['training:cyclone:2','training:flood:1']
        assert 'We begin with' in s['text'] and 'Our final report covers' in s['text']
        assert s['text'].index('We begin with')<s['text'].index('Our final report covers')
        assert s['text'].count('That completes this weather bulletin.')==1
        assert s['bulletin']['target_minutes']==60 and s['bulletin']['coverage']=='needs_more_material'
        assert s['bulletin']['word_count']==len(s['text'].split())
        assert s['estimated_seconds']<3600
        assert len({c['id'] for c in s['claims']})==len(s['claims'])
        assert all(c['status']=='generated_grounded' for c in s['claims'])
        plan=client.post('/api/visuals/plans',json={'script_id':s['id'],'expected_revision':s['revision']})
        assert plan.status_code==200,plan.text
        assert ' '.join(re.split(r'\s+',s['text']))==' '.join(' '.join(p['script_segment'].split()) for p in plan.json()['scenes'])
        for scene in plan.json()['scenes']:
            claim=next(c for c in s['claims'] if c['id']==scene['claim_id'])
            assert scene['parameters']['source_advisory_id']==claim['primary_advisory_id']
        # Human free edits cannot silently inherit source verification.
        edit=client.post(f"/api/scripts/{s['id']}/revisions",json={'expected_revision':1,'text':s['text']+'\n\nA new unsupported statement about a storm.', 'editor':'Test editor','note':'Edit narration'}).json()
        assert edit['bulletin']['word_count']==len(edit['text'].split())
        assert edit['bulletin']['remaining_words']==60*145-len(edit['text'].split())
        assert edit['claims'][-1]['status']=='requires_verification'


def test_long_source_is_split_into_source_bound_visual_beats(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        load_sources(client)
        store=client.app.state.store
        a=store.advisory('training:flood:1')
        text=('Synthetic flood source detail. '*400).strip()
        a=a.model_copy(update={'id':'training:longflood:1','event_key':'training:longflood','text':text,'checksum':hashlib.sha256(text.encode()).hexdigest()})
        store.save_advisory(a)
        s=client.post('/api/newsroom/runs',json={'advisory_id':a.id,'bulletin':True,'target_minutes':20}).json()
        p=client.post('/api/visuals/plans',json={'script_id':s['id'],'expected_revision':1}).json()
        assert len(p['scenes'])>len(s['claims'])
        assert all(scene['target_seconds']<=8 for scene in p['scenes'])
        assert all(scene['parameters']['source_advisory_id']==a.id for scene in p['scenes'])
        assert ' '.join(s['text'].split())==' '.join(' '.join(scene['script_segment'].split()) for scene in p['scenes'])
        body={'plan_id':p['id'],'title':'Long synthetic program','presentation':'broadcast','scenes':[{'id':scene['id'],'seconds':10,'transition':'cut'} for scene in p['scenes']]}
        result=client.post('/api/production/timelines',json=body)
        assert result.status_code==200,result.text
        assert result.json()['seconds']>600


def test_thirty_minute_material_has_capacity_for_short_maps_without_padding(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        load_sources(client);store=client.app.state.store
        original=store.advisory('training:flood:1')
        text=' '.join(f'Synthetic source detail {i}.' for i in range(1100))
        a=original.model_copy(update={'id':'training:thirty:1','event_key':'training:thirty','text':text,'checksum':hashlib.sha256(text.encode()).hexdigest()})
        store.save_advisory(a)
        s=client.post('/api/newsroom/runs',json={'advisory_id':a.id,'bulletin':True,'target_minutes':30}).json()
        p=client.post('/api/visuals/plans',json={'script_id':s['id'],'expected_revision':1}).json()
        assert 180<len(p['scenes'])<=600
        assert all(scene['target_seconds']<=8 for scene in p['scenes'])
        assert ' '.join(s['text'].split())==' '.join(' '.join(scene['script_segment'].split()) for scene in p['scenes'])
        assert all('source_claim_text' in scene for scene in p['scenes'] if len(scene['script_segment'].split())==18)
        body={'plan_id':p['id'],'title':'Synthetic 30-minute capacity','presentation':'broadcast',
              'scenes':[{'id':scene['id'],'seconds':1800/len(p['scenes']),'transition':'cut'} for scene in p['scenes']]}
        checked=client.post('/api/production/check',json=body)
        assert checked.status_code==200,checked.text
        assert not checked.json()['ready'] # Footage is still absent; capacity alone is not a final edit.
        assert not any(i['code']=='map_hold_limit' for i in checked.json()['issues'])


def test_multi_paragraph_alert_and_forecast_keep_correct_source_scenes(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        load_sources(client)
        store=client.app.state.store
        a=store.advisory('training:flood:1')
        text='Synthetic alert introduction.\n\nSynthetic regional flood details.\n\nSynthetic emergency guidance.'
        multi=a.model_copy(update={'id':'training:paragraph-alert:1','event_key':'training:paragraph-alert','text':text,'checksum':hashlib.sha256(text.encode()).hexdigest()})
        store.save_advisory(multi)
        cyclone=store.advisory('training:cyclone:2')
        forecast='Synthetic forecast paragraph one.\n\nSynthetic forecast paragraph two.'
        hurricane=cyclone.model_copy(update={'id':'training:paragraph-forecast:1','event_key':'training:paragraph-forecast','provider':'NHC','provenance':'synthetic_fixture','forecast_excerpt':forecast})
        store.save_advisory(hurricane)
        for ids in ([multi.id],[multi.id,hurricane.id],[hurricane.id,multi.id]):
            response=client.post('/api/newsroom/runs',json={'advisory_id':ids[0],'advisory_ids':ids,'bulletin':True,'target_minutes':10})
            assert response.status_code==200,response.text
            script=response.json()
            assert 'Synthetic regional flood details.' in script['text']
            if hurricane.id in ids:
                assert 'Synthetic forecast paragraph two.' in script['text']
            assert all(c['status']=='generated_grounded' for c in script['claims'])
            plan=client.post('/api/visuals/plans',json={'script_id':script['id'],'expected_revision':1})
            assert plan.status_code==200,plan.text
            for scene in plan.json()['scenes']:
                claim=next(c for c in script['claims'] if c['id']==scene['claim_id'])
                assert scene['parameters']['source_advisory_id']==claim['primary_advisory_id']
