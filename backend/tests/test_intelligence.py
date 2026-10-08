import asyncio
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from app.collector import Collector, parse_nhc_feed
from app.intelligence import IntelligenceDesk
from app.main import create_app
from app.storage import Store
from app.transport import SourceHTTP, feed_url
from app.weather import normalize_nws, freshness

FIXTURES = Path(__file__).parent / 'fixtures'
NWS = 'https://api.weather.gov/alerts/active'
NHC = 'https://www.nhc.noaa.gov/index-at.xml'


def feature(identity='test-alert', *, references=(), offset=-1, message='Alert', status='Actual', severity='Severe'):
    now = datetime.now(timezone.utc)
    return {'id':'https://api.weather.gov/alerts/' + identity, 'type':'Feature', 'properties':{
        'id':identity, 'sent':(now + timedelta(minutes=offset)).isoformat(),
        'expires':(now + timedelta(hours=12)).isoformat(), 'event':'Synthetic test warning',
        'areaDesc':'Synthetic test county', 'severity':severity, 'certainty':'Observed', 'urgency':'Immediate',
        'status':status, 'messageType':message, 'description':'SYNTHETIC TEST ONLY. Never a real observation.',
        'instruction':'Synthetic instructions.', 'references':[{'identifier':value} for value in references]}}


def collection(*features, next_url=None):
    result = {'type':'FeatureCollection', 'features':list(features)}
    if next_url:
        result['pagination'] = {'next':next_url}
    return result


def test_official_fixture_integrity_and_nhc_extraction():
    provenance = json.loads((FIXTURES / 'provenance.json').read_text())
    for entry in provenance['files']:
        assert hashlib.sha256((FIXTURES / entry['file']).read_bytes()).hexdigest() == entry['sha256']
    items, rejected = parse_nhc_feed((FIXTURES / 'nhc-atlantic-2026-10-08.xml').read_text())
    assert rejected == [] and len(items) == 1
    item = items[0]
    assert item.title == 'Tropical Storm Isaias'
    assert item.facts['advisory_number'] == '5A'
    assert item.facts['wind_mph'] == 65 and item.facts['pressure_mb'] == 994
    assert item.facts['movement_mph'] == 8
    assert item.issued_at == datetime(2026,10,8,0,tzinfo=timezone.utc)
    assert len(item.warnings) == 4
    assert 'Mouth of the Mississippi River to Yankeetown' in item.warnings[0]
    assert 'On the forecast track' in ' '.join(item.forecast_excerpt.split())
    desk = IntelligenceDesk(items, as_of=datetime(2026,10,8,2,27,tzinfo=timezone.utc))
    assert desk.describe(item)['verification']['status'] == 'verified_source'
    assert desk.describe(item)['priority']['score'] >= 40


def test_captured_nws_test_messages_are_not_current_weather():
    payload = json.loads((FIXTURES / 'nws-alerts-2026-10-08.json').read_text())
    items = [normalize_nws(item) for item in payload['features']]
    desk = IntelligenceDesk(items, as_of=datetime(2026,10,8,2,27,tzinfo=timezone.utc))
    test_message = next(item for item in items if item.facts['status'] == 'Test')
    assert desk.status(test_message) == 'non-operational'
    assert desk.priority(test_message)['score'] == 0
    assert all(item.source_payload for item in items)


def test_two_official_nhc_advisories_detect_real_measurement_and_warning_changes():
    earlier, rejected = parse_nhc_feed((FIXTURES/'nhc-atlantic-2026-10-08.xml').read_text())
    later, rejected_later = parse_nhc_feed((FIXTURES/'nhc-atlantic-2026-10-08-0300.xml').read_text())
    assert rejected == rejected_later == []
    assert later[0].facts['advisory_number'] == '6'
    assert later[0].facts['wind_mph'] == 70 and later[0].facts['pressure_mb'] == 988
    desk=IntelligenceDesk(earlier+later, as_of=datetime(2026,10,8,3,15,tzinfo=timezone.utc))
    described=desk.describe(later[0]);changes={change['field']:change for change in described['changes']}
    assert described['previous_id'] == earlier[0].id
    assert described['comparison']['status']=='verified_sources'
    assert changes['wind_mph']['delta']==5
    assert changes['pressure_mb']['delta']==-6
    assert changes['latitude']['delta']==.1
    assert changes['longitude']['delta']==.5
    assert 'Hurricane Watch' in changes['warnings_summary']['previous']
    assert 'Hurricane Warning' in changes['warnings_summary']['current']
    assert 'forecast_guidance' in changes
    assert desk.status(earlier[0])=='superseded'


