"""Footage keys: private storage, never returned or echoed, used by stock search."""
import json
import os
import stat
import httpx
from fastapi.testclient import TestClient
from app.credentials import Credentials

KEY = 'TestPexelsKey0123456789abcdefXYZ'


def test_keys_are_owner_only_and_status_never_contains_them(tmp_path, monkeypatch):
    monkeypatch.delenv('PEXELS_API_KEY', raising=False);monkeypatch.delenv('PIXABAY_API_KEY', raising=False)
    store = Credentials(tmp_path)
    status = store.update({'pexels': KEY})
    if os.name != 'nt':  # Windows has no Unix permission bits; the file lives in the user's private profile folder there.
        assert stat.S_IMODE(os.stat(tmp_path / 'credentials.json').st_mode) == 0o600
    assert KEY not in json.dumps(status) and status['pexels'] == {'configured': True, 'source': 'saved in app'}
    assert store.get('pexels') == KEY and store.get('pixabay') is None
    monkeypatch.setenv('PEXELS_API_KEY', 'EnvironmentKey0123456789abcd')
    assert store.get('pexels') == 'EnvironmentKey0123456789abcd' and store.status()['pexels']['source'] == 'environment'
    store.update({'pexels': ''})
    assert 'PEXELS_API_KEY' not in json.loads((tmp_path / 'credentials.json').read_text())


def test_api_saves_tests_and_never_echoes_keys(tmp_path, monkeypatch):
    from app.main import create_app
    monkeypatch.delenv('PEXELS_API_KEY', raising=False);monkeypatch.delenv('PIXABAY_API_KEY', raising=False)
    seen = []
    def transport(request):
        if request.url.host == 'api.pexels.com':
            seen.append(request.headers['Authorization'])
            return httpx.Response(401, json={'error': 'bad key'})
        return httpx.Response(200, json={'query': {'pages': {}}, 'response': {'docs': []}})
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        bad = client.put('/api/settings/footage-keys', json={'pexels': 'not a key!'})
        assert bad.status_code == 422 and 'not a key' not in bad.text
        saved = client.put('/api/settings/footage-keys', json={'pexels': KEY})
        assert saved.status_code == 200 and KEY not in saved.text
        assert KEY not in client.get('/api/settings/footage-keys').text
        tested = client.post('/api/settings/footage-keys/test')
        assert KEY not in tested.text and 'rejected the API key' in tested.json()['pexels']['message']
        assert seen == [KEY]  # sent only to the provider


def test_footage_review_ranks_per_beat_builds_a_sheet_and_imports_nothing(tmp_path, monkeypatch):
    from app.main import create_app
    from test_production import prepare
    monkeypatch.setenv('PEXELS_API_KEY', KEY);monkeypatch.delenv('PIXABAY_API_KEY', raising=False)
    from PIL import Image
    import io
    jpeg = io.BytesIO();Image.new('RGB', (64, 36), 'gray').save(jpeg, 'JPEG')
    def transport(request):
        if request.url.host == 'api.pexels.com':
            return httpx.Response(200, json={'videos': [
                {'id': 1, 'url': 'https://www.pexels.com/video/hurricane-storm-waves-1/', 'duration': 20, 'user': {'name': 'Ana'}, 'image': 'https://images.pexels.com/1.jpg',
                 'video_files': [{'file_type': 'video/mp4', 'width': 1920, 'height': 1080, 'link': 'https://videos.pexels.com/video-files/1/hd.mp4'}]},
                {'id': 2, 'url': 'https://www.pexels.com/video/city-skyline-2/', 'duration': 3, 'user': {'name': 'Bo'}, 'image': 'https://images.pexels.com/2.jpg',
                 'video_files': [{'file_type': 'video/mp4', 'width': 1280, 'height': 720, 'link': 'https://videos.pexels.com/video-files/2/hd.mp4'}]}]})
        return httpx.Response(200, json={'query': {'pages': {}}, 'response': {'docs': []}})
    monkeypatch.setattr('app.footage_review.preview', lambda client, url: _image())
    async def _image_coro():
        return Image.new('RGB', (64, 36), 'gray')
    def _image():
        return _image_coro()
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        _, plan, _ = prepare(client)
        before = len(client.get('/api/production').json()['media'])
        result = client.post('/api/production/footage-review', json={'plan_id': plan['id']})
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['beats'] and all(len(b['candidates']) <= 4 for b in data['beats'])
        ranked = [c for b in data['beats'] for c in b['candidates']]
        storm = next(c for c in ranked if 'Hurricane' in c['title']);skyline = next(c for c in ranked if 'skyline' in c['title'].lower())
        assert storm['score'] > skyline['score'] and not skyline['recommended']
        assert client.get(f"/api/production/footage-reviews/{data['id']}/sheet").status_code == 200
        assert len(client.get('/api/production').json()['media']) == before  # review never imports


