from datetime import datetime, timezone
from types import SimpleNamespace
from app.preview_audit import audit, canonical
from app.report_graphs import prepare


def source(identity, area, text):
    return SimpleNamespace(id=identity, area=area, title='Warning', text=text, checksum='pinned',
        issued_at=datetime(2026,10,10,tzinfo=timezone.utc),provider='NWS')

def document(*texts):
    return {'advisory_id':'fl','selected_advisory_ids':['fl','al'],
            'claims':[{'id':str(i),'text':t,'status':'requires_verification'} for i,t in enumerate(texts)]}

def test_ranges_units_and_spoken_numbers_are_checked_without_human_attestation():
    evidence=[source('fl','Coastal Dixie Florida','Surge forecast 2-4 feet. Rain 1-3 inches.'), source('al','Montgomery, AL','Between 3 and 5 inches of rain have fallen.')]
    doc=document('Coastal Dixie Florida expects two to four feet of surge.', 'Now move into Alabama.', 'Montgomery saw three to five inches of rain.', 'Think about the rain already down.')
    result=audit(doc,evidence)
    assert result['ready']
    assert [r['primary_advisory_id'] for r in result['claims']]==['fl','al','al','al']
    assert all(c['status']=='requires_verification' for c in doc['claims'])
    assert result['human_review_required'] and result['mode']=='local_preview_only'
    assert not audit(document('Florida expects two to five feet of surge.'),evidence)['ready']
    assert not audit(document('Florida expects 4 inches of surge.'),evidence)['ready']
    assert not audit(document('Florida expects 99 feet of surge.'),evidence)['ready']
    assert not audit(document('Florida is guaranteed to flood.'),evidence)['ready']


def test_nws_charts_preserve_forecast_and_observed_ranges_and_do_not_replace_footage():
    a=source('al','Montgomery Alabama','Radar indicated between 3 and 5 inches of rain have fallen. Additional rainfall amounts of 1 to 2 inches are possible.')
    scene={'type':'cinematic_weather_map','parameters':{},'script_segment':'Three to five inches of rain had already fallen, with one to two inches of additional rain possible.'}
    data=prepare(scene,a)
    assert [c['range'] for c in data['charts']]==[[3,5],[1,2]]
    assert [c['qualifier'] for c in data['charts']]==['Already fallen','Additional possible']
    assert all(c['kind']=='range' and c['points'][0]['advisory_id']=='al' for c in data['charts'])
    scene['media_id']='footage'
    assert prepare(scene,a) is None


def test_shorter_visual_shots_conserve_audio_frames_and_keep_claims():
    from app.automatic_edit import subdivide, shot_frames
    for frames in range(30,3601):
        lengths=shot_frames(frames)
        assert sum(lengths)==frames and min(lengths)>=30 and max(lengths)<=120
    plan={'id':'old','scenes':[{'id':'scene','claim_id':'claim','script_segment':'The forecast rain could cause flooding across the warned area.','parameters':{'source_advisory_id':'al'}}]}
    job={'id':'speech','result':{'scenes':[{'id':'scene','seconds':5}],'coverage':.98,'timing_basis':'Recognized speech'}}
    new,derived,edits=subdivide(plan,job)
    assert new['parent_plan_id']=='old' and derived['parent_alignment_id']=='speech'
    assert sum(round(s['seconds']*30) for s in edits)==150
    assert ' '.join(s['script_segment'] for s in new['scenes'])==plan['scenes'][0]['script_segment']
    assert all(s['claim_id']=='claim' and s['parameters']['source_advisory_id']=='al' for s in new['scenes'])
    assert derived['result']['coverage']==.98
    assert 'editorial cuts' in derived['result']['timing_basis']


