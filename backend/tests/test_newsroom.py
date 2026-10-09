"""Newsroom acceptance tests; synthetic scenarios plus unchanged official captures."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.fixtures import training_advisories
from app.collector import parse_nhc_feed
from app.models import compose
from app.storage import Store


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def current(client):
    # Synthetic fixture advertised as official inside a unit test only, never production data.
    item = training_advisories()[0].model_copy(update={
        'id':'synthetic-current', 'provider':'NHC', 'provenance':'official_fetch',
        'issued_at':datetime.now(timezone.utc) - timedelta(minutes=5),
        'text':'SYNTHETIC TEST SOURCE. Maximum sustained winds are 85 mph. Minimum central pressure is 975 mb. This is not a real observation.'})
    client.app.state.store.save_advisory(item)
    return item


def draft(client, item):
    result = client.post('/api/newsroom/runs', json={'advisory_id':item.id})
    assert result.status_code == 200, result.text
    return result.json()


def edit(client, document, text):
    return client.post(f"/api/scripts/{document['id']}/revisions", json={
        'expected_revision':document['revision'], 'text':text, 'editor':'Test editor', 'note':'Acceptance test change'})


def test_six_roles_preserve_structured_handoffs_and_source_identity(client):
    item = current(client)
    document = draft(client, item)
    run = client.get('/api/newsroom/runs/' + document['run_id']).json()
    assert run['status'] == 'succeeded' and run['script_id'] == document['id']
    assert [step['agent'] for step in run['steps']] == ['Data collector','Change detector','News prioritizer','Fact verifier','Scriptwriter','Editorial controller']
    assert all(step['status'] == 'succeeded' and step['output']['schema_version'] == '1' and step['finished_at'] for step in run['steps'])
    manifest = run['steps'][3]['output']['evidence_manifest']
    assert manifest[0]['checksum'] == item.checksum
    assert document['claims'] and all(claim['status'] == 'generated_grounded' for claim in document['claims'])
    assert document['editorial']['can_review'] is True
    assert document['review_valid'] is False and document['broadcast_eligible'] is False
    assert document['versions'][0]['revision'] == 1
    assert client.get('/api/dashboard').json()['newsroom']['runs'][0]['id'] == run['id']


def test_official_captured_forecast_and_comparison_remain_exact(client):
    fixtures=Path(__file__).parent/'fixtures'
    earlier,_=parse_nhc_feed((fixtures/'nhc-atlantic-2026-10-08.xml').read_text())
    later,_=parse_nhc_feed((fixtures/'nhc-atlantic-2026-10-08-0300.xml').read_text())
    for item in earlier+later:
        client.app.state.store.save_advisory(item)
    document=draft(client,later[0])
    assert '65 to 70 mph' in document['text'] and '994 to 988 mb' in document['text']
    assert later[0].forecast_excerpt in document['text']
    assert all(claim['status']=='generated_grounded' for claim in document['claims'])
    assert all(item['checksum'] for item in document['evidence_manifest'])
    assert len(document['source_advisory_ids'])==2


def test_review_is_tied_to_revision_and_edits_preserve_history(client):
    item=current(client);document=draft(client,item)
    result=client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test reviewer','expected_revision':1,'note':'Checked source uncertainty'})
    assert result.status_code==200 and result.json()['review_valid']
    # Whitespace is not a new factual claim, but a new revision still clears approval.
    result=edit(client,document,document['text'].replace('According to','According  to'))
    assert result.status_code==200
    updated=result.json()
    assert updated['revision']==2 and updated['review_valid'] is False
    assert updated['status']=='needs_review'
    original=client.get(f"/api/scripts/{document['id']}?revision=1").json()
    assert original['text']==document['text'] and original['is_latest'] is False
    assert original['editorial']['can_review'] is False
    assert len(updated['reviews'])==1 and updated['reviews'][0]['revision']==1
    assert len(updated['versions'])==2
    csv=client.get(f"/api/scripts/{document['id']}/scenes.csv?revision=2").text
    assert 'According  to' in csv and 'claim_id' in csv


def test_unsupported_edit_cannot_reuse_prior_approval(client):
    document=draft(client,current(client))
    client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test reviewer'})
    updated=edit(client,document,document['text']+'\n\nThe storm will make landfall tomorrow with 200 mph winds.').json()
    assert updated['editorial']['can_review'] is False
    assert any(issue['code']=='unsupported_claim' and issue['blocking'] for issue in updated['editorial']['issues'])
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test reviewer','expected_revision':2}).status_code==409


def test_named_quote_attestation_requires_actual_source_and_numeric_support(client):
    document=draft(client,current(client))
    updated=edit(client,document,document['text']+'\n\nThe reported wind speed is 85 mph.').json()
    claim=updated['claims'][-1]
    body={'expected_revision':2,'claim_id':claim['id'],'advisory_id':document['advisory_id'],
        'quote':'Maximum sustained winds are 85 mph.','explanation':'This sentence reports the same maximum wind measurement.','reviewer':'Source checker'}
    path=f"/api/scripts/{document['id']}/claims/support"
    assert client.post(path,json={**body,'quote':'Maximum sustained winds are 200 mph.'}).status_code==422
    assert client.post(path,json={**body,'advisory_id':'not-in-package'}).status_code==422
    result=client.post(path,json=body)
    assert result.status_code==200
    supported=result.json()
    assert supported['revision']==3 and supported['claims'][-1]['status']=='human_attested'
    assert supported['claims'][-1]['support']['reviewer']=='Source checker'
    assert supported['editorial']['can_review'] is True
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Final editor','expected_revision':3}).json()['review_valid']
    changed=edit(client,supported,supported['text'].replace('reported wind speed is 85','reported wind speed is 200')).json()
    assert changed['claims'][-1]['status']=='requires_verification'
    assert client.post(path,json={**body,'expected_revision':4,'claim_id':changed['claims'][-1]['id']}).status_code==422


def test_direct_source_quotation_and_concurrent_revision_protection(client):
    item=current(client);document=draft(client,item)
    result=edit(client,document,document['text']+'\n\nMaximum sustained winds are 85 mph.')
    assert result.status_code==200
    assert result.json()['claims'][-1]['status']=='source_quote'
    assert edit(client,document,document['text']+'\n\nA concurrent change.').status_code==409
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test editor','expected_revision':1}).status_code==409
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test editor'}).status_code==409
    assert client.get(f"/api/scripts/{document['id']}").json()['revision']==2


def test_opening_context_cannot_be_removed_and_blank_names_fail(client):
    document=draft(client,current(client))
    result=edit(client,document,'\n\n'.join(document['text'].split('\n\n')[1:])).json()
    assert any(issue['code']=='missing_context' and issue['blocking'] for issue in result['editorial']['issues'])
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'   ','expected_revision':2}).status_code==422
    assert client.post(f"/api/scripts/{document['id']}/revisions",json={'expected_revision':2,'text':result['text'],'editor':'  ','note':'Test note'}).status_code==422


def test_source_update_invalidates_review_without_erasing_it(client):
    item=current(client);document=draft(client,item)
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test reviewer'}).json()['review_valid']
    client.app.state.store.save_advisory(item.model_copy(update={'id':'newer-synthetic', 'issued_at':datetime.now(timezone.utc)}))
    shown=client.get(f"/api/scripts/{document['id']}").json()
    assert shown['status']=='review_invalidated' and shown['review_valid'] is False
    assert shown['label']=='superseded' and len(shown['reviews'])==1
    assert shown['broadcast_eligible'] is False


def test_source_checksums_are_revalidated_at_review(client):
    document=draft(client,current(client))
    # Corrupt the stored manifest as a simulation of database corruption, not through an API.
    stored=client.app.state.store.script(document['id'])
    stored['evidence_manifest'][0]['checksum']='bad-checksum'
    with client.app.state.store.connection() as conn:
        conn.execute('UPDATE scripts SET document=? WHERE id=?',(json.dumps(stored),document['id']))
    assert client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test reviewer'}).status_code==409


def test_unconfigured_model_failure_records_stage_without_partial_script(client,monkeypatch):
    monkeypatch.delenv('WETHA_OLLAMA_MODEL',raising=False)
    item=current(client)
    response=client.post('/api/newsroom/runs',json={'advisory_id':item.id,'engine':'ollama'})
    assert response.status_code==422
    state=client.get('/api/newsroom').json();run=client.get('/api/newsroom/runs/'+state['runs'][0]['id']).json()
    assert run['status']=='failed' and run['script_id'] is None
    assert run['steps'][-1]['agent']=='Scriptwriter' and run['steps'][-1]['status']=='failed'
    assert client.get('/api/dashboard').json()['stats']['scripts']==0
    assert client.post('/api/newsroom/runs',json={'advisory_id':'missing'}).status_code==404
    assert len(client.get('/api/newsroom').json()['runs'])==1


def test_model_composition_uses_catalogue_without_new_claims(tmp_path,monkeypatch):
    monkeypatch.setenv('WETHA_OLLAMA_MODEL','test-model')
    def respond(request):
        assert str(request.url)=='http://127.0.0.1:11434/api/chat'
        payload=json.loads(request.content);blocks=json.loads(payload['messages'][0]['content'])['blocks']
        ids=[block['id'] for block in blocks]
        return httpx.Response(200,json={'message':{'content':json.dumps({'order':[ids[0],*reversed(ids[1:-1]),ids[-1]]})}})
    with TestClient(create_app(tmp_path,model_transport=httpx.MockTransport(respond))) as client:
        item=current(client)
        result=client.post('/api/newsroom/runs',json={'advisory_id':item.id,'engine':'ollama'})
        assert result.status_code==200,result.text
        doc=result.json()
        assert doc['engine']=='ollama-grounded-composition-v1' and doc['editorial']['can_review']
        assert all(claim['status']=='generated_grounded' for claim in doc['claims'])


@pytest.mark.parametrize('output', [
    {'order':['first','invented','last']},
    {'order':['first','middle','last'],'text':'The hurricane will hit tomorrow.'},
    {'order':['first','middle','middle','last']},
    {'order':['middle','first','last']},
])
def test_model_cannot_inject_or_drop_or_duplicate_context(output,monkeypatch):
    monkeypatch.setenv('WETHA_OLLAMA_MODEL','test-model')
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':json.dumps(output)}}))
    with pytest.raises(ValueError):
        asyncio.run(compose('ollama',[{'id':value,'text':value} for value in ['first','middle','last']],transport))


def test_gemini_contract_and_secret_redaction(tmp_path,monkeypatch):
    monkeypatch.setenv('WETHA_GEMINI_MODEL','test-model')
    monkeypatch.setenv('WETHA_GEMINI_API_KEY','test-secret-not-real')
    def respond(request):
        assert request.url.host=='generativelanguage.googleapis.com'
        assert request.headers['x-goog-api-key']=='test-secret-not-real'
        assert 'test-secret-not-real' not in str(request.url)
        blocks=json.loads(json.loads(request.content)['contents'][0]['parts'][0]['text'])['blocks']
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':json.dumps({'order':[block['id'] for block in blocks]})}]}}]})
    with TestClient(create_app(tmp_path,model_transport=httpx.MockTransport(respond))) as client:
        document=client.post('/api/newsroom/runs',json={'advisory_id':current(client).id,'engine':'gemini'}).json()
        assert document['engine']=='gemini-grounded-composition-v1'
        run=client.get('/api/newsroom/runs/'+document['run_id']).text
        assert 'test-secret-not-real' not in run and 'test-secret-not-real' not in client.get('/api/newsroom').text


def test_model_transport_failure_is_sanitized(tmp_path,monkeypatch):
    monkeypatch.setenv('WETHA_GEMINI_MODEL','test-model');monkeypatch.setenv('WETHA_GEMINI_API_KEY','test-secret-not-real')
    def fail(request):
        raise httpx.ConnectError('Error containing test-secret-not-real',request=request)
    with TestClient(create_app(tmp_path,model_transport=httpx.MockTransport(fail))) as client:
        response=client.post('/api/newsroom/runs',json={'advisory_id':current(client).id,'engine':'gemini'})
        assert response.status_code==422 and 'test-secret-not-real' not in response.text
        run=client.get('/api/newsroom/runs/'+client.get('/api/newsroom').json()['runs'][0]['id']).text
        assert 'test-secret-not-real' not in run


def test_run_revision_and_review_survive_restart_and_interrupted_runs_fail(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        item=current(client);document=draft(client,item)
        updated=edit(client,document,document['text']+'\n\nMaximum sustained winds are 85 mph.').json()
        client.post(f"/api/scripts/{document['id']}/review",json={'reviewer':'Test reviewer','expected_revision':2})
        store=client.app.state.store
        identity=store.start_run(item.id,'deterministic')
        store.start_step(identity,1,'Data collector',{'advisory_id':item.id})
    with TestClient(create_app(tmp_path)) as client:
        shown=client.get(f"/api/scripts/{document['id']}").json()
        assert shown['text']==updated['text'] and shown['revision']==2 and shown['review_valid']
        assert len(shown['versions'])==2 and len(shown['reviews'])==1
        run=client.get('/api/newsroom/runs/'+identity).json()
        assert run['status']=='failed' and run['steps'][0]['status']=='failed'
        assert 'restart' in run['error']


def test_requested_source_refresh_failure_preserves_evidence_and_has_no_draft(tmp_path):
    denied=httpx.MockTransport(lambda request:httpx.Response(403,text='Source unavailable'))
    with TestClient(create_app(tmp_path,source_transport=denied)) as client:
        item=current(client)
        result=client.post('/api/newsroom/runs',json={'advisory_id':item.id,'refresh_sources':True})
        assert result.status_code==422
        run=client.get('/api/newsroom/runs/'+client.get('/api/newsroom').json()['runs'][0]['id']).json()
        assert run['status']=='failed' and run['steps'][0]['agent']=='Data collector'
        assert run['steps'][0]['status']=='failed' and run['script_id'] is None
        assert client.get('/api/dashboard').json()['stats']['stored_advisories']==1
        assert client.get('/api/dashboard').json()['stats']['scripts']==0


def test_pre_phase3_database_upgrade_preserves_original_script_and_review_metadata(tmp_path):
    from app.newsroom import GroundedScriptWriter
    import sqlite3
    item=training_advisories()[0]
    document=GroundedScriptWriter().generate(item,None)
    document.update(status='reviewed',reviewer='Legacy reviewer',reviewed_at='2024-01-01T12:00:00+00:00')
    conn=sqlite3.connect(tmp_path/'studio.sqlite3')
    conn.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
    for migration in sorted((Path(__file__).parents[1]/'migrations').glob('*.sql')):
        if migration.name.startswith('004'):
            continue
        conn.executescript(migration.read_text())
        conn.execute('INSERT INTO schema_migrations VALUES (?, ?)',(migration.name,'2024-01-01'))
        conn.commit()
    conn.execute('INSERT INTO advisories VALUES (?, ?, ?, ?, ?, ?, ?)',(item.id,item.provider,item.event_key,item.issued_at.isoformat(),item.checksum,item.model_dump_json(),'2024-01-01'))
    conn.execute('INSERT INTO scripts VALUES (?, ?, ?, ?)',(document['id'],item.id,json.dumps(document),'2024-01-01'))
    conn.commit();conn.close()
    with TestClient(create_app(tmp_path)) as client:
        shown=client.get('/api/scripts/'+document['id']).json()
        assert shown['revision']==1 and shown['text']==document['text']
        assert shown['versions'][0]['editor']=='Legacy writer'
        assert shown['review_valid'] is False
        raw=client.app.state.store.script(document['id'],1)
        assert raw['reviewer']=='Legacy reviewer' and raw['status']=='reviewed'


def test_source_update_during_model_request_is_detected_before_editorial_gate(tmp_path,monkeypatch):
    monkeypatch.setenv('WETHA_OLLAMA_MODEL','test-model')
    app=create_app(tmp_path)
    def respond(request):
        item=app.state.store.advisory('synthetic-current')
        app.state.store.save_advisory(item.model_copy(update={'id':'newer-during-model','issued_at':datetime.now(timezone.utc)}))
        blocks=json.loads(json.loads(request.content)['messages'][0]['content'])['blocks']
        return httpx.Response(200,json={'message':{'content':json.dumps({'order':[block['id'] for block in blocks]})}})
    app=create_app(tmp_path,model_transport=httpx.MockTransport(respond))
    with TestClient(app) as client:
        result=client.post('/api/newsroom/runs',json={'advisory_id':current(client).id,'engine':'ollama'})
        assert result.status_code==200
        assert result.json()['label']=='superseded' and result.json()['editorial']['can_review'] is False
