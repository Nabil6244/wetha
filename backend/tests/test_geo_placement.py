"""Geographic gate on final footage selection: unit rules plus end-to-end placement through the API."""
import hashlib
import json
import shutil
import subprocess
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import media_selection
from app.geo_gate import placement

US = SimpleNamespace(provider='NWS', title='Flash Flood Warning', event_key='urn:x', issued_at=None)
TRAINING = SimpleNamespace(provider='TRAINING', title='Training Cyclone', event_key='T1', issued_at=None)
FLOOD = 'Across parts of Alabama, heavy rain raised flash-flood concerns.'


def asset(identity, name, tags, source='', **catalog):
    return {'id': identity, 'kind': 'video', 'name': name, 'seconds': 40, 'rights_confirmed': True, 'context': 'illustrative',
            'attribution': 'A', 'source': source or f'https://www.pexels.com/video/{identity}-1/', 'width': 1920,
            'catalog': {'tags': tags, **catalog}}


def scene(text=FLOOD):
    return {'id': 's', 'script_segment': text, 'parameters': {}}


def chosen(clips, text=FLOOD, advisory=US):
    excluded = []
    ranked = media_selection.rank(scene(text), clips, advisory, limit=None, allow_unverified=True, excluded=excluded)
    return [c['media_id'] for c in ranked], excluded


def test_named_foreign_places_never_enter_a_us_edit_even_when_highly_relevant():
    dhaka = asset('dhaka', 'pexels-1.mp4', ['flood', 'rain', 'damage'], 'https://www.pexels.com/video/flooded-street-in-dhaka-bangladesh-1/')
    mexico = asset('mexico', 'pexels-2.mp4', ['flood', 'rain'], 'https://www.pexels.com/video/urban-flooding-during-rain-in-mexico-city-2/')
    rickshaw = asset('rickshaw', 'pexels-3.mp4', ['flood'], 'https://www.pexels.com/video/urban-flooded-street-with-rickshaw-and-cars-3/')
    ids, excluded = chosen([dhaka, mexico, rickshaw])
    assert ids == []
    assert {e['media_id'] for e in excluded} == {'dhaka', 'mexico', 'rickshaw'} and all(e['compatibility'] == 'conflict' for e in excluded)
    # Confirmed conflicts stay excluded even after a reviewer clears the setting.
    cleared = asset('mexico2', 'pexels-4.mp4', ['flood'], 'https://www.pexels.com/video/urban-flooding-during-rain-in-mexico-city-4/', setting_cleared=True, setting_note='checked')
    assert not placement(cleared, FLOOD, US)['allowed']


def test_possible_conflict_waits_for_review_and_clearance_allows_it():
    street = asset('street', 'pexels-5.mp4', ['flood', 'rain'], 'https://www.pexels.com/video/urban-street-flooding-after-heavy-rainfall-5/')
    ids, excluded = chosen([street])
    assert ids == [] and excluded[0]['compatibility'] == 'possible_conflict' and 'clears the setting' in excluded[0]['reason']
    cleared = {**street, 'catalog': {**street['catalog'], 'setting_cleared': True, 'setting_note': 'US road signs, no foreign signage'}}
    assert chosen([cleared])[0] == ['street']
    reviewed = {**street, 'catalog': {**street['catalog'], 'location_reviewed': True, 'region_codes': ['AL'], 'reference': 'https://example.org'}}
    assert chosen([reviewed])[0] == ['street']


def test_location_neutral_and_us_named_footage_stay_eligible():
    surge = asset('surge', 'pexels-6.mp4', ['waves', 'storm'], 'https://www.pexels.com/video/storm-surge-waves-over-seawall-6/')
    palms = asset('palms', 'pexels-7.mp4', ['wind', 'storm'], 'https://www.pexels.com/video/palm-trees-bending-in-hurricane-wind-7/')
    rain = asset('rain', 'pexels-8.mp4', ['rain'], 'https://www.pexels.com/video/heavy-rain-falling-8/')
    houston = asset('houston', 'pexels-9.mp4', ['flood', 'rain'], 'https://www.pexels.com/video/houston-urban-street-flooding-9/')
    assert chosen([surge], 'Storm surge pushed water over seawalls along the Florida coast.')[0] == ['surge']
    assert chosen([palms], 'Hurricane-force winds bent palms across Florida.')[0] == ['palms']
    assert chosen([rain], 'Heavy rain fell for hours across Alabama.')[0] == ['rain']
    assert chosen([houston])[0] == ['houston']


