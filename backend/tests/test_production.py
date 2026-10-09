"""Production tests use synthetic media, never real observation footage."""
import io
import json
import shutil
import subprocess
import time
import wave
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.production import probe

pytestmark = pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg/FFprobe required')


def prepare(client):
    client.post('/api/training/load')
    script = client.post('/api/scripts', json={'advisory_id': 'training:cyclone:2'}).json()
    plan = client.post('/api/visuals/plans', json={'script_id': script['id'], 'expected_revision': 1}).json()
    body = {'plan_id': plan['id'], 'title': 'Synthetic production test', 'scenes': [
        {'id': s['id'], 'seconds': 1, 'transition': 'cut'} for s in plan['scenes']]}
    return script, plan, body


def image():
    buffer = io.BytesIO()
    Image.new('RGB', (160, 90), '#1e554e').save(buffer, format='PNG')
    return buffer.getvalue()


def upload(client, content=None, **changes):
    metadata = {'name': 'synthetic.png', 'kind': 'image', 'context': 'illustrative',
                'license': 'Owned synthetic test image', 'attribution': 'Test creator',
                'source': 'Synthetic test fixture', 'rights_confirmed': True, **changes}
    return client.post('/api/production/media', content=image() if content is None else content,
                       headers={'X-Media-Metadata': quote(json.dumps(metadata)), 'Content-Type': 'application/octet-stream'})


def wait_render(client, identity, timeout=90):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        row = next(r for r in client.get('/api/production').json()['renders'] if r['id'] == identity)
        if row['status'] not in ('queued', 'running'):
            return row
        time.sleep(0.15)
    pytest.fail('Render did not complete before timeout')


def test_broadcast_footage_sequence_renders_and_validates_each_cut(tmp_path):
    video = tmp_path/'sequence-fixture.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=teal:s=320x180:r=30:d=8','-c:v','libx264','-threads','2',str(video)],check=True)
    with TestClient(create_app(tmp_path/'app')) as client:
        _, _, body = prepare(client)
        media = upload(client,video.read_bytes(),name='sequence-fixture.mp4',kind='video').json()
        cuts = [{'media_id':media['id'],'seconds':3,'trim_start':0},{'media_id':media['id'],'seconds':3,'trim_start':3}]
        body['presentation']='broadcast'
        body['scenes'][0].update(seconds=6,cuts=cuts)
        assert client.post('/api/production/check',json=body).json()['ready']
        bad = json.loads(json.dumps(body));bad['scenes'][0]['cuts'][1]['trim_start']=6
        assert not client.post('/api/production/check',json=bad).json()['ready']
        bad = json.loads(json.dumps(body));bad['scenes'][0]['seconds']=5
        assert not client.post('/api/production/check',json=bad).json()['ready']
        timeline = client.post('/api/production/timelines',json=body).json()
        job = client.post('/api/production/renders',json={'timeline_id':timeline['id']}).json()
        completed = wait_render(client,job['id'])
        assert completed['status']=='succeeded',completed['error']
        manifest = client.get(f"/api/production/renders/{job['id']}/manifest").json()
        assert len(manifest['timeline']['scenes'][0]['cuts'])==2
        video_info=probe(client.app.state.production.output_path(job['id'],'video'))
        stream=next(s for s in video_info['streams'] if s['codec_type']=='video')
        assert float(stream['duration'])==pytest.approx(manifest['timeline']['seconds'],abs=.1)
        assert int(stream['nb_frames'])==round(manifest['timeline']['seconds']*30)
        assert media['id'] in manifest['media']


