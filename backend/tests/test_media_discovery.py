import hashlib
import io
import json

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.media_discovery import normalize, safe_url


def fixture():
    data = io.BytesIO()
    Image.new('RGB', (64, 36), '#435c78').save(data, 'PNG')
    return data.getvalue()


def page(raw, **changes):
    info = {'url': 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Rain.png',
            'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Rain.png',
            'mime': 'image/png', 'size': len(raw), 'width': 64, 'height': 36,
            'sha1': hashlib.sha1(raw).hexdigest(),
            'extmetadata': {'LicenseShortName': {'value': 'CC BY 4.0'},
                            'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by/4.0/'},
                            'Artist': {'value': '<a href="https://example.org">Synthetic creator</a>'},
                            'ImageDescription': {'value': '<b>Rain and wind</b> synthetic image'},
                            'DateTimeOriginal': {'value': '2017-09-05'},
                            'Credit': {'value': 'Synthetic source'}}, **changes}
    return {'title': 'File:Rain.png', 'imageinfo': [info]}


def test_normalization_license_host_html_and_youtube_origin():
    raw = fixture()
    result = normalize(page(raw))
    assert result['attribution'] == 'Synthetic creator'
    assert result['captured_at'] is None and result['event_id'] is None
    assert '<b>' not in result['description']
    assert normalize(page(raw, url='http://127.0.0.1/private.png')) is None
    assert normalize(page(raw, size=251*1024*1024)) is None
    original = page(raw)
    original['imageinfo'][0]['extmetadata']['LicenseShortName']['value'] = 'CC BY-SA 4.0'
    assert normalize(original) is None
    original = page(raw, mime='video/webm', url='https://upload.wikimedia.org/wikipedia/commons/a/ab/Rain.webm')
    original['imageinfo'][0]['extmetadata']['Credit']['value'] = '<a href="https://www.youtube.com/watch?v=AbCdEf012_-">YouTube</a>'
    result = normalize(original)
    assert result['provider'] == 'youtube' and result['source'].endswith('AbCdEf012_-')
    original['imageinfo'][0]['extmetadata']['Credit']['value'] = '<a href="https://evil.youtube.com/watch?v=AbCdEf012_-">YouTube</a>'
    assert normalize(original)['provider'] == 'commons'
    assert not safe_url('https://upload.wikimedia.org@localhost/file', {'upload.wikimedia.org'})
    assert normalize({'imageinfo': []}) is None


def test_live_search_cache_and_import_preserves_source_credits(tmp_path):
    raw = fixture()
    calls = []
    def transport(request):
        calls.append(request.url)
        if request.url.host == 'commons.wikimedia.org':
            return httpx.Response(200, json={'query': {'pages': {'1': page(raw)}}})
        assert request.url.host == 'upload.wikimedia.org'
        return httpx.Response(200, content=raw, headers={'content-type': 'image/png'})
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        body = {'query': 'rain', 'kind': 'image', 'provider': 'commons'}
        result = client.post('/api/production/discovery/search', json=body).json()
        assert len(result['results']) == 1 and not result['warnings']
        candidate = result['results'][0]
        client.post('/api/production/discovery/search', json=body)
        assert len(calls) == 1
        assert client.post('/api/production/discovery/import', json={'candidate_id': candidate['id'], 'rights_confirmed': False}).status_code == 422
        imported = client.post('/api/production/discovery/import', json={'candidate_id': candidate['id'], 'rights_confirmed': True})
        assert imported.status_code == 200
        asset = imported.json()
        assert asset['license'].startswith('CC BY 4.0') and asset['attribution'] == 'Synthetic creator'
        assert asset['catalog']['tags'] == ['rain', 'wind']
        assert asset['catalog']['captured_at'] is None
        assert client.get(f"/api/production/media/{asset['id']}/file").content == raw
        assert client.post('/api/production/discovery/import', json={'candidate_id': candidate['id'], 'rights_confirmed': True}).json()['duplicate']
        assert len(calls) == 2
        cached = client.post('/api/production/discovery/search', json=body).json()['results'][0]
        assert cached['local_media_id'] == asset['id']
        assert len(client.get('/api/production').json()['media']) == 1