def test_search_needs_fall_back_to_the_plan_source_for_older_plans():
    from types import SimpleNamespace
    from app.footage_expansion import needs
    plan = {'id': 'p', 'advisory_id': 'nhc:AL092026:7A', 'scenes': [{'id': 's', 'script_segment': 'Isaias brought flooding rain to Florida.', 'parameters': {}}]}
    seen = []
    store = SimpleNamespace(advisory=lambda identity: seen.append(identity) or SimpleNamespace(area='', title='Hurricane Isaias', event_key='AL092026', forecast_excerpt='', provider='NHC', text=''))
    rows = needs(plan, store)
    assert rows and set(seen) == {'nhc:AL092026:7A'}


def test_hurricane_review_rejects_wrong_settings_and_spreads_clips():
    from types import SimpleNamespace
    from app.footage_review import score
    advisory = SimpleNamespace(title='Hurricane Isaias Advisory 7A', event_key='AL092026', forecast_excerpt='')
    scene = {'script_segment': 'Hurricane Isaias brought strong winds to the coast.'}
    licensed = {'provider': 'pexels', 'height': 1080, 'seconds': 20, 'reuse_basis': 'stock_license', 'license': 'Pexels License'}
    mountain = {**licensed, 'id': 'm', 'title': 'Dramatic storm clouds over mountain landscape', 'tags': ['storm']}
    palms = {**licensed, 'id': 'p', 'title': 'Palm trees bending in hurricane wind on the beach', 'tags': ['wind', 'storm']}
    grass = {**licensed, 'id': 'g', 'title': 'Vibrant green grass in windy field', 'tags': ['wind']}
    m, p, g = (score(c, scene, advisory) for c in (mountain, palms, grass))
    assert p[2] and not m[2] and not g[2]
    assert p[0] > m[0] and p[0] > g[0]
    assert any('generic' in r for r in m[1]) and any('Contradicts' in r for r in g[1])
    again = score(palms, scene, advisory, shown={'p'})
    assert again[0] < p[0] and 'Already offered for an earlier beat' in again[1] and not again[2]


def test_calm_short_and_elsewhere_clips_are_never_recommended():
    from types import SimpleNamespace
    from app.footage_review import score, assess
    advisory = SimpleNamespace(title='Hurricane Isaias Advisory 7A', event_key='AL092026', forecast_excerpt='')
    scene = {'script_segment': 'Waves and storm surge hit the coast.'}
    base = {'tags': ['waves', 'storm'], 'provider': 'pexels', 'height': 1080, 'seconds': 20, 'reuse_basis': 'stock_license', 'license': 'Pexels License'}
    for title, seconds in (('Serene view of tropical palm trees and ocean waves', 20), ('Dramatic ocean waves crashing at sunset', 20),
                           ('Storm at the coastal area', 3)):
        assert not score({**base, 'id': title, 'title': title, 'seconds': seconds}, scene, advisory)[2], title
    assert score({**base, 'id': 'ok', 'title': 'Hurricane storm surge waves crashing over seawall'}, scene, advisory)[2]
    # Another place in the title is a location fact, not a relevance penalty: illustrative footage may come from anywhere.
    other = assess({**base, 'id': 's', 'title': 'Storm surge overtopping a seawall in San Diego'}, scene, advisory)
    assert other['tier'] in ('auto', 'recommended') and other['location']['named_place'] == 'San Diego'
