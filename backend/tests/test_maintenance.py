from pathlib import Path
from types import SimpleNamespace
import os
import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.maintenance import cleanup, summary
from app.storage import Store


def fixture(tmp_path):
    store=Store(tmp_path/'studio.sqlite3');store.initialize()
    # Exercise real FK relationships through the standard production fixture.
    return store


def test_cleanup_preserves_exports_media_and_symlink_targets(tmp_path):
    from test_production import prepare
    with TestClient(create_app(tmp_path)) as client:
        _,plan,_=prepare(client)
        store=client.app.state.store
        store.production_save('timelines',{'id':'timeline','plan_id':plan['id']})
        for status in ('succeeded','running'):
            store.production_save('renders',{'id':status,'timeline_id':'timeline','status':status,'stage':'test','progress':10,'validation':{'seconds':4},'attempts':1})
            folder=tmp_path/'production/renders'/status;folder.mkdir()
            for name in ('program.mp4','report.json','manifest.json','scene-000.mp4'):(folder/name).write_bytes(b'keep' if name!='scene-000.mp4' else b'cache')
            frames=folder/'frames-000';frames.mkdir();(frames/'cut-0.mp4').write_bytes(b'cut')
        outside=tmp_path/'original.mp4';outside.write_bytes(b'never touch')
        folder=tmp_path/'production/renders/succeeded';(folder/'scene-001.mp4').symlink_to(outside)
        media=tmp_path/'production/media/upload.mp3';media.write_bytes(b'audio')
        before=summary(store)
        assert before['scene_cache_bytes']==8
        assert before['weather_asset_bytes']>=0
        result=cleanup(store,'scene_cache')
        assert result['reclaimed_bytes']==8
        assert (folder/'program.mp4').read_bytes()==b'keep'
        assert (folder/'report.json').exists() and (folder/'manifest.json').exists()
        assert not (folder/'scene-000.mp4').exists()
        assert (tmp_path/'production/renders/running/scene-000.mp4').exists()
        assert outside.read_bytes()==b'never touch' and media.read_bytes()==b'audio'
        assert len(store.render_progress())==2
        assert store.render_progress()[0]['validation']=={'seconds':4}
        assert store.production_count('renders','succeeded')==1


def test_source_cache_cleanup_preserves_source_evidence_and_idle_guard(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/training/load')
        store=client.app.state.store
        count=len(store.advisories())
        store.cache_response('https://api.weather.gov/alerts/active','cached',None,None)
        client.app.state.production.tasks['test']=object()
        assert client.post('/api/storage/cleanup/source_responses').status_code==409
        assert store.cache('https://api.weather.gov/alerts/active')
        client.app.state.production.tasks.clear()
        assert client.post('/api/storage/cleanup/source_responses').status_code==200
        assert not store.cache('https://api.weather.gov/alerts/active')
        assert len(store.advisories())==count
        assert client.post('/api/storage/cleanup/compact').status_code==200
        assert client.post('/api/storage/cleanup/everything').status_code==422


def test_temporary_uploads_require_24_hours_and_retention_is_age_bound(tmp_path):
    store=fixture(tmp_path);folder=tmp_path/'production/media';folder.mkdir(parents=True)
    old=folder/'old.upload.mp3';new=folder/'new.upload.mp3';saved=folder/'audio.mp3'
    for p in (old,new,saved):p.write_bytes(b'audio')
    os.utime(old,(time.time()-90000,)*2)
    assert cleanup(store,'temporary')['removed_files']==1
    assert new.exists() and saved.exists() and not old.exists()


def test_compact_dashboard_keeps_full_source_text_available_on_demand(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/training/load')
        full=client.get('/api/dashboard').json()
        compact=client.get('/api/dashboard?compact=true').json()
        assert compact['stats']==full['stats']
        assert len(compact['advisories'])==len(full['advisories'])
        item=compact['advisories'][0]
        assert item['detail_available'] is False and item['text']=='' and item['facts']=={}
        evidence=client.get('/api/advisories/'+item['id']+'/evidence').json()['advisory']
        assert evidence['text'] and evidence['facts']
        assert evidence['text']==next(a['text'] for a in full['advisories'] if a['id']==item['id'])