def test_offline_and_changed_bytes_fail_without_partial_import(tmp_path):
    raw = fixture()
    mode = ['offline']
    def transport(request):
        if mode[0] == 'offline':
            raise httpx.ConnectError('Offline test', request=request)
        if request.url.host == 'commons.wikimedia.org':
            return httpx.Response(200, json={'query': {'pages': {'1': page(raw)}}})
        return httpx.Response(200, content=b'changed bytes')
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        fallback = client.post('/api/production/discovery/search', json={'query': 'rain waves'}).json()
        assert fallback['warnings'] and len(fallback['results']) >= 2
        assert 'pexels' in fallback['links'] and 'youtube' in fallback['links']
        mode[0] = 'changed'
        result = client.post('/api/production/discovery/search', json={'query': 'wind', 'kind': 'image', 'provider': 'commons'}).json()
        response = client.post('/api/production/discovery/import', json={'candidate_id': result['results'][0]['id'], 'rights_confirmed': True})
        assert response.status_code == 422 and 'checksum changed' in response.json()['detail']
        assert client.get('/api/production').json()['media'] == []
        assert list((tmp_path / 'production/media').iterdir()) == []
        assert client.post('/api/production/discovery/import', json={'candidate_id': '0'*64, 'rights_confirmed': True}).status_code == 422


def test_offline_reviewed_stock_youtube_filters_and_no_arbitrary_url(tmp_path):
    def transport(request):
        raise AssertionError('No network expected')
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        rows = client.get('/api/production/discovery').json()['results']
        assert len(rows) == 3
        stock = client.post('/api/production/discovery/search', json={'query': 'rain', 'provider': 'stock', 'live': False}).json()
        assert len(stock['results']) == 1 and stock['results'][0]['provider'] == 'stock'
        youtube = client.post('/api/production/discovery/search', json={'query': 'waves', 'provider': 'youtube', 'live': False}).json()
        assert len(youtube['results']) == 1 and youtube['results'][0]['event_id'] == 'AL112017'
        assert client.post('/api/production/discovery/import', json={'candidate_id': rows[0]['id'], 'rights_confirmed': True, 'url': 'https://localhost/secret'}).status_code == 422


def test_nasa_fallback_uses_real_camera_archive_and_preserves_duplicate_checksum(tmp_path):
    collection='https://images-assets.nasa.gov/video/iss-test/collection.json'
    video='https://images-assets.nasa.gov/video/iss-test/iss-test~large.mp4'
    def transport(request):
        if request.url.host=='commons.wikimedia.org':raise httpx.ConnectError('Synthetic provider outage',request=request)
        if request.url.host=='images-api.nasa.gov':
            return httpx.Response(200,json={'collection':{'items':[{'href':collection,'data':[{
                'nasa_id':'iss-test','center':'JSC','title':'ISS cameras view a storm','media_type':'video',
                'description':'A dated hurricane offshore near Florida.','date_created':'2019-01-01T00:00:00Z'}]}]}})
        if str(request.url)==collection:return httpx.Response(200,json=[video.replace('https:','http:')])
        if request.method=='HEAD' and str(request.url)==video:return httpx.Response(200,headers={'content-length':'1000'})
        raise AssertionError(str(request.url))
    with TestClient(create_app(tmp_path,discovery_transport=httpx.MockTransport(transport))) as client:
        result=client.post('/api/production/discovery/search',json={'query':'Florida storm','provider':'all','kind':'video'}).json()
        candidate=next(c for c in result['results'] if c['provider']=='nasa')
        assert candidate['download_url']==video and candidate['context']=='archival'
        assert candidate['captured_at'] is None and candidate['event_id'] is None
        assert candidate['regional_status']=='capture_location_review_needed'
        discovery=client.app.state.discovery
        discovery.remember({**candidate,'checksum':'remembered-local-checksum'})
        assert discovery.remember({k:v for k,v in candidate.items() if k!='checksum'})['checksum']=='remembered-local-checksum'
