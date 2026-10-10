import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.alignment import align
from test_bulletin import build, load_sources


def test_polished_source_mapping_preserves_sources_and_does_not_attest_paraphrases(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        load_sources(client);s=build(client).json()
        root=f"/api/scripts/{s['id']}"
        pack=client.get(root+'/source-pack').json()
        assert len(pack['sources'])==2 and all(a['checksum'] for a in pack['sources'])
        text='Florida residents should check the hurricane report before making plans.\n\nThe flood report describes a different affected area and its official guidance.'
        mapped=client.post(root+'/source-map',json={'text':text}).json()
        assert len(mapped['paragraphs'])==2
        body={'expected_revision':1,'text':text,'editor':'Test editor','sources':['training:cyclone:2','training:flood:1']}
        saved=client.post(root+'/polished',json=body)
        assert saved.status_code==200,saved.text
        saved=saved.json()
        assert saved['revision']==2 and all(c['status']=='requires_verification' for c in saved['claims'])
        assert [c['primary_advisory_id'] for c in saved['claims']]==body['sources']
        assert saved['evidence_manifest']==s['evidence_manifest']
        assert not saved['editorial']['can_review']
        assert not any(i['code']=='missing_context' for i in saved['editorial']['issues'])
        plan=client.post('/api/visuals/plans',json={'script_id':s['id'],'expected_revision':2}).json()
        assert [row['parameters']['source_advisory_id'] for row in plan['scenes']]==body['sources']
        assert client.get(root+'/source-pack').json()==pack
        body.update(expected_revision=2,text=text+' Changed.',sources=['unknown','training:flood:1'])
        assert client.post(root+'/polished',json=body).status_code==422
        assert client.get(root).json()['revision']==2


def test_alignment_uses_spoken_boundary_and_exact_audio_frames():
    plan={'scenes':[{'id':'a','script_segment':'Florida rain is heavy today'}, {'id':'b','script_segment':'Alabama winds are strong tonight'}]}
    words=[{'word':w,'start':t,'end':t+.5} for w,t in zip('Florida rain is heavy today Alabama winds are strong tonight'.split(),[1,2,3,4,5,7.2,8,9,10,11])]
    result=align(plan,words,13.23)
    assert result['coverage']==1
    assert result['scenes'][0]['seconds']==7.2
    assert sum(round(s['seconds']*30) for s in result['scenes'])==round(13.23*30)
    assert all(s['transition']=='cut' for s in result['scenes'])
    with pytest.raises(ValueError,match='match the recording'):
        align(plan,[{'word':'completely different audio','start':0,'end':3}],13)


def test_alignment_rejects_whole_missing_scene_even_with_high_overall_match():
    long=' '.join(f'word{i}' for i in range(100))
    plan={'scenes':[{'id':'a','script_segment':long},{'id':'b','script_segment':'missing phrase entirely unseen'},{'id':'c','script_segment':long}]}
    text=long+' '+long
    words=[{'word':w,'start':i*.1,'end':i*.1+.1} for i,w in enumerate(text.split())]
    with pytest.raises(ValueError):align(plan,words,21)


def test_alignment_job_binds_timing_to_plan_audio_and_survives_restart(tmp_path, monkeypatch):
    import io, time, wave, sys
    from types import SimpleNamespace
    from app.alignment import tokens, AlignmentJobs
    from test_production import prepare, upload
    def fake_model(*args,**kwargs):
        class Model:
            def transcribe(self,*args,**kwargs):
                return iter([SimpleNamespace(end=seconds,words=recognized)]),None
        return Model()
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=fake_model))
    with TestClient(create_app(tmp_path)) as client:
        _,plan,body=prepare(client)
        seconds=len(plan['scenes'])*4
        recognized=[]
        for i,scene in enumerate(plan['scenes']):
            parts=tokens(scene['script_segment'])
            recognized.extend(SimpleNamespace(word=w,start=i*4+j*3.8/len(parts),end=i*4+(j+1)*3.8/len(parts)) for j,w in enumerate(parts))
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*seconds*16000)
        audio=upload(client,stream.getvalue(),name='alignment.wav',kind='audio',context='narration').json()
        job=client.post('/api/production/alignment',json={'plan_id':plan['id'],'narration_id':audio['id']})
        assert job.status_code==200,job.text
        identity=job.json()['id']
        for _ in range(100):
            status=client.get('/api/production/alignment/'+identity).json()
            if status['status'] in ('completed','failed'):break
            time.sleep(.01)
        assert status['status']=='completed',status
        result=status['result'];assert result['coverage']==1
        body.update(scenes=result['scenes'],alignment_id=identity,narration_id=audio['id'],narration_verified=True)
        saved=client.post('/api/production/timelines',json=body)
        assert saved.status_code==200,saved.text
        assert saved.json()['alignment_id']==identity
        assert 'recognized word timestamps' in saved.json()['timing_basis']
        assert AlignmentJobs(client.app.state.production).get(identity)['result']==result
        body['scenes'][0]['seconds']+=.1;body['scenes'][1]['seconds']-=.1
        invalid=client.post('/api/production/timelines',json=body)
        assert invalid.status_code==422 and 'durations changed' in invalid.text
        assert client.get('/api/production/alignment/../../studio.sqlite3').status_code!=200
