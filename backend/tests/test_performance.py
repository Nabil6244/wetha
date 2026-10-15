import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
from app import broadcast
from app.orchestrator import Orchestrator,STAGES


def test_repeated_submit_reuses_the_running_job():
    request={'plan_id':'plan','narration_id':'voice','title':'Test'}
    job={'id':'running','status':'running','request':request}
    store=SimpleNamespace(production_list=lambda kind:[job])
    engine=Orchestrator(store,SimpleNamespace(),None,None,None)
    assert engine.start(SimpleNamespace(model_dump=lambda:request))==job
    assert not engine.tasks


def test_progress_advances_inside_a_stage_without_rewriting_unchanged_status():
    engine=Orchestrator(None,None,None,None,None);engine.save=Mock()
    job={'stages':[{'key':key,'label':label,'status':'pending','detail':''} for key,label in STAGES]}
    engine.stage(job,'validate','done')
    engine.stage(job,'align','running','Listening · 50%',.5)
    assert job['progress']==17
    engine.stage(job,'align','running','Listening · 50%',.5)
    assert engine.save.call_count==2


def test_hardware_probe_failure_falls_back_and_probe_runs_once(monkeypatch):
    broadcast.encoder_args.cache_clear()
    run=Mock(side_effect=subprocess.CalledProcessError(1,['ffmpeg']))
    monkeypatch.setattr(broadcast.subprocess,'run',run)
    monkeypatch.setattr(broadcast.sys,'platform','darwin')
    try:
        assert broadcast.encoder_args('auto')[1]=='libx264'
        assert broadcast.encoder_args('auto')[1]=='libx264'
        assert run.call_count==1
        assert broadcast.encoder_args('software')[1]=='libx264'
    finally:
        broadcast.encoder_args.cache_clear()


def test_low_disk_space_stops_before_creating_a_render(tmp_path,monkeypatch):
    import pytest
    from app.production import Production
    service=object.__new__(Production)
    service.root=tmp_path;service.tasks={}
    service.store=SimpleNamespace(production_get=lambda *args:{})
    service.validate_timeline=lambda _:({'seconds':600},{})
    monkeypatch.setattr('app.production.shutil.disk_usage',lambda _:SimpleNamespace(free=10_000_000))
    with pytest.raises(ValueError,match='Settings → Storage'):
        service.new_render('timeline')
