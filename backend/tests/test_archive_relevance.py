"""Internet Archive relevance: real false positives from a live import, plus positive and ambiguous cases."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app.media_discovery import archive_assessment

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/archive-relevance.json').read_text())
STRONG = {'identifier': 'noaa-hurricane-ian-surge', 'title': 'Hurricane Ian storm surge flooding in Fort Myers', 'collection': ['nasa'],
          'licenseurl': 'https://creativecommons.org/licenses/by/4.0/', 'creator': 'NOAA Ocean Service', 'subject': ['hurricane', 'storm surge', 'flooding'],
          'description': 'Storm surge and wind-driven waves flood streets.'}
STRONG_FILES = [{'name': 'surge.mp4', 'size': '80000000', 'height': '1080', 'width': '1920', 'length': '95', 'sha1': 'b' * 40}]


@pytest.mark.parametrize('row', FIXTURES, ids=[r['doc']['identifier'][:40] for r in FIXTURES])
def test_real_archive_items_get_the_right_verdict(row):
    result = archive_assessment(row['doc'], row['files'])
    assert result['verdict'] == row['expected'], result['reasons']
    assert result['reasons'] or result['verdict'] == 'strong'


def test_strong_needs_trusted_collection_720p_and_named_creator():
    assert archive_assessment(STRONG, STRONG_FILES)['verdict'] == 'strong'
    assert archive_assessment({**STRONG, 'collection': ['opensource_movies']}, STRONG_FILES)['verdict'] == 'review'
    assert archive_assessment({**STRONG, 'creator': ''}, STRONG_FILES)['verdict'] == 'review'  # CC BY without attribution
    assert archive_assessment(STRONG, [{**STRONG_FILES[0], 'height': '480'}])['verdict'] == 'review'
    assert archive_assessment({**STRONG, 'licenseurl': 'https://creativecommons.org/licenses/by-sa/4.0/'}, STRONG_FILES)['verdict'] == 'reject'
    assert archive_assessment({**STRONG, 'licenseurl': 'https://creativecommons.org/licenses/by-nc/4.0/'}, STRONG_FILES)['verdict'] == 'reject'
    assert archive_assessment(STRONG, [{**STRONG_FILES[0], 'size': str(400 * 1024 * 1024)}])['verdict'] == 'reject'  # over the download limit


def test_search_drops_rejected_items_and_marks_review_items(tmp_path, monkeypatch):
    from app.main import create_app
    monkeypatch.delenv('PEXELS_API_KEY', raising=False);monkeypatch.delenv('PIXABAY_API_KEY', raising=False)
    by_id = {r['doc']['identifier']: r for r in FIXTURES};by_id[STRONG['identifier']] = {'doc': STRONG, 'files': STRONG_FILES}
    fetched = []
    def transport(request):
        if request.url.path == '/advancedsearch.php':
            return httpx.Response(200, json={'response': {'docs': [r['doc'] for r in by_id.values()]}})
        if request.url.path.startswith('/metadata/'):
            identifier = request.url.path.split('/metadata/')[1];fetched.append(identifier);row = by_id[identifier]
            return httpx.Response(200, json={'d1': 'ia800100.us.archive.org', 'dir': f'/1/items/{identifier}', 'metadata': row['doc'],
                                             'files': [{**f, 'sha1': f.get('sha1') or 'c' * 40} for f in row['files']]})
        return httpx.Response(200, json={'query': {'pages': {}}})
    with TestClient(create_app(tmp_path, discovery_transport=httpx.MockTransport(transport))) as client:
        result = client.post('/api/production/discovery/search', json={'query': 'tornado storm', 'provider': 'all', 'kind': 'video', 'live': True}).json()
    archive = {r['title']: r for r in result['results'] if r['provider'] == 'archive'}
    for junk in ('Ogniste Tornado', 'Atomic Woman', 'Abandoned Dogs', 'Disney', 'Healing Scriptures', 'Sirens'):
        assert not any(junk.lower() in t.lower() for t in archive), junk
    assert archive['Hurricane Ian storm surge flooding in Fort Myers']['archive_verdict'] == 'strong'
    assert any('Hialeah' in t and r['archive_verdict'] == 'review' for t, r in archive.items())
    # Genre-blocked and title-only rejections never cost a metadata request.
    assert 'the-adventures-of-atomic-woman-episode-1-tornado-turmoil' not in fetched and 'florida-disney' not in fetched


def test_review_items_are_never_imported_and_stock_is_tried_first(tmp_path):
    from app.footage_expansion import FootageExpansion
    from app.contracts import FootageExpansionRequest
    imports = []
    async def run():
        plan = {'id': 'plan', 'scenes': [{'id': 's', 'script_segment': 'Tornado damage and flooding', 'parameters': {'source_advisory_id': 'a'}}]}
        store = SimpleNamespace(path=tmp_path / 'db', visual_plan=lambda _: plan, advisory=lambda _: SimpleNamespace(area=''))
        class Discovery:
            production = SimpleNamespace(store=store, validate_plan=lambda p, **k: None)
            async def search(self, body):
                return {'warnings': [], 'results': [
                    {'id': '1' * 64, 'title': 'Archive review', 'provider': 'archive', 'archive_verdict': 'review', 'archive_reasons': ['Personal-upload collection'], 'kind': 'video', 'reuse_basis': 'public_domain', 'width': 1280, 'bytes': 10, 'source': 'a'},
                    {'id': '2' * 64, 'title': 'Archive strong', 'provider': 'archive', 'archive_verdict': 'strong', 'kind': 'video', 'reuse_basis': 'cc_by', 'width': 1920, 'bytes': 10, 'source': 'b'},
                    {'id': '3' * 64, 'title': 'Pexels clip', 'provider': 'pexels', 'kind': 'video', 'reuse_basis': 'stock_license', 'width': 1920, 'bytes': 10, 'source': 'c'}]}
            async def import_candidate(self, body):
                imports.append(body.candidate_id[0])
                return {'id': body.candidate_id[:6], 'name': 'n', 'seconds': 20, 'source': 's', 'license': 'l', 'bytes': 10}
        manager = FootageExpansion(Discovery())
        job = manager.start(FootageExpansionRequest(plan_id='plan', max_new_clips=1))
        await asyncio.gather(*manager.tasks)
        return manager.get(job['id'])
    result = asyncio.run(run())
    assert imports[0] == '3'  # licensed stock before the Internet Archive
    assert '1' not in imports
    assert any(r['title'] == 'Archive review' for r in result['needs_review'])
