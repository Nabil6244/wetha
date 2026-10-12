"""The manual footage library: uploaded clips are catalogued, kept across restarts, and placed only where their hazard fits."""
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import media_selection
from app.main import create_app
from test_production import upload

# The same category -> tag mapping the Footage library page saves (desktop/src/components/ManualFootageLibrary.tsx).
FLASH_FLOOD = ['flash flood', 'flood']
TORNADO = ['tornado']
ISSUED = datetime(2026, 10, 10, 7, 21, tzinfo=timezone.utc)


def video(tmp_path, name, colour, seconds=6):
    path = tmp_path / name
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={colour}:s=1280x720:d={seconds}:r=30',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
    return path.read_bytes()


def catalog(tags, location='', regions=(), reviewed=False, reference=''):
    return {'tags': tags, 'event_id': '', 'location': location, 'region_codes': list(regions), 'location_reviewed': reviewed,
            'captured_at': None, 'reference': reference, 'preferred_trim_start': 0, 'setting_cleared': False, 'setting_note': ''}


def add(client, body, name, tags, **where):
    response = upload(client, body, name=name, kind='video', license='Filmed by me', attribution='Station crew', source='My own footage')
    assert response.status_code == 200, response.text
    clip = response.json()
    if not clip.get('duplicate'):
        saved = client.put(f"/api/production/media/{clip['id']}/catalog", json=catalog(tags, **where))
        assert saved.status_code == 200, saved.text
    return clip


def beat(text):
    return {'id': 's', 'script_segment': text, 'parameters': {'source_advisory_id': 'story'}}


def story(title, area):
    return SimpleNamespace(id='story', provider='NWS', title=title, event_key='urn:story', issued_at=ISSUED, forecast_excerpt='', area=area)


def test_uploads_are_catalogued_deduplicated_editable_and_kept_across_restarts(tmp_path):
    flood_clip = video(tmp_path, 'flooded-street.mp4', 'navy')
    with TestClient(create_app(tmp_path / 'data')) as client:
        clip = add(client, flood_clip, 'flooded-street.mp4', FLASH_FLOOD, location='Montgomery, Alabama', regions=['AL'])
        media = next(m for m in client.get('/api/production').json()['media'] if m['id'] == clip['id'])
        assert media['seconds'] == pytest.approx(6, abs=.2) and (media['width'], media['height']) == (1280, 720)
        assert media['catalog']['tags'] == FLASH_FLOOD and media['catalog']['region_codes'] == ['AL']
        assert media_selection.location_confidence(media) == 'provisional'   # declared, not verified
        # The same file again: reported as a duplicate, the original record and its catalog are kept.
        again = upload(client, flood_clip, name='copy.mp4', kind='video', license='Filmed by me', attribution='Station crew', source='My own footage').json()
        assert again['duplicate'] and again['id'] == clip['id'] and again['name'] == 'flooded-street.mp4'
        # A corrupt file is refused and never enters the library.
        broken = upload(client, b'\x00\x00\x00 not a video', name='broken.mp4', kind='video', license='Filmed by me', attribution='Crew', source='Mine')
        assert broken.status_code in (400, 422)
        assert [m['name'] for m in client.get('/api/production').json()['media'] if m['kind'] == 'video'] == ['flooded-street.mp4']
        # Editing metadata: a verified location needs a source documenting it.
        assert client.put(f"/api/production/media/{clip['id']}/catalog", json=catalog(FLASH_FLOOD, 'Montgomery, Alabama', ['AL'], True)).status_code == 422
        verified = catalog(FLASH_FLOOD, 'Montgomery, Alabama', ['AL'], True, 'https://example.org/where-it-was-filmed')
        assert client.put(f"/api/production/media/{clip['id']}/catalog", json=verified).status_code == 200
        stored = client.app.state.production.media_path(client.app.state.store.production_get('media', clip['id']))
    # Persistence: a new app on the same data folder still has the clip, its file and its catalog.
    assert str(stored).startswith(str(tmp_path / 'data'))
    with TestClient(create_app(tmp_path / 'data')) as client:
        media = next(m for m in client.get('/api/production').json()['media'] if m['id'] == clip['id'])
        assert media['catalog']['location_reviewed'] and stored.is_file()
        assert media_selection.location_confidence(media) == 'reviewed'


def test_removing_a_clip_keeps_its_file_and_can_be_undone(tmp_path):
    with TestClient(create_app(tmp_path / 'data')) as client:
        clip = add(client, video(tmp_path, 'hail.mp4', 'gray'), 'hail.mp4', ['hail'])
        removed = client.post(f"/api/production/media/{clip['id']}/quarantine", json={'reason': 'Removed from the footage library by the editor'})
        assert removed.status_code == 200 and removed.json()['quarantined']
        from pathlib import Path
        assert Path(removed.json()['quarantined']['path']).is_file()   # moved aside, not deleted
        assert client.post(f"/api/production/media/{clip['id']}/restore").json().get('quarantined') is None


def test_the_selector_places_an_uploaded_clip_only_where_its_hazard_fits(tmp_path):
    with TestClient(create_app(tmp_path / 'data')) as client:
        add(client, video(tmp_path, 'flooded-street.mp4', 'navy'), 'flooded-street.mp4', FLASH_FLOOD, location='Montgomery, Alabama', regions=['AL'])
        add(client, video(tmp_path, 'funnel.mp4', 'black'), 'funnel.mp4', TORNADO, location='Moore, Oklahoma', regions=['OK'])
        media = [m for m in client.get('/api/production').json()['media'] if m['kind'] == 'video']
    flood = story('Flash Flood Warning', 'Montgomery, AL')
    ranked = media_selection.rank(beat('Flash flooding covered roads across Alabama.'), media, flood, limit=None, allow_unverified=True)
    assert [r['media_id'] for r in ranked][:1] == [next(m['id'] for m in media if m['name'] == 'flooded-street.mp4')]
    assert 'funnel.mp4' not in [next(m['name'] for m in media if m['id'] == r['media_id']) for r in ranked]   # another hazard
    tornado = story('Tornado Warning', 'Cleveland County, OK')
    excluded = []
    ranked = media_selection.rank(beat('A tornado touched down near Moore.'), media, tornado, limit=None, allow_unverified=True, excluded=excluded)
    assert [next(m['name'] for m in media if m['id'] == r['media_id']) for r in ranked] == ['funnel.mp4']
    # The flood clip is refused, not forced in, even though it is the only other footage in the library.
    assert next(m['id'] for m in media if m['name'] == 'flooded-street.mp4') not in [r['media_id'] for r in ranked]
    winter = story('Winter Storm Warning', 'Crazy Mountains')
    assert media_selection.rank(beat('Heavy snow closed mountain passes.'), media, winter, limit=None, allow_unverified=True) == []