def test_nws_update_and_cancellation_revoke_earlier_script_review(tmp_path):
    first = feature('first', offset=-60)
    second = feature('second', references=['first'], offset=-10, message='Update')
    cancel = feature('cancel', references=['second'], offset=-1, message='Cancel')
    responses = iter([collection(first), collection(second), collection(cancel)])
    with TestClient(create_app(tmp_path, httpx.MockTransport(lambda request:httpx.Response(200,json=next(responses))))) as client:
        assert client.post('/api/providers/nws/refresh').json()['inserted'] == 1
        draft = client.post('/api/scripts', json={'advisory_id':'first'}).json()
        assert client.post(f"/api/scripts/{draft['id']}/review",json={'reviewer':'Test editor'}).status_code == 200
        client.post('/api/providers/nws/refresh')
        items = {item['id']:item for item in client.get('/api/advisories').json()}
        assert items['first']['freshness'] == 'superseded'
        assert items['second']['previous_id'] == 'first'
        assert items['second']['freshness'] == 'current'
        assert client.post(f"/api/scripts/{draft['id']}/review",json={'reviewer':'Test editor'}).status_code == 409
        client.post('/api/providers/nws/refresh')
        dashboard = client.get('/api/dashboard').json()
        assert dashboard['stats']['current_alerts'] == 0
        assert len(dashboard['intelligence']['events']) == 1
        event = dashboard['intelligence']['events'][0]
        assert event['status'] == 'cancelled'
        timeline = client.get(f"/api/events/{event['id']}").json()['timeline']
        assert [item['id'] for item in timeline] == ['first','second','cancel']
        assert client.get('/api/advisories/first/evidence').json()['source_payload'] == first


def test_linked_events_work_when_predecessor_arrives_later():
    first, second, third = [normalize_nws(item) for item in [feature('first',offset=-60),feature('second',references=['first'],offset=-20,message='Update'),feature('third',references=['second'],message='Update')]]
    desk = IntelligenceDesk([third,first,second])
    assert len(desk.events()) == 1
    assert desk.previous(third).id == 'second'
    assert desk.previous(second).id == 'first'
    unrelated = normalize_nws(feature('unrelated'))
    assert len(IntelligenceDesk([first, second, unrelated]).events()) == 2


def test_absent_alert_is_not_active_after_complete_refresh(tmp_path):
    item = feature()
    responses = iter([collection(item), collection()])
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=next(responses))))) as client:
        client.post('/api/providers/nws/refresh')
        assert client.get('/api/advisories').json()[0]['freshness'] == 'current'
        client.post('/api/providers/nws/refresh')
        assert client.get('/api/advisories').json()[0]['freshness'] == 'not_active'
        assert client.get('/api/dashboard').json()['stats']['stored_advisories'] == 1


def test_long_duration_alert_uses_official_expiry_and_recent_feed_check():
    item = normalize_nws(feature(offset=-24*60))
    assert freshness(item) == 'current'
    feed = {'id':'nws','url':NWS,'status':'healthy','last_success_at':datetime.now(timezone.utc).isoformat(),'interval_seconds':300}
    desk = IntelligenceDesk([item], [feed], {'nws':{item.id}})
    assert desk.status(item) == 'current'
    stale = dict(feed,last_success_at=(datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat())
    assert IntelligenceDesk([item], [stale], {'nws':{item.id}}).status(item) == 'stale_feed'


def test_failed_collection_preserves_evidence_and_blocks_current_review(tmp_path):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200,json=collection(feature())) if calls == 1 else httpx.Response(403)
    with TestClient(create_app(tmp_path,httpx.MockTransport(handler))) as client:
        client.post('/api/providers/nws/refresh')
        draft = client.post('/api/scripts',json={'advisory_id':'test-alert'}).json()
        assert client.post('/api/providers/nws/refresh').status_code == 502
        assert calls == 2  # No unchanged retries for access denial.
        dashboard = client.get('/api/dashboard').json()
        assert dashboard['stats']['stored_advisories'] == 1
        assert dashboard['advisories'][0]['freshness'] == 'stale_feed'
        assert 'HTTP 403' in next(feed for feed in dashboard['intelligence']['feeds'] if feed['id']=='nws')['last_error']
        assert client.post(f"/api/scripts/{draft['id']}/review",json={'reviewer':'Test editor'}).status_code == 409