def test_import_rights_real_format_duplicate_repair_and_checksum(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert upload(client, rights_confirmed=False).status_code == 422
        assert upload(client, license=' ').status_code == 422
        assert upload(client, name='../secret.png').status_code == 422
        assert upload(client, b'not media').status_code == 422
        broken_png = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000d49444154789c63606060000000040001f5a77c550000000049454e44ae426082')
        assert upload(client, broken_png).status_code == 422
        assert upload(client, context='narration').status_code == 422
        response = upload(client)
        assert response.status_code == 200
        asset = response.json()
        assert asset['width'] == 160 and asset['seconds'] is None
        assert upload(client).json()['duplicate'] is True
        assert upload(client, license='Different license').status_code == 422
        url = '/api/production/media/' + asset['id'] + '/file'
        assert client.get(url).content == image()
        path = tmp_path / 'production/media' / asset['filename']
        path.write_bytes(b'corrupt')
        assert client.get(url).status_code == 422
        assert upload(client).json()['duplicate'] is True
        assert client.get(url).content == image()
        assert len(client.get('/api/production').json()['media']) == 1
        assert client.post('/api/production/media', content=image(), headers={'Origin': 'https://evil.test'}).status_code == 403


def test_import_size_limit_cleans_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr('app.production.MAX_UPLOAD', 10)
    with TestClient(create_app(tmp_path)) as client:
        assert upload(client).status_code == 422
        assert list((tmp_path / 'production/media').iterdir()) == []


def test_timeline_preserves_revision_claim_order_and_explicit_timing(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        script, plan, body = prepare(client)
        reordered = {**body, 'scenes': list(reversed(body['scenes']))}
        assert client.post('/api/production/timelines', json=reordered).status_code == 422
        unknown = {**body, 'scenes': [{**s, 'media_id': 'missing'} for s in body['scenes']]}
        assert client.post('/api/production/timelines', json=unknown).status_code == 404
        invented = {**body, 'scenes': [{**s, 'script_segment': 'Invented forecast'} for s in body['scenes']]}
        assert client.post('/api/production/timelines', json=invented).status_code == 422
        zero = {**body, 'scenes': [{**s, 'seconds': 0} for s in body['scenes']]}
        assert client.post('/api/production/timelines', json=zero).status_code == 422
        timeline = client.post('/api/production/timelines', json=body).json()
        assert timeline['broadcast_eligible'] is False and timeline['audio_mode'] == 'silent'
        assert [s['script_segment'] for s in timeline['scenes']] == [s['script_segment'] for s in plan['scenes']]
        client.post('/api/scripts/' + script['id'] + '/revisions', json={'expected_revision': 1,
                    'editor': 'Test editor', 'note': 'Unsupported addition', 'text': script['text'] + '\n\nAn unsupported forecast.'})
        assert client.post('/api/production/renders', json={'timeline_id': timeline['id']}).status_code == 409
        assert client.post('/api/production/timelines', json=body).status_code == 409
        latest = client.get('/api/scripts/' + script['id']).json()
        plan2 = client.post('/api/visuals/plans', json={'script_id': script['id'], 'expected_revision': latest['revision']}).json()
        unsupported = {**body, 'plan_id': plan2['id'], 'scenes': [{'id': s['id'], 'seconds': 1} for s in plan2['scenes']]}
        assert client.post('/api/production/timelines', json=unsupported).status_code == 422


def test_real_render_image_footage_audio_export_and_persistence(tmp_path):
    fixture = tmp_path / 'synthetic.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=30',
                    '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(fixture)], check=True)
    with TestClient(create_app(tmp_path)) as client:
        _, _, body = prepare(client)
        still = upload(client).json()
        clip = upload(client, fixture.read_bytes(), name='synthetic.mp4', kind='video', context='archival').json()
        body['scenes'][0].update(media_id=still['id'], transition='fade')
        body['scenes'][1].update(media_id=clip['id'], trim_start=0.5)
        too_short = json.loads(json.dumps(body))
        too_short['scenes'][1]['seconds'] = 3
        assert client.post('/api/production/timelines', json=too_short).status_code == 422
        seconds = len(body['scenes'])
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(b'\0\0' * seconds * 16000)
        narration = upload(client, stream.getvalue(), name='narration.wav', kind='audio', context='narration').json()
        body.update(narration_id=narration['id'])
        assert client.post('/api/production/timelines', json=body).status_code == 422
        body['narration_verified'] = True
        bad_audio = {**body, 'scenes': [{**s, 'seconds': 2} for s in body['scenes']]}
        assert client.post('/api/production/timelines', json=bad_audio).status_code == 422
        timeline_response = client.post('/api/production/timelines', json=body)
        assert timeline_response.status_code == 200, timeline_response.text
        timeline = timeline_response.json()
        job = client.post('/api/production/renders', json={'timeline_id': timeline['id']}).json()
        completed = wait_render(client, job['id'])
        log = tmp_path / 'production/renders' / job['id'] / 'ffmpeg.log'
        assert completed['status'] == 'succeeded', completed.get('error', '') + '\n' + log.read_text()
        assert completed['validation']['decoded'] is True
        assert completed['snapshot']['source_label'] == 'training'
        assert completed['validation']['audio_mode'] == 'imported_narration'
        base = '/api/production/renders/' + job['id']
        assert client.get(base + '/video', headers={'Range': 'bytes=0-99'}).status_code == 206
        assert 'Synthetic training' in client.get(base + '/subtitles').text or 'synthetic' in client.get(base + '/subtitles').text
        manifest = client.get(base + '/manifest').json()
        assert manifest['broadcast_eligible'] is False
        assert len(manifest['media']) == 3
        assert manifest['output']['height'] == 1080
        assert client.get('/api/dashboard').json()['stats']['programs'] == 1
        output = tmp_path / 'production/renders' / job['id'] / 'program.mp4'
        info = probe(output)
        assert next(s for s in info['streams'] if s['codec_type'] == 'video')['r_frame_rate'] == '30/1'
        output.write_bytes(b'corrupt')
        assert client.get(base + '/video').status_code == 422
    with TestClient(create_app(tmp_path)) as client:
        state = client.get('/api/production').json()
        assert len(state['timelines']) == 1 and len(state['media']) == 3
        assert state['renders'][0]['status'] == 'succeeded'


def test_cancel_and_restart_durable_job_state(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _, _, body = prepare(client)
        timeline = client.post('/api/production/timelines', json=body).json()
        job = client.post('/api/production/renders', json={'timeline_id': timeline['id']}).json()
        cancelled = client.post('/api/production/renders/' + job['id'] + '/cancel')
        assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
        store = client.app.state.store
        saved = store.production_get('renders', job['id'])
        saved.update(status='running')
        store.production_update_render(saved)
    with TestClient(create_app(tmp_path)) as client:
        saved = client.get('/api/production').json()['renders'][0]
        assert saved['status'] == 'failed' and 'restart' in saved['error']
        assert client.get('/api/production/renders/' + job['id'] + '/video').status_code == 422


def test_retry_reuses_verified_segments(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        _, _, body = prepare(client)
        timeline = client.post('/api/production/timelines', json=body).json()
        engine = client.app.state.production
        original = engine.command
        async def fail_assembly(job, args, timeout=600, **kwargs):
            if 'concat' in args:
                raise ValueError('Synthetic assembly failure')
            await original(job, args, timeout, **kwargs)
        engine.command = fail_assembly
        job = client.post('/api/production/renders', json={'timeline_id': timeline['id']}).json()
        failed = wait_render(client, job['id'])
        assert failed['status'] == 'failed' and failed['cache']
        segments = sorted((tmp_path / 'production/renders' / job['id']).glob('scene-*.mp4'))
        stamps = [p.stat().st_mtime_ns for p in segments]
        engine.command = original
        assert client.post('/api/production/renders/' + job['id'] + '/retry').status_code == 200
        completed = wait_render(client, job['id'])
        assert completed['status'] == 'succeeded', completed['error']
        assert [p.stat().st_mtime_ns for p in segments] == stamps
        assert completed['attempts'] == 2


def test_satellite_snapshot_render_pruning_and_corruption(tmp_path, monkeypatch):
    from types import SimpleNamespace
    app = create_app(tmp_path)
    with TestClient(app) as client:
        script, plan, body = prepare(client)
        store = app.state.store
        production = app.state.production
        # Synthetic observations exercise the NOAA pipeline without downloading imagery.
        original_advisory = store.advisory
        monkeypatch.setattr(store, 'advisory', lambda identity: SimpleNamespace(provider='NHC', issued_at=__import__('datetime').datetime.fromisoformat('2026-10-08T09:00:00+00:00'), facts={'longitude': -80, 'latitude': 25}) if identity == 'context-fixture' else original_advisory(identity))
        original_pin = production.pin_observations
        monkeypatch.setattr(production, 'pin_observations', lambda script: original_pin({**script, 'advisory_id': 'context-fixture'}))
        assert client.post('/api/production/timelines', json={**body, 'satellite_context': True}).status_code == 422
        for minute in ('00', '05'):
            store.save_visual_asset({'kind': 'goes', 'source_url': 'https://example.test/synthetic-' + minute + '.png',
                'observed_at': '2026-10-08T09:' + minute + ':00+00:00', 'content_type': 'image/png',
                'metadata': {'attribution': 'Synthetic NOAA pipeline test'}}, image())
        response = client.post('/api/production/timelines', json={**body, 'satellite_context': True, 'presentation': 'cinematic', 'music': True})
        assert response.status_code == 200, response.text
        timeline = response.json()
        observations = timeline['scenes'][0]['observations']
        assert len(observations) == 2
        assert observations[0]['observed_at'] < observations[1]['observed_at']
        assert 'issue_time_offset_seconds' in observations[0]
        with store.connection() as conn:
            conn.execute('DELETE FROM visual_assets')
        job = client.post('/api/production/renders', json={'timeline_id': timeline['id']}).json()
        completed = wait_render(client, job['id'])
        assert completed['status'] == 'succeeded', completed['error']
        assert completed['validation']['decoded']
        manifest = client.get('/api/production/renders/' + job['id'] + '/manifest').json()
        assert manifest['timeline']['scenes'][0]['observations'] == observations
        assert 'regional context' in manifest['quality_warnings'][0]
        assert manifest['presentation_beats'] and manifest['music']['creator'] == 'Weather Intelligence Studio'
        assert completed['validation']['audio_mode'] == 'local_instrumental'
        production.observation_path(observations[0]).write_bytes(b'corrupted')
        response = client.post('/api/production/renders', json={'timeline_id': timeline['id']})
        assert response.status_code == 422 and 'imagery is missing or changed' in response.text


def test_cinematic_forecast_keeps_complete_sentences():
    from app.cinematic import beats
    text = ('On the forecast track, the storm is expected to pass north of the peninsula later today '
            'and make landfall along the northern coast within the warning area late Friday or early Saturday.')
    result = beats({'title': 'Synthetic presentation test'}, {'type': 'storm_track',
        'script_segment': 'Official forecast guidance, quoted from this advisory:\n' + text})
    assert [shot['value'] for shot in result] == [text]
    assert result[0]['label'] == 'NHC FORECAST GUIDANCE'


def test_youtube_reuse_record_short_cut_and_broadcast_footage(tmp_path):
    from app.contracts import MediaImportMetadata
    from pydantic import ValidationError
    metadata={'name':'youtube-test.mp4','kind':'video','context':'illustrative',
        'license':'Synthetic creator permission for test','attribution':'Synthetic fixture creator',
        'source':'https://youtu.be/AbCdEf012_-?t=12','rights_confirmed':True,
        'source_provider':'youtube','reuse_basis':'permission','reuse_evidence':'Synthetic written permission record',
        'preferred_clip_seconds':3.5}
    parsed=MediaImportMetadata.model_validate(metadata)
    assert parsed.source=='https://www.youtube.com/watch?v=AbCdEf012_-'
    for bad in ({'source':'https://youtube.com/@channel'},{'source':'https://youtube.com.evil.test/watch?v=AbCdEf012_-'},
                {'reuse_evidence':''},{'reuse_basis':'public_domain'},{'kind':'image'},{'preferred_clip_seconds':5}):
        with pytest.raises(ValidationError):MediaImportMetadata.model_validate({**metadata,**bad})
    clip=tmp_path/'synthetic-source.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=teal:s=160x90:r=30:d=6',
        '-c:v','libx264','-pix_fmt','yuv420p',str(clip)],check=True)
    with TestClient(create_app(tmp_path)) as client:
        _,_,body=prepare(client)
        response=upload(client,clip.read_bytes(),**metadata)
        assert response.status_code==200,response.text
        asset=response.json()
        assert asset['source']==parsed.source and asset['reuse_evidence']==metadata['reuse_evidence']
        assert upload(client,clip.read_bytes(),**metadata).json()['duplicate']
        modified={**metadata,'reuse_evidence':'Different permission record'}
        assert upload(client,clip.read_bytes(),**modified).status_code==422
        body.update(presentation='broadcast')
        body['scenes'][0].update(media_id=asset['id'],seconds=3.5,trim_start=1)
        timeline=client.post('/api/production/timelines',json=body).json()
        assert timeline['scenes'][0]['direction']['scene_type']=='ground_footage'
        assert 'not verified' in timeline['scenes'][0]['direction']['fallback']
        job=client.post('/api/production/renders',json={'timeline_id':timeline['id']}).json()
        result=wait_render(client,job['id'])
        assert result['status']=='succeeded',result['error']
        manifest=client.get('/api/production/renders/'+job['id']+'/manifest').json()
        assert manifest['media'][asset['id']]['source_provider']=='youtube'
        assert manifest['media'][asset['id']]['preferred_clip_seconds']==3.5
        assert result['validation']['decoded']
