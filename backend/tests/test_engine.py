"""Visual director, footage intelligence, providers, reports, captions and packaging."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app import media_selection, production_report, packaging
from app.visual_director import classify, annotate


@pytest.mark.parametrize('text,intent,footage', [
    ('Hurricane Milton rapidly intensified overnight into a category five storm.', 'intensification', 'phenomenon'),
    ('The storm is moving north toward the Big Bend at 12 mph.', 'movement', 'phenomenon'),
    ('Milton made landfall near Siesta Key late Wednesday.', 'landfall', 'phenomenon'),
    ('Flash flooding swamped neighborhoods along the river.', 'flooding', 'impact'),
    ('A tornado warning is in effect for Polk County until 9 PM.', 'tornado', 'phenomenon'),
    ('Crews rescued residents from flooded homes overnight.', 'response', 'response'),
    ('Heat index values could reach 115 degrees this afternoon.', 'temperature', 'establishing'),
    ('More updates will follow at the top of the hour.', 'context', 'establishing'),
])
def test_director_reads_the_meaning_of_each_beat(text, intent, footage):
    result = classify(text, 'Hurricane Milton Advisory 18')
    assert result['intent'] == intent and result['footage_class'] == footage
    assert result['preferred'] and 0 < result['confidence'] <= .95


def test_hazard_falls_back_to_the_story_not_a_guess():
    assert classify('Conditions will deteriorate tonight.', 'Tropical Storm Debby Advisory 5')['hazard'] == 'tropical_cyclone'
    assert classify('Conditions will deteriorate tonight.', '')['hazard'] == 'general'


def test_every_shot_gets_a_traceable_decision_record():
    advisory = SimpleNamespace(title='Hurricane Test', event_key='AL01', forecast_excerpt='')
    scenes = [
        {'id': 'a', 'script_segment': 'Flooding swamped homes.', 'seconds': 4, 'cuts': [{'media_id': 'clip', 'seconds': 4, 'trim_start': 0}], 'media_id': None,
         'parameters': {'source_advisory_id': 'x'}, 'direction': {'scene_type': 'ground_footage'}},
        {'id': 'b', 'script_segment': 'The hurricane strengthened to 140 mph.', 'seconds': 3, 'cuts': [], 'media_id': None, 'map_mode': 'auto', 'graphic_style': 'auto',
         'parameters': {'source_advisory_id': 'x', 'visual_state': 'pan', 'state_meta': {'available': ['wide', 'pan'], 'chosen': 'pan', 'reason': 'test'}},
         'direction': {'scene_type': 'region_focus'}},
    ]
    media = {'clip': {'context': 'archival', 'catalog': {}, 'name': 'flood.mp4'}}
    rows = annotate(scenes, lambda _: advisory, media)
    assert rows[0]['family'] == 'footage' and rows[0]['start'] == 0 and rows[1]['start'] == 4
    assert any('Archival' in w for w in rows[0]['warnings']) and any('not reviewed' in w for w in rows[0]['warnings'])
    assert rows[1]['intent'] == 'intensification'
    assert any('change gauge' in w for w in rows[1]['warnings'])  # wanted, but no two measurements existed


def asset(identity, tags, width=1920, **extra):
    return {'id': identity, 'kind': 'video', 'name': identity, 'seconds': 30, 'rights_confirmed': True, 'context': 'illustrative',
            'attribution': 'A', 'source': 's', 'width': width, 'catalog': {'tags': tags}, **extra}


def test_footage_ranking_prefers_the_shot_the_beat_needs():
    advisory = SimpleNamespace(event_key='x', title='Hurricane', forecast_excerpt='', issued_at=datetime(2024, 10, 9, tzinfo=timezone.utc))
    scene = {'id': 's', 'script_segment': 'Flooding and storm damage left roads impassable.', 'parameters': {}}
    ranked = media_selection.rank(scene, [asset('rain-sky', ['rain', 'storm']), asset('flooded-street', ['flood', 'damage'])], advisory)
    assert ranked[0]['media_id'] == 'flooded-street' and 'impact' in ranked[0]['shot_classes']
    low = media_selection.rank(scene, [asset('small', ['flood'], width=640), asset('hd', ['flood'])], advisory)
    assert low[0]['media_id'] == 'hd'


def test_location_and_date_labels_are_never_upgraded_silently():
    advisory = SimpleNamespace(issued_at=datetime(2024, 10, 9, tzinfo=timezone.utc))
    assert media_selection.location_confidence({'catalog': {'location': 'Tampa'}}) == 'provisional'
    assert media_selection.location_confidence({'catalog': {'location_reviewed': True, 'region_codes': ['FL']}}) == 'reviewed'
    assert media_selection.location_confidence({'catalog': {}}) == 'unknown'
    assert media_selection.temporal_label({'catalog': {'captured_at': '2024-10-09'}}, advisory) == 'current'
    assert media_selection.temporal_label({'catalog': {'captured_at': '2017-09-10'}}, advisory) == 'archival'
    assert media_selection.temporal_label({'catalog': {}}, advisory) == 'unknown'


def test_pexels_and_pixabay_results_carry_licences_and_skip_without_keys(tmp_path, monkeypatch):
    from app.main import create_app
    calls = []
    def transport(request):
        calls.append(request.url.host)
        if request.url.host == 'api.pexels.com':
            assert request.headers['Authorization'] == 'pexels-test-key'
            return httpx.Response(200, json={'videos': [{'id': 1, 'url': 'https://www.pexels.com/video/hurricane-waves-crashing-1/', 'duration': 20,
                'user': {'name': 'Ana'}, 'image': 'https://images.pexels.com/1.jpg',
                'video_files': [{'file_type': 'video/mp4', 'width': 1920, 'height': 1080, 'link': 'https://videos.pexels.com/video-files/1/hd.mp4'},
                                {'file_type': 'video/mp4', 'width': 640, 'height': 360, 'link': 'https://videos.pexels.com/video-files/1/sd.mp4'}]}]})
        if request.url.host == 'pixabay.com':
            return httpx.Response(200, json={'hits': [{'id': 2, 'pageURL': 'https://pixabay.com/videos/id-2/', 'tags': 'storm, rain, flood', 'duration': 15, 'user': 'Ben',
                'videos': {'large': {'url': 'https://cdn.pixabay.com/video/2/large.mp4', 'width': 1920, 'height': 1080, 'size': 12345678}}}]})
        return httpx.Response(200, json={'query': {'pages': {}}})
    monkeypatch.delenv('PEXELS_API_KEY', raising=False);monkeypatch.delenv('PIXABAY_API_KEY', raising=False)
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        body = {'query': 'hurricane storm', 'provider': 'all', 'kind': 'video', 'live': True}
        client.post('/api/production/discovery/search', json=body)
        assert 'api.pexels.com' not in calls and 'pixabay.com' not in calls
        monkeypatch.setenv('PEXELS_API_KEY', 'pexels-test-key');monkeypatch.setenv('PIXABAY_API_KEY', 'pixabay-test-key')
        result = client.post('/api/production/discovery/search', json={**body, 'query': 'hurricane waves'}).json()
        stock = {r['provider']: r for r in result['results'] if r['provider'] in ('pexels', 'pixabay')}
        assert stock['pexels']['download_url'].endswith('hd.mp4') and stock['pexels']['reuse_basis'] == 'stock_license'
        assert 'Pexels License' in stock['pexels']['license'] and stock['pexels']['context'] == 'illustrative'
        assert stock['pixabay']['bytes'] == 12345678 and 'Pixabay Content License' in stock['pixabay']['license']
        before = len(calls)
        client.post('/api/production/discovery/search', json={**body, 'query': 'hurricane waves'})
        assert calls[before:].count('api.pexels.com') == 0  # cached for 24 hours per provider terms


def test_parallel_footage_downloads_stay_within_limits(tmp_path):
    from app.footage_expansion import FootageExpansion, DOWNLOADS
    from app.contracts import FootageExpansionRequest
    active = {'now': 0, 'max': 0}
    async def run():
        plan = {'id': 'plan', 'scenes': [{'id': 's', 'script_segment': 'Florida rain and flooding', 'parameters': {'source_advisory_id': 'fl'}}]}
        store = SimpleNamespace(path=tmp_path / 'db', visual_plan=lambda _: plan, advisory=lambda _: SimpleNamespace(area=''))
        class Discovery:
            production = SimpleNamespace(store=store, validate_plan=lambda p, **k: None)
            async def search(self, body):
                return {'warnings': [], 'results': [{'id': f'{i:064}', 'title': f'clip {i}', 'kind': 'video', 'reuse_basis': 'stock_license', 'width': 1920, 'bytes': 1000} for i in range(10)]}
            async def import_candidate(self, body):
                active['now'] += 1;active['max'] = max(active['max'], active['now'])
                await asyncio.sleep(.02);active['now'] -= 1
                return {'id': body.candidate_id[-4:], 'name': 'n', 'seconds': 20, 'source': 's', 'license': 'l', 'bytes': 1000}
        manager = FootageExpansion(Discovery())
        job = manager.start(FootageExpansionRequest(plan_id='plan', max_new_clips=5))
        await asyncio.gather(*manager.tasks)
        return manager.get(job['id'])
    result = asyncio.run(run())
    assert len(result['imported']) == 5 and 1 < active['max'] <= DOWNLOADS


def test_qc_log_parsing_and_caption_checks():
    log = 'freeze_start: 10.0\nfreeze_duration: 7\nfreeze_end: 17.0\n[Parsed_ebur128] Summary:\n  Integrated loudness:\n    I:         -15.8 LUFS\n  True peak:\n    Peak:       -1.2 dBFS\nsilence_duration: 2.5\n'
    measured = production_report.parse_qc(log)
    assert measured['integrated_lufs'] == -15.8 and measured['true_peak_dbtp'] == -1.2 and measured['freezes'] == [(10.0, 17.0)]
    srt = '1\n00:00:00,000 --> 00:00:00,300\nToo quick\n\n2\n00:00:01,000 --> 00:00:04,000\nA readable line\n\n3\n00:00:04,000 --> 00:00:05,000\n\n'
    count, findings = production_report.caption_checks(srt)
    codes = {c for _, c, _ in findings}
    assert count == 3 and {'caption_flash', 'blank_caption'} <= codes


def test_captions_start_on_recognized_words(tmp_path):
    from app.production import Production
    stub = object.__new__(Production)
    timeline = {'presentation': 'broadcast', 'scenes': [{'seconds': 6, 'script_segment': ' '.join(f'word{i}' for i in range(20)),
                                                         'word_frames': [i * 9 for i in range(20)]}]}
    srt = Production.captions(stub, timeline)
    starts = [line.split(' --> ')[0] for line in srt.split('\n') if '-->' in line]
    assert starts[0] == '00:00:00,000' and len(starts) >= 2
    # The second page starts on its first word's spoken frame, not at an even split of the shot.
    second_first_word = len(timeline['scenes'][0]['script_segment'][:84].split())  # first page ~ two 42-char lines
    assert starts[1] != '00:00:03,000'


def test_packaging_builds_private_metadata_and_valid_chapters():
    timeline = {'title': 'Milton nears Florida', 'report_title': 'Hurricane Milton Advisory 18', 'seconds': 60,
                'scenes': [{'seconds': 20, 'script_segment': 'Milton strengthened. It is moving east.', 'parameters': {'source_advisory_id': a, 'places': [('Tampa', [0, 0])]}} for a in ('a', 'b', 'c')]}
    report = {'sources': [{'id': x, 'title': f'Story {x}', 'provider': 'NHC', 'issued_at': '2024-10-09T00:00:00+00:00'} for x in 'abc'],
              'footage': [{'attribution': 'Ana / Pexels', 'license': 'Pexels License', 'context': 'illustrative'}],
              'visual_plan': [{'hazard': 'tropical_cyclone'}]}
    meta = packaging.metadata(timeline, report)
    assert meta['privacy'] == 'private' and meta['publishing']['status'] == 'not_configured'
    assert [c['start'] for c in meta['chapters']] == [0, 20, 40]
    assert '0:00 Story a' in meta['description'] and 'Ana / Pexels' in meta['description']
    assert 'tropical cyclone' in meta['tags']
    short = {**timeline, 'scenes': timeline['scenes'][:2], 'seconds': 40}
    assert packaging.metadata(short, report)['chapters'] == []  # fewer than three chapters are not valid on YouTube


def test_media_records_update_in_place(tmp_path):
    from app.storage import Store
    store = Store(tmp_path / 'db.sqlite3');store.initialize()
    document = {'id': 'm', 'checksum': 'c' * 64, 'kind': 'video', 'name': 'clip'}
    store.production_save('media', document)
    store.production_update_media({**document, 'shot_starts': [1.5]})
    assert store.production_get('media', 'm')['shot_starts'] == [1.5]
    with pytest.raises(KeyError):
        store.production_update_media({**document, 'checksum': 'd' * 64})


SPC_BODY = json.dumps({'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'LABEL': 'TSTM', 'fill': '#C1E9C1', 'stroke': '#55BB55', 'ISSUE_ISO': '2024-05-06T16:30:00+00:00',
     'VALID_ISO': '2024-05-06T16:30:00+00:00', 'EXPIRE_ISO': '2024-05-07T12:00:00+00:00', 'FORECASTER': 'Test'},
     'geometry': {'type': 'Polygon', 'coordinates': [[[-100, 30], [-90, 30], [-90, 40], [-100, 40], [-100, 30]]]}},
    {'type': 'Feature', 'properties': {'LABEL': 'MDT', 'fill': '#E67F7F', 'stroke': '#C00000', 'ISSUE_ISO': '2024-05-06T16:30:00+00:00',
     'VALID_ISO': '2024-05-06T16:30:00+00:00', 'EXPIRE_ISO': '2024-05-07T12:00:00+00:00', 'FORECASTER': 'Test'},
     'geometry': {'type': 'Polygon', 'coordinates': [[[-98, 34], [-95, 34], [-95, 37], [-98, 37], [-98, 34]]]}}]})


def test_spc_outlook_is_cached_per_issue_and_only_used_inside_its_valid_period(tmp_path):
    from app import spc, broadcast
    from app.storage import Store
    from app.visual_states import assign
    store = Store(tmp_path / 'db.sqlite3');store.initialize()
    attempts = []
    def transport(request):
        attempts.append(1)
        return httpx.Response(503) if len(attempts) == 1 else httpx.Response(200, content=SPC_BODY.encode())
    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await spc.collect(store, client, 1)
    asyncio.run(collect())
    assert len(attempts) == 2  # retried once after a server error
    inside = spc.find(store, datetime(2024, 5, 6, 20, tzinfo=timezone.utc))
    assert inside and inside['categories'] == ['TSTM', 'MDT'] and inside['attribution'] == 'NOAA/NWS Storm Prediction Center'
    assert spc.find(store, datetime(2024, 5, 8, tzinfo=timezone.utc)) is None
    advisory = SimpleNamespace(title='Tornado Watch 200', event_key='urn:test', forecast_excerpt='', warnings=[], provider='NWS', issued_at=datetime(2024, 5, 6, 20, tzinfo=timezone.utc))
    scenes = [{'id': f's{i}', 'type': 'region_focus', 'script_segment': 'A tornado watch covers central Oklahoma with damaging winds possible.', 'seconds': 4,
               'media_id': None, 'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto',
               'parameters': {'source_advisory_id': 'w', 'geojson': {'features': []}, 'outlook': inside, 'credit': 'NWS'}} for i in range(3)]
    for scene in scenes:
        scene['direction'] = broadcast.director(scene, 'urn:test', 4)
    states = assign(scenes, lambda _: advisory)
    assert states[0] == 'severe_outlook'
    frame = broadcast.Composer(scenes[0]['direction'], scenes[0]['parameters']).frame(.5)
    assert frame.size == (1920, 1080)


def test_spc_outage_raises_a_clear_error_instead_of_inventing_areas(tmp_path):
    from app import spc
    from app.storage import Store
    store = Store(tmp_path / 'db.sqlite3');store.initialize()
    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as client:
            return await spc.collect(store, client, 1, attempts=2)
    with pytest.raises(ValueError, match='unavailable'):
        asyncio.run(collect())
    assert store.visual_assets('spc_outlook') == []


def test_internet_archive_keeps_only_open_licences_and_weather_subjects(tmp_path, monkeypatch):
    from app.main import create_app
    monkeypatch.delenv('PEXELS_API_KEY', raising=False);monkeypatch.delenv('PIXABAY_API_KEY', raising=False)
    docs = [{'identifier': 'flash-flood-water', 'title': 'Flash Flood - Water', 'licenseurl': 'http://creativecommons.org/publicdomain/mark/1.0/', 'subject': ['flood', 'storm']},
            {'identifier': 'timothy-flood-talk', 'title': 'Conversations: Timothy Flood', 'licenseurl': 'http://creativecommons.org/publicdomain/mark/1.0/', 'subject': 'interview'},
            {'identifier': 'nc-flood', 'title': 'Flood footage', 'licenseurl': 'https://creativecommons.org/licenses/by-nc/4.0/', 'subject': 'flood'}]
    def transport(request):
        if request.url.path == '/advancedsearch.php':
            return httpx.Response(200, json={'response': {'docs': docs}})
        if request.url.path.startswith('/metadata/'):
            return httpx.Response(200, json={'d1': 'ia800100.us.archive.org', 'dir': '/1/items/flash-flood-water',
                'files': [{'name': 'clip.mp4', 'size': '9000000', 'height': '720', 'width': '1280', 'sha1': 'a' * 40}]})
        return httpx.Response(200, json={'query': {'pages': {}}})
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        result = client.post('/api/production/discovery/search', json={'query': 'flash flood', 'provider': 'all', 'kind': 'video', 'live': True}).json()
        archive = [r for r in result['results'] if r['provider'] == 'archive']
        assert [r['title'] for r in archive] == ['Flash Flood - Water']  # name match and NC licence rejected
        row = archive[0]
        assert row['download_url'] == 'https://ia800100.us.archive.org/1/items/flash-flood-water/clip.mp4'
        assert row['context'] == 'archival' and row['reuse_basis'] == 'public_domain' and row['expected_sha1'] == 'a' * 40


def test_place_beats_get_their_own_shot_and_layers_do_not_repeat_three_times():
    from app import broadcast
    from app.visual_states import assign
    advisory = SimpleNamespace(title='Flash Flood Warning issued October 10', event_key='urn:x', forecast_excerpt='', warnings=[], provider='NWS',
                               area='Richmond, GA; Aiken, SC', issued_at=datetime(2026, 10, 10, 21, tzinfo=timezone.utc),
                               expires_at=datetime(2026, 10, 10, 22, 30, tzinfo=timezone.utc),
                               source_payload={'properties': {'senderName': 'NWS Columbia SC'}},
                               facts={'description': 'At 533 PM EDT, Doppler radar indicated heavy rain. Between 3 and 4.5 inches of rain have fallen. HAZARD...Flash flooding caused by thunderstorms. SOURCE...Radar indicated. IMPACT...Flooding of small creeks and streams.'})
    polygon = {'type': 'Feature', 'properties': {'kind': 'alert_area'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-82.2, 33.3], [-81.8, 33.3], [-81.8, 33.6], [-82.2, 33.6], [-82.2, 33.3]]]}}
    texts = ['Along Florida’s Gulf Coast, surge was the threat.', 'Across parts of Alabama, heavy rain fell.', 'Rain continued.', 'Rain continued.',
             'Rain continued.', 'Rain continued.', 'Water kept rising in Georgia and South Carolina.', 'Rain continued.']
    scenes = []
    for i, text in enumerate(texts):
        scene = {'id': f's{i}', 'type': 'region_focus', 'script_segment': text, 'seconds': 4, 'media_id': None, 'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto',
                 'parameters': {'source_advisory_id': 'w', 'geojson': {'features': [polygon]}, 'facts': advisory.facts, 'credit': 'NWS'}}
        scene['direction'] = broadcast.director(scene, 'urn:x', 4)
        scenes.append(scene)
    states = assign(scenes, lambda _: advisory)
    assert states[0] == states[1] == states[6] == 'place_focus'
    assert [m['name'] for m in scenes[0]['parameters']['state_places']] == ['Florida Gulf Coast']
    assert {m['name'] for m in scenes[6]['parameters']['state_places']} == {'Georgia', 'South Carolina'}
    layers = [s['parameters']['visual_layer'] for s in scenes]
    assert not any(a == b == c for a, b, c in zip(layers, layers[1:], layers[2:]))
    assert 'warning_card' in states
    card = next(s for s in scenes if s['parameters'].get('visual_state') == 'warning_card')['parameters']['warning_card']
    assert card['office'] == 'NWS Columbia SC' and card['rain'].startswith('Between 3 and 4.5 inches') and card['hazard'].startswith('Flash flooding')
    for scene in scenes:
        assert broadcast.Composer(scene['direction'], scene['parameters']).frame(.7).size == (1920, 1080)


@pytest.mark.parametrize('text,expected', [
    ('And offshore near Georgia and northeast Florida,', [('Georgia', ['GA']), ('Northeast Florida', ['FL'])]),
    ('The Northeast braced for heavy rain.', [('Northeast', ['NY', 'NJ', 'PA', 'CT', 'RI', 'MA', 'VT', 'NH', 'ME'])]),
    ('Along Florida’s Gulf Coast, surge was the threat.', [('Florida Gulf Coast', ['FL'])]),
    ('Flooding hit southern Alabama overnight.', [('Southern Alabama', ['AL'])]),
    ('The Mississippi River rose near Baton Rouge, Louisiana.', [('Louisiana', ['LA'])]),
])
def test_place_names_resolve_to_the_right_states(text, expected):
    from app.geography import mentions
    assert [(m['name'], m['states']) for m in mentions(text)] == expected
