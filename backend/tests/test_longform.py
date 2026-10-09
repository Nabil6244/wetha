import copy
import importlib.util
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.longform import blueprint,audit
from app.broadcast import Composer
from test_production import prepare,wait_render


def test_hour_blueprint_is_exact_with_chapter_questions_and_content_needs():
    p=blueprint([])
    assert p['seconds']==3600 and p['frames']==108000 and len(p['chapters'])==12
    assert sum(c['seconds'] for c in p['chapters'])==3600
    assert p['chapters'][-1]['start_seconds']+p['chapters'][-1]['seconds']==3600
    assert all(c['question'] and c['needs'] for c in p['chapters'])
    result=audit([],lambda _:None)
    assert not result['ready'] and result['seconds']==0
    assert len([i for i in result['issues'] if i['code']=='chapter_duration'])==12


def test_hour_cannot_be_filled_by_replaying_short_timeline_or_same_footage():
    t={'id':'short','seconds':60,'event_id':'AL092020','scenes':[
        {'type':'source_card','script_segment':'A short supported source passage','seconds':6,'graphic_style':'source_card'},
        {'type':'ground_footage','script_segment':'A distinct supported passage','seconds':6,'cuts':[{'media_id':'clip','trim_start':1,'seconds':3},{'media_id':'clip','trim_start':1,'seconds':3}]}]}
    r=audit([{'chapter_id':'hook','timeline_ids':['short']},{'chapter_id':'origins','timeline_ids':['short']}],lambda _:t)
    codes={i['code'] for i in r['issues']}
    assert {'repeated_timeline','repeated_clip','source_cooldown','short_script'}<=codes
    assert not r['ready'] and r['seconds']==12
    with pytest.raises(ValueError,match='Unknown chapter'):audit([{'chapter_id':'missing','timeline_ids':[]}],lambda _:t)


def test_hour_assembler_shifts_chapter_subtitles_without_rounding_drift():
    path=Path(__file__).resolve().parents[2]/'scripts/assemble-hour.py'
    spec=importlib.util.spec_from_file_location('hour_assembly_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cues=module.shifted_subtitles('1\n00:00:00,033 --> 00:00:04,100\nSource caption\n',3594)
    assert cues==['00:59:54,033 --> 00:59:58,100\nSource caption']
    with pytest.raises(ValueError,match='Reversed'):module.shifted_subtitles('1\n00:00:05,000 --> 00:00:04,000\nBad interval',0)


def test_motion_graphics_keep_source_claims_and_survive_save_reload(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _,plan,body=prepare(client);body['presentation']='broadcast'
        comparison=next(i for i,s in enumerate(plan['scenes']) if s['type']=='what_changed')
        body['scenes'][comparison]['graphic_style']='question_reveal'
        body['scenes'][0]['graphic_style']='source_card'
        r=client.post('/api/production/timelines',json=body);assert r.status_code==200,r.text
        timeline=r.json();scene=timeline['scenes'][comparison]
        assert scene['script_segment']==plan['scenes'][comparison]['script_segment']
        before=copy.deepcopy(scene['parameters'])
        composer=Composer(scene['direction'],scene['parameters']);first=composer.frame(.1);last=composer.frame(.9)
        assert first.tobytes()!=last.tobytes() and scene['parameters']==before
        saved=client.get('/api/production').json()['timelines'][0]
        assert saved['scenes'][comparison]['graphic_style']=='question_reveal'
        job=client.post('/api/production/renders',json={'timeline_id':timeline['id']}).json()
        assert wait_render(client,job['id'])['status']=='succeeded'
        assembler_path=Path(__file__).resolve().parents[2]/'scripts/assemble-hour.py'
        spec=importlib.util.spec_from_file_location('hour_collect_test',assembler_path)
        assembler=importlib.util.module_from_spec(spec);spec.loader.exec_module(assembler)
        with pytest.raises(ValueError,match='Hour content audit failed'):
            assembler.collect(tmp_path,[{'chapter_id':'hook','render_ids':[job['id']]}])
        bad=copy.deepcopy(body);bad['scenes'][0]['graphic_style']='change_gauge'
        assert not client.post('/api/production/check',json=bad).json()['ready']
        bad=copy.deepcopy(body);bad['scenes'][0]['graphic_style']='forecast_clock'
        assert not client.post('/api/production/check',json=bad).json()['ready']
        assert not client.post('/api/production/longform/check',json={'chapters':[{'chapter_id':'hook','timeline_ids':[timeline['id']]}]}).json()['ready']
