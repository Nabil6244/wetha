from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.media_selection import draft, rank
from test_production import prepare, upload


def advisory():
    return SimpleNamespace(event_key='AL092020', issued_at=datetime(2020, 8, 4, tzinfo=timezone.utc))


def asset(identity, **changes):
    return {'id': identity, 'name': 'rain-video.mp4', 'kind': 'video', 'seconds': 12,
            'rights_confirmed': True, 'context': 'illustrative', 'source_provider': 'stock',
            'attribution': 'Synthetic creator', 'source': 'Synthetic fixture',
            'preferred_clip_seconds': 3.5, **changes}


def scene(identity, kind='lower_third'):
    return {'id': identity, 'type': kind, 'script_segment': 'Rainfall and gusts affect Carolina coastal areas.', 'parameters': {}}


def test_rank_matches_topics_event_date_location_but_keeps_context_labels():
    matched = asset('matched', catalog={'tags': ['rain', 'wind'], 'event_id': 'AL092020', 'captured_at': '2020-08-04', 'location': 'Carolina', 'preferred_trim_start': 5})
    unrelated = asset('unrelated', context='archival', catalog={'tags': ['rain'], 'event_id': 'AL112017', 'captured_at': '2017-09-05'})
    result = rank(scene('1'), [unrelated, matched, asset('too-short', seconds=2), asset('audio', kind='audio'), asset('snow', name='snow.mp4')], advisory())
    assert [r['media_id'] for r in result] == ['matched', 'unrelated']
    assert result[0]['trim_start'] == 5 and result[0]['label'] == 'ILLUSTRATIVE FOOTAGE'
    assert any('Different event' in reason for reason in result[1]['reasons'])
    assert rank(scene('1'), [matched], advisory(), ['matched']) == []


def test_short_template_protects_graphics_order_closing_and_does_not_repeat():
    scenes = [scene('1'), scene('2', 'storm_track'), scene('3'), scene('4', 'what_changed'), scene('5'), scene('6')]
    result = draft({'scenes': scenes}, [asset('a'), asset('b')], advisory())
    edits = result['scenes']
    assert [s['id'] for s in edits] == [s['id'] for s in scenes]
    assert sum(round(s['seconds'] * 30) for s in edits) == 900
    assert [s['media_id'] for s in edits if s['media_id']] == ['a', 'b']
    assert all(edits[i]['media_id'] is None for i in (1, 3, 5))
    assert all(3 <= s['seconds'] <= 4 for s in edits if s['media_id'])
    assert all(s['seconds'] <= 6 for s in edits)
    assert any(issue['code'] == 'missing_footage' for issue in result['issues'])


def test_template_handles_dense_or_empty_library_without_dropping_claims():
    scenes = [scene(str(i)) for i in range(30)]
    result = draft({'scenes': scenes}, [asset(str(i)) for i in range(30)], advisory())
    assert len(result['scenes']) == 30
    assert sum(round(s['seconds'] * 30) for s in result['scenes']) == 900
    assert all(s['media_id'] is None for s in result['scenes'])
    empty = draft({'scenes': scenes[:5]}, [], advisory())
    assert sum(round(s['seconds'] * 30) for s in empty['scenes']) == 900
    with pytest.raises(ValueError, match='1–30'):
        draft({'scenes': scenes + [scene('extra')]}, [], advisory())


def test_catalog_assistance_and_nonmutating_preflight(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _, plan, body = prepare(client)
        media = upload(client, name='rain-fixture.png').json()
        catalog = {'tags': ['Rain', 'wind', 'rain'], 'event_id': 'AL092020', 'captured_at': '2020-08-04', 'location': 'Carolina', 'reference': 'Synthetic metadata fixture'}
        response = client.put(f"/api/production/media/{media['id']}/catalog", json=catalog)
        assert response.status_code == 200
        assert response.json()['catalog']['tags'] == ['rain', 'wind']
        assert response.json()['source'] == media['source'] and response.json()['license'] == media['license']
        assert client.put(f"/api/production/media/{media['id']}/catalog", json={**catalog, 'preferred_trim_start': 1}).status_code == 422
        result = client.post('/api/production/assist', json={'plan_id': plan['id']}).json()
        assert result['seconds'] == 30
        timeline = {**body, 'scenes': result['scenes'], 'presentation': 'broadcast', 'template': 'short_30', 'music': True}
        checked = client.post('/api/production/check', json=timeline).json()
        assert checked['ready'] and checked['seconds'] == 30
        assert client.get('/api/production').json()['timelines'] == []
        saved = client.post('/api/production/timelines', json=timeline)
        assert saved.status_code == 200 and saved.json()['template'] == 'short_30'
        altered = {**timeline, 'scenes': [{**s, 'seconds': 1} for s in result['scenes']]}
        assert not client.post('/api/production/check', json=altered).json()['ready']
        # Metadata edits cannot rewrite the catalogue retained by a saved timeline.
        client.put(f"/api/production/media/{media['id']}/catalog", json={'tags': ['snow']})
        picked = next((s for s in saved.json()['scenes'] if s['media_id']), None)
        if picked:
            assert picked['selection_catalog']['tags'] == ['rain', 'wind']
        (tmp_path / 'production/media' / media['filename']).write_bytes(b'corrupt')
        result = client.post('/api/production/assist', json={'plan_id': plan['id']}).json()
        assert any(i['code'] == 'unavailable_media' for i in result['issues'])
        assert all(s['media_id'] is None for s in result['scenes'])
        assert not client.post('/api/production/check', json={**body, 'scenes': [{**s, 'media_id': media['id']} for s in body['scenes']]}).json()['ready']


@pytest.mark.parametrize('template,target', [('report_60',60),('report_90',90)])
def test_report_sequences_use_unique_ranges_and_protect_graphic_pacing(template, target):
    scenes = [scene('intro'),scene('conditions'),scene('track','storm_track'),scene('stats','what_changed'),scene('impact'),scene('close')]
    result = draft({'scenes':scenes}, [asset('a',seconds=80),asset('b',seconds=80)],advisory(),template=template)
    assert result['ready'] and result['seconds']==target
    assert sum(round(s['seconds']*30) for s in result['scenes'])==target*30
    ranges = {}
    for row in result['scenes']:
        if not row['cuts']:
            assert row['seconds'] <= 6
        else:
            assert sum(round(c['seconds']*30) for c in row['cuts']) == round(row['seconds']*30)
        for cut in row['cuts']:
            assert 3 <= cut['seconds'] <= 4
            old=ranges.setdefault(cut['media_id'],[])
            assert all(cut['trim_start'] >= end-.01 for end in old)
            old.append(cut['trim_start']+cut['seconds'])
    assert not draft({'scenes':scenes}, [asset('tiny',seconds=4)],advisory(),template=template)['ready']