def test_malformed_records_are_quarantined_and_repeated_evidence_is_deduplicated(tmp_path):
    valid = feature()
    invalid = feature('invalid'); invalid['properties']['expires'] = invalid['properties']['sent']
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=collection(valid,invalid))))) as client:
        first = client.post('/api/providers/nws/refresh').json()
        assert first['collected'] == 1 and first['rejected'] == 1 and first['inserted'] == 1
        assert client.post('/api/providers/nws/refresh').json()['inserted'] == 0
        state = client.get('/api/intelligence').json()
        assert len(state['quarantine']) == 1
        assert next(feed for feed in state['feeds'] if feed['id']=='nws')['status'] == 'degraded'
        assert client.get('/api/advisories').json()[0]['freshness'] == 'current'


def test_conflicting_immutable_record_is_quarantined(tmp_path):
    first = feature()
    conflict = copy.deepcopy(first); conflict['properties']['description']='Conflicting changed source text under the same ID'
    responses = iter([collection(first),collection(conflict)])
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=next(responses))))) as client:
        client.post('/api/providers/nws/refresh')
        result = client.post('/api/providers/nws/refresh').json()
        assert result['rejected'] == 1 and result['inserted'] == 0
        assert client.get('/api/advisories').json()[0]['freshness'] == 'not_active'
        assert client.get('/api/advisories/test-alert/evidence').json()['source_payload'] == first


def test_priority_prefers_high_impact_operational_evidence():
    minor = normalize_nws(feature('minor',severity='Minor'))
    extreme = normalize_nws(feature('extreme',severity='Extreme'))
    test = normalize_nws(feature('test',severity='Extreme',status='Test'))
    desk = IntelligenceDesk([minor,test,extreme])
    assert desk.descriptions()[0]['id'] == 'extreme'
    assert desk.priority(test)['score'] == 0
    assert desk.priority(extreme)['tier'] == 'lead'
    assert desk.priority(extreme)['score'] > desk.priority(minor)['score']


def test_source_cache_revalidation_survives_restart_and_keeps_issue_time(tmp_path):
    first = feature()
    def handler(request):
        if request.headers.get('if-none-match') == '"sample"':
            return httpx.Response(304)
        return httpx.Response(200,json=collection(first),headers={'ETag':'"sample"'})
    transport = httpx.MockTransport(handler)
    with TestClient(create_app(tmp_path,transport)) as client:
        assert client.post('/api/providers/nws/refresh').json()['inserted'] == 1
    with TestClient(create_app(tmp_path,transport)) as client:
        result = client.post('/api/providers/nws/refresh').json()
        assert result['inserted'] == 0 and result['revalidated_pages'] == 1
        item = client.get('/api/advisories').json()[0]
        assert datetime.fromisoformat(item['issued_at'].replace('Z','+00:00')) == datetime.fromisoformat(first['properties']['sent'])


def test_cache_checksum_mismatch_is_rejected(tmp_path):
    store = Store(tmp_path/'db.sqlite3');store.initialize()
    store.cache_response(NWS,'verified body','etag',None)
    with store.connection() as conn:
        conn.execute('UPDATE http_cache SET body=?',('altered body',))
    async def run():
        source = SourceHTTP(store,httpx.MockTransport(lambda request:pytest.fail('Corrupt cache must be rejected before request')))
        try:
            with pytest.raises(ValueError,match='checksum mismatch'):
                await source.get(NWS)
        finally:
            await source.close()
    asyncio.run(run())