def test_prepare_reuses_completed_audio_match_without_manual_timing_or_checkbox(tmp_path):
    import io, wave
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_production import prepare as setup, upload
    from uuid import uuid4
    with TestClient(create_app(tmp_path)) as client:
        script,plan,body=setup(client)
        duration=len(plan['scenes'])*5
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*duration*16000)
        audio=upload(client,stream.getvalue(),name='prepared.wav',kind='audio',context='narration').json()
        identity=str(uuid4())
        job={'id':identity,'status':'completed','plan_id':plan['id'],'narration_id':audio['id'],
             'script_text_checksum':plan['script_text_checksum'],'audio_checksum':audio['checksum'],
             'result':{'scenes':[{'id':s['id'],'seconds':5,'media_id':None,'trim_start':0,'transition':'cut'} for s in plan['scenes']],
                       'coverage':.98,'timing_basis':'Recognized speech','issues':[]}}
        client.app.state.alignment.jobs[identity]=job
        body.update(narration_id=audio['id'],presentation='broadcast')
        response=client.post('/api/production/prepare',json=body)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['status']=='ready' and result['body']['narration_verified']
        assert result['plan']['automatic_shots']
        assert result['alignment']['parent_alignment_id']==identity
        assert result['check']['seconds']==duration
        timeline=client.post('/api/production/timelines',json=result['body'])
        assert timeline.status_code==200,timeline.text
        assert not timeline.json()['broadcast_eligible']
        assert client.app.state.store.script(script['id'])['text']==script['text']


def test_scene_reuse_requires_identical_snapshot_and_unchanged_encoded_checksum(tmp_path):
    import hashlib,copy
    from app.production import Production
    from pathlib import Path
    p=object.__new__(Production);p.root=tmp_path
    scene={'id':'s','seconds':4,'transition':'cut','parameters':{'source_advisory_id':'al'}}
    snapshot={'presentation':'broadcast','source_label':'expired','scenes':[scene]}
    old={'id':'old','renderer_version':15,'snapshot':snapshot,'cache':{'0':hashlib.sha256(b'encoded').hexdigest()}}
    p.store=SimpleNamespace(production_list=lambda _: [old])
    directory=tmp_path/'renders'/'old';directory.mkdir(parents=True);(directory/'scene-000.mp4').write_bytes(b'encoded')
    new={'id':'new','renderer_version':15,'snapshot':copy.deepcopy(snapshot),'cache':{}}
    p.reuse_scene_cache(new);assert new['reused_scenes']==1
    new['id']='changed';new['cache']={};new['snapshot']['scenes'][0]['parameters']['source_advisory_id']='fl'
    p.reuse_scene_cache(new);assert new['reused_scenes']==0
    new['snapshot']=copy.deepcopy(snapshot);(directory/'scene-000.mp4').write_bytes(b'corrupt')
    p.reuse_scene_cache(new);assert new['reused_scenes']==0


def test_mixed_edit_strips_snapshot_metadata_from_existing_footage_requests():
    from app.bulletin_edit import draft
    scene={'id':'scene','seconds':6,'media_id':None,'trim_start':0,'transition':'cut','cuts':[{'media_id':'clip','seconds':3,'trim_start':0,'selection_catalog':{'location':'pinned'}},{'media_id':'clip','seconds':3,'trim_start':3,'selection_catalog':{}}],
           'map_mode':'auto','graphic_style':'auto','regional_focus':'auto','type':'cinematic_weather_map','parameters':{}}
    result=draft({'scenes':[scene]},[],lambda _:None)
    assert all(set(c)=={'media_id','seconds','trim_start'} for c in result['scenes'][0]['cuts'])
    assert scene['cuts'][0]['selection_catalog']=={'location':'pinned'}


def test_query_tags_cannot_promote_nasa_space_launch_into_weather_footage():
    from app.media_selection import rank
    scene={'script_segment':'Waves and storm surge threaten boats.','parameters':{}}
    asset={'id':'launch','name':'Science_Launching_on_SpaceX_CRS-29.mp4','kind':'video','rights_confirmed':True,'source':'https://images.nasa.gov/details/Science_Launching_on_SpaceX_CRS-29','seconds':50,'catalog':{'tags':['waves']},'context':'archival','attribution':'NASA'}
    assert rank(scene,[asset],SimpleNamespace(event_key='storm'))==[]