def test_non_us_and_unknown_region_stories():
    street = asset('street', 'pexels-5.mp4', ['flood', 'rain'], 'https://www.pexels.com/video/urban-street-flooding-after-heavy-rainfall-5/')
    mexico = asset('mexico', 'pexels-2.mp4', ['flood', 'rain'], 'https://www.pexels.com/video/urban-flooding-during-rain-in-mexico-city-2/')
    # Not a US story: the US-specific street rule does not apply.
    assert chosen([street], advisory=TRAINING)[0] == ['street']
    # Unknown region, but the clip names a foreign place: excluded until cleared (existing protection).
    ids, excluded = chosen([mexico], advisory=TRAINING)
    assert ids == [] and 'story region is unknown' in excluded[0]['reason']
    cleared = {**mexico, 'catalog': {**mexico['catalog'], 'setting_cleared': True, 'setting_note': 'checked'}}
    assert chosen([cleared], advisory=TRAINING)[0] == ['mexico']


def test_bulletin_draft_reports_exclusions():
    from app.bulletin_edit import draft
    rows = [{'id': str(i), 'type': 'lower_third', 'seconds': 7, 'script_segment': FLOOD, 'parameters': {'source_advisory_id': 'a'}, 'media_id': None,
             'trim_start': 0, 'transition': 'cut', 'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto', 'regional_focus': 'auto'} for i in range(6)]
    mexico = asset('mexico', 'pexels-2.mp4', ['flood', 'rain'], 'https://www.pexels.com/video/urban-flooding-during-rain-in-mexico-city-2/')
    result = draft({'scenes': rows, 'unverified_location_footage': True}, [mexico], lambda _: US)
    assert not any(s['cuts'] for s in result['scenes'])
    assert result['excluded_footage'][0]['media_id'] == 'mexico'


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_unresolved_conflict_cannot_reach_the_final_edit_and_media_is_untouched(tmp_path):
    from app.main import create_app
    from test_production import prepare, upload
    fixture = tmp_path / 'clip.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30', '-t', '12', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(fixture)], check=True)
    with TestClient(create_app(tmp_path / 'data')) as client:
        _, plan, body = prepare(client)
        clip = upload(client, fixture.read_bytes(), name='urban-flooding-during-rain-in-mexico-city.mp4', kind='video', context='illustrative').json()
        client.put(f"/api/production/media/{clip['id']}/catalog", json={'tags': ['flood', 'rain', 'storm', 'wind', 'waves'], 'reference': ''})
        before = client.app.state.store.production_get('media', clip['id'])
        path = client.app.state.production.root / 'media' / before['filename'];digest = hashlib.sha256(path.read_bytes()).hexdigest()
        body.update(presentation='broadcast')
        for s in body['scenes']:
            s['seconds'] = 7
        # Automatic mixed edit: the clip is excluded and the reason is reported.
        draft = client.post('/api/production/bulletin-edit', json=body).json()
        assert not any(s['cuts'] for s in draft['scenes']) and draft['excluded_footage'][0]['media_id'] == clip['id']
        # Manual placement is refused when the timeline is built.
        manual = json.loads(json.dumps(body))
        manual['scenes'][1].update(cuts=[{'media_id': clip['id'], 'seconds': 3.5, 'trim_start': 0}, {'media_id': clip['id'], 'seconds': 3.5, 'trim_start': 4}])
        refused = client.post('/api/production/timelines', json=manual)
        assert refused.status_code == 422 and 'cannot be used here' in refused.text
        # After an explicit reviewer clearance, the same placement is accepted.
        cleared = client.put(f"/api/production/media/{clip['id']}/catalog", json={'tags': ['flood', 'rain', 'storm', 'wind', 'waves'], 'reference': '',
                                                                                 'setting_cleared': True, 'setting_note': 'Watched: no signage or landmarks'})
        assert cleared.status_code == 200 and cleared.json()['catalog']['setting_cleared_at']
        saved = client.post('/api/production/timelines', json=manual)
        assert saved.status_code == 200, saved.text
        # Withdrawing clearance blocks the saved timeline at the pre-render check.
        client.put(f"/api/production/media/{clip['id']}/catalog", json={'tags': ['flood'], 'reference': ''})
        blocked = client.post('/api/production/renders', json={'timeline_id': saved.json()['id']})
        assert blocked.status_code == 422 and 'cannot be used here' in blocked.text
        # Nothing about the media itself changed.
        after = client.app.state.store.production_get('media', clip['id'])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest and after['checksum'] == before['checksum'] and not after.get('quarantined')