def test_paginated_alerts_are_committed_only_after_complete_collection(tmp_path):
    calls=[]
    first, second = feature('first'),feature('second')
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,json=collection(second) if request.url.query else collection(first,next_url=NWS+'?cursor=next'))
    with TestClient(create_app(tmp_path,httpx.MockTransport(handler))) as client:
        assert client.post('/api/providers/nws/refresh').json()['collected'] == 2
        assert len(calls)==2
        assert client.get('/api/dashboard').json()['stats']['current_alerts']==2


@pytest.mark.parametrize('next_url',['https://evil.test/private',NWS])
def test_invalid_or_cyclic_pagination_does_not_admit_partial_evidence(tmp_path,next_url):
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=collection(feature(),next_url=next_url))))) as client:
        assert client.post('/api/providers/nws/refresh').status_code == 502
        assert client.get('/api/advisories').json() == []


def test_overlapping_refreshes_share_one_collection(tmp_path):
    store=Store(tmp_path/'db.sqlite3');store.initialize()
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls=0
        async def handler(request):
            nonlocal calls
            calls+=1;started.set();await release.wait()
            return httpx.Response(200,json=collection(feature()))
        collector=Collector(store,httpx.MockTransport(handler))
        try:
            first=asyncio.create_task(collector.refresh('nws'));await started.wait()
            second=asyncio.create_task(collector.refresh('nws'));await asyncio.sleep(0)
            release.set();results=await asyncio.gather(first,second)
            assert calls == 1 and results[0] == results[1]
            assert len(store.jobs()) == 1
        finally:
            await collector.close()
    asyncio.run(run())


def test_polling_configuration_is_validated_persisted_and_resumed(tmp_path):
    calls=[]
    payload=collection(feature())
    def handler(request):
        calls.append(str(request.url));return httpx.Response(200,json=payload)
    app=create_app(tmp_path,httpx.MockTransport(handler))
    with TestClient(app) as client:
        assert client.post('/api/feeds/nws/polling',json={'enabled':True,'interval_seconds':5}).status_code == 422
        assert client.post('/api/feeds/unknown/polling',json={'enabled':False}).status_code == 404
        assert client.post('/api/feeds/nws/polling',json={'enabled':True,'interval_seconds':60}).status_code == 200
        # Wait for the actual worker via a loop on its durable result; no fixed long sleep.
        import time
        for _ in range(100):
            state=client.get('/api/intelligence').json()
            if next(feed for feed in state['feeds'] if feed['id']=='nws')['last_success_at']:
                break
            time.sleep(.01)
        else:pytest.fail('Enabled poller did not collect')
        assert len(calls)==1
        with app.state.store.connection() as conn:
            conn.execute('UPDATE feeds SET next_poll_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),'nws'))
    with TestClient(create_app(tmp_path,httpx.MockTransport(handler))) as client:
        for _ in range(100):
            feed=next(feed for feed in client.get('/api/intelligence').json()['feeds'] if feed['id']=='nws')
            if len(calls)>=2 and feed['status']=='healthy':break
            time.sleep(.01)
        else:pytest.fail('Persisted poller did not resume after restart')
        assert feed['enabled'] is True and feed['interval_seconds']==60
        client.post('/api/feeds/nws/polling',json={'enabled':False,'interval_seconds':60})
        assert next(feed for feed in client.get('/api/intelligence').json()['feeds'] if feed['id']=='nws')['next_poll_at'] is None


def test_transient_http_failures_retry_and_source_denials_do_not(tmp_path, monkeypatch):
    store=Store(tmp_path/'db.sqlite3');store.initialize()
    async def no_delay(seconds):pass
    monkeypatch.setattr('app.transport.asyncio.sleep',no_delay)
    count=0
    def handler(request):
        nonlocal count
        count+=1
        return httpx.Response(503) if count<3 else httpx.Response(200,text='verified response')
    async def run():
        source=SourceHTTP(store,httpx.MockTransport(handler))
        try:
            assert (await source.get(NWS)).body == 'verified response'
        finally:await source.close()
    asyncio.run(run());assert count==3


@pytest.mark.parametrize('url',['http://api.weather.gov/alerts/active',NWS+'?target=private','https://api.weather.gov.evil.test/alerts/active','https://user@api.weather.gov/alerts/active','https://api.weather.gov:443/alerts/active'])
def test_feed_allowlist_rejects_unapproved_destinations(url):
    with pytest.raises(ValueError):feed_url(url)


def test_rss_entities_are_rejected():
    with pytest.raises(ValueError,match='entities'):
        parse_nhc_feed('<!DOCTYPE rss [<!ENTITY x "expanded">]><rss><channel>&x;</channel></rss>')


def test_duplicate_conflicting_ids_in_one_page_are_not_admitted(tmp_path):
    first=feature()
    conflict=copy.deepcopy(first);conflict['properties']['severity']='Extreme'
    unrelated=feature('unrelated')
    payload=collection(first,conflict,unrelated,unrelated)
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=payload)))) as client:
        result=client.post('/api/providers/nws/refresh').json()
        assert result['collected']==1 and result['inserted']==1 and result['rejected']==1
        assert [item['id'] for item in client.get('/api/advisories').json()]==['unrelated']


