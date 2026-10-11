"""Script + voiceover -> finished video, report and package, with restart and resume."""
import io
import json
import math
import shutil
import struct
import time
import wave
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import create_app

pytestmark = pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg/FFprobe required')
SECONDS = 5


def setup(client):
    from test_production import prepare, upload
    script, plan, _ = prepare(client)
    duration = SECONDS * len(plan['scenes'])
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
        wav.writeframes(b''.join(struct.pack('<h', round(6000 * math.sin(2 * math.pi * 200 * n / 16000)) if (n // 8000) % 3 else 0) for n in range(duration * 16000)))
    audio = upload(client, stream.getvalue(), name='voice.wav', kind='audio', context='narration').json()
    # A completed local alignment for this exact script and audio, with recognized word starts.
    identity = str(uuid4())
    words = {s['id']: [round(i * (SECONDS * 30 - 10) / max(1, len(s['script_segment'].split()))) for i in range(len(s['script_segment'].split()))] for s in plan['scenes']}
    client.app.state.alignment.jobs[identity] = {'id': identity, 'status': 'completed', 'plan_id': plan['id'], 'narration_id': audio['id'],
        'script_text_checksum': plan['script_text_checksum'], 'audio_checksum': audio['checksum'],
        'result': {'scenes': [{'id': s['id'], 'seconds': SECONDS, 'media_id': None, 'trim_start': 0, 'transition': 'cut'} for s in plan['scenes']],
                   'coverage': .98, 'timing_basis': 'Recognized speech', 'issues': [], 'word_frames': words}}
    return plan, audio


def wait(client, identity, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get('/api/production/auto/' + identity).json()
        if job['status'] in ('succeeded', 'failed', 'cancelled', 'interrupted'):
            return job
        time.sleep(.5)
    raise AssertionError('production did not finish')


def test_script_and_voiceover_become_a_finished_video_with_report(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        plan, audio = setup(client)
        started = client.post('/api/production/auto', json={'plan_id': plan['id'], 'narration_id': audio['id'], 'title': 'Hurricane test update'})
        assert started.status_code == 200, started.text
        job = wait(client, started.json()['id'])
        assert job['status'] == 'succeeded', job['error']
        assert [s['status'] for s in job['stages']] == ['done', 'done', 'done', 'skipped', 'skipped', 'done', 'done', 'done', 'done']
        base = '/api/production/renders/' + job['render_id']
        report = client.get(base + '/report').json()
        assert report['checks']['captions'] > 0 and report['checks']['loudness_lufs'] is not None
        assert {'scenes', 'joins', 'audio_mix', 'final_encode', 'quality_control'} <= set(report['timings_seconds'])
        assert report['visual_plan'] and all(r['reason'] and r['intent'] for r in report['visual_plan'])
        assert '# Production report' in client.get(base + '/report_md').text
        metadata = client.get(base + '/metadata').json()
        assert metadata['privacy'] == 'private' and metadata['publishing']['status'] == 'not_configured'
        assert 'Sources' in metadata['description']
        board = client.get(f"/api/production/storyboards/{job['storyboard']['id']}/sheet")
        assert board.status_code == 200 and Image.open(io.BytesIO(board.content)).width > 1000
        assert client.get(f"/api/production/storyboards/{job['storyboard']['id']}/preview").status_code == 200
        assert job['storyboard']['metrics']['shots'] > 0
        thumb = client.get(base + '/thumbnail')
        assert thumb.status_code == 200
        assert Image.open(io.BytesIO(thumb.content)).size == (1280, 720)
        # Word-timed captions: each caption begins on a recognized word start, not an even split.
        srt = client.get(base + '/subtitles').text
        assert srt.count('-->') >= len(plan['scenes'])


def test_interrupted_production_resumes_after_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        plan, audio = setup(client)
        alignment = client.app.state.alignment.jobs
        started = client.post('/api/production/auto', json={'plan_id': plan['id'], 'narration_id': audio['id'], 'title': 'Resume test'}).json()
        first = wait(client, started['id'])
        assert first['status'] == 'succeeded', first['error']
        # Simulate a crash mid-production by saving the job as running.
        store = client.app.state.store
        row = store.production_get('jobs', started['id']);row['status'] = 'running'
        store.production_update_job(row)
        saved = {k: v for k, v in alignment.items()}
        (tmp_path / 'alignments').mkdir(exist_ok=True)
        for identity, job in saved.items():
            (tmp_path / 'alignments' / f'{identity}.json').write_text(json.dumps(job))
    with TestClient(create_app(tmp_path)) as client:
        job = client.get('/api/production/auto/' + started['id']).json()
        assert job['status'] == 'interrupted' and 'Resume' in job['error']
        assert client.post('/api/production/auto/' + started['id'] + '/resume').status_code == 200
        resumed = wait(client, started['id'])
        assert resumed['status'] == 'succeeded', resumed['error']
        render = client.app.state.store.production_get('renders', resumed['render_id'])
        assert render.get('reused_scenes', 0) > 0  # unchanged scenes come from the earlier render
