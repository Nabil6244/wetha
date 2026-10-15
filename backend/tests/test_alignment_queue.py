"""A busy speech engine must not fail a video job or silently claim word timing."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.alignment import AlignmentBusy, AlignmentJobs
from app.orchestrator import Orchestrator


def test_busy_alignment_identifies_the_job_to_wait_for():
    service=object.__new__(AlignmentJobs)
    service.lock=threading.Lock()
    service.jobs={'first':{'id':'first','plan_id':'old','narration_id':'other','status':'running'}}
    service.production=SimpleNamespace(
        store=SimpleNamespace(visual_plan=lambda _: {},production_list=lambda _: [{'id':'voice','kind':'audio'}]),
        validate_plan=lambda *args,**kwargs: None,media_path=lambda _: 'local-audio')
    with pytest.raises(AlignmentBusy) as caught:
        service.start('new','voice')
    assert caught.value.job_id=='first'
    assert list(service.jobs)==['first']


def orchestration(prepare):
    engine=object.__new__(Orchestrator)
    engine.prepare=prepare
    engine.alignment=SimpleNamespace(get=Mock(return_value={'status':'completed'}))
    engine.stage=Mock()
    body={'plan_id':'plan','title':'Weather bulletin','narration_id':'voice','scenes':[{'id':'scene','seconds':4}]}
    job={'request':{},'issues':[]}
    return engine,body,job


def test_unconfirmed_job_waits_and_retries_after_the_other_recording(monkeypatch):
    monkeypatch.setattr('app.orchestrator.POLL',.001)
    prepare=Mock(side_effect=[AlignmentBusy('first'),{'status':'ready'}])
    engine,body,job=orchestration(prepare)
    assert asyncio.run(engine.prepared(job,body))=={'status':'ready'}
    assert prepare.call_count==2
    engine.alignment.get.assert_called_with('first')
    assert not job['issues']
    assert 'Waiting' in engine.stage.call_args_list[0].args[-1]


def test_confirmed_fitted_timing_uses_the_fast_path_instead_of_failing():
    prepare=Mock(side_effect=[AlignmentBusy('first'),{'status':'ready'}])
    engine,body,job=orchestration(prepare)
    body['narration_verified']=True
    job['request']={'scenes':body['scenes'],'narration_verified':True}
    assert asyncio.run(engine.prepared(job,body))=={'status':'ready'}
    assert prepare.call_args_list[1].args[-1] is False
    assert job['issues'][0]['code']=='timing_fallback'
    assert 'word-level alignment was not applied' in job['issues'][0]['message']
    engine.alignment.get.assert_not_called()


def test_validation_errors_are_not_treated_as_a_busy_engine():
    engine,body,job=orchestration(Mock(side_effect=ValueError('Audio does not match the script')))
    with pytest.raises(ValueError,match='does not match'):
        asyncio.run(engine.prepared(job,body))


def test_replanning_after_observation_collection_keeps_fitted_timing():
    prepare=Mock(return_value={'status':'ready'})
    engine,body,job=orchestration(prepare)
    job['issues']=[{'code':'timing_fallback','message':'Already confirmed fitted timing'}]
    assert asyncio.run(engine.prepared(job,body))=={'status':'ready'}
    prepare.assert_called_once()
    assert prepare.call_args.args[-1] is False