def test_simultaneous_conflicting_event_versions_cannot_pass_review(tmp_path):
    first=feature('first')
    conflicting=copy.deepcopy(first)
    conflicting['id']='https://api.weather.gov/alerts/conflicting'
    conflicting['properties'].update(id='conflicting',severity='Extreme',references=[{'identifier':'first'}])
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=collection(first,conflicting))))) as client:
        client.post('/api/providers/nws/refresh')
        assert all(item['freshness']=='conflicting' for item in client.get('/api/advisories').json())
        draft=client.post('/api/scripts',json={'advisory_id':'first'}).json()
        assert draft['label']=='conflicting'
        assert client.post(f"/api/scripts/{draft['id']}/review",json={'reviewer':'Test editor'}).status_code==409


def test_inflight_worker_shutdown_records_interruption_and_backoff(tmp_path):
    store=Store(tmp_path/'db.sqlite3');store.initialize()
    async def run():
        started=asyncio.Event()
        async def handler(request):
            started.set();await asyncio.Event().wait()
        collector=Collector(store,httpx.MockTransport(handler))
        collector.configure('nws',True,60);collector.start()
        await asyncio.wait_for(started.wait(),timeout=2)
        await collector.close()
        feed=collector.feed('nws')
        assert store.jobs()[0]['status']=='failed'
        assert feed['consecutive_failures']==1
        assert datetime.fromisoformat(feed['next_poll_at']) > datetime.now(timezone.utc)+timedelta(seconds=100)
    asyncio.run(run())


def test_oversized_response_is_not_cached_or_admitted(tmp_path):
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,content=b'x'*8_000_001)))) as client:
        assert client.post('/api/providers/nws/refresh').status_code==502
        assert client.app.state.store.cache(NWS) is None
        assert client.get('/api/advisories').json()==[]


def test_wrong_rss_publication_time_quarantines_the_advisory():
    original=(FIXTURES/'nhc-atlantic-2026-10-08.xml').read_text()
    altered=original.replace('Wed, 07 Oct 2026 23:54:11 GMT','Wed, 07 Oct 2026 20:54:11 GMT')
    items,rejected=parse_nhc_feed(altered)
    assert items==[] and len(rejected)==1
    assert 'issue times disagree' in rejected[0]['reason']


def test_recovered_evidence_resolves_quarantine_without_erasing_history(tmp_path):
    valid=feature()
    invalid=copy.deepcopy(valid);invalid['properties']['description']=None
    responses=iter([collection(invalid),collection(valid)])
    with TestClient(create_app(tmp_path,httpx.MockTransport(lambda request:httpx.Response(200,json=next(responses))))) as client:
        assert client.post('/api/providers/nws/refresh').json()['rejected']==1
        assert len(client.get('/api/intelligence').json()['quarantine'])==1
        assert client.post('/api/providers/nws/refresh').json()['inserted']==1
        assert client.get('/api/intelligence').json()['quarantine']==[]
        with client.app.state.store.connection() as conn:
            rows=conn.execute('SELECT payload, resolved_at FROM rejected_evidence').fetchall()
        assert len(rows)==1 and rows[0]['resolved_at'] is not None
        assert json.loads(rows[0]['payload'])==invalid
