"""Phase 4 finish: transitions, audio bed and transition sounds, captions, grade."""
import io
import math
import shutil
import struct
import wave
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app import audio_polish, broadcast
from app.production import caption_pages
from app.visual_states import transitions


def shot(identity, story='a', family='map', **extra):
    parameters = {'source_advisory_id': story}
    if family == 'card':
        parameters['visual_state'] = 'stat_card'
    if family == 'chart':
        parameters['report_graphs'] = {'charts': []}
    return {'id': identity, 'media_id': None, 'cuts': [], 'transition': 'cut', 'parameters': parameters,
            'direction': {'scene_type': 'region_focus'}, **extra}


def test_transitions_follow_the_edit_grammar():
    rows = [shot('0'), shot('1', family='card'), shot('2'), shot('3', family='chart'), shot('4'),
            shot('5', story='b'), shot('6', cuts=[{'media_id': 'x'}]), shot('7'),
            shot('8', parent_scene_id='p'), shot('9', parent_scene_id='p')]
    rows[9]['parameters']['camera_span'] = [.5, 1]
    transitions(rows)
    kinds = [r['parameters'].get('transition_in') for r in rows]
    assert kinds[:6] == [None, 'push', 'wipe', 'dissolve', 'wipe', 'story']
    assert kinds[6] is None and kinds[7] is None          # footage keeps hard cuts on both sides
    assert kinds[9] is None                               # a continuous camera hold is not interrupted


def test_transition_pictures_keep_size_and_move_between_shots():
    red, blue = Image.new('RGB', (1920, 1080), 'red'), Image.new('RGB', (1920, 1080), 'blue')
    for kind in ('dissolve', 'push', 'story', 'wipe'):
        start, end = broadcast.blend(kind, red, blue, .02), broadcast.blend(kind, red, blue, .98)
        assert start.size == end.size == (1920, 1080)
        assert start.getpixel((1700, 540))[0] > 200 and end.getpixel((200, 540))[2] > 200


def test_transition_sounds_land_on_cues_and_stay_silent_elsewhere(tmp_path):
    path = tmp_path / 'cues.wav'
    audio_polish.write_cues(path, [2.0, 5.0, 5.1], 8)
    with wave.open(str(path)) as track:
        assert track.getnframes() == 8 * audio_polish.RATE
        samples = struct.unpack('<%dh' % track.getnframes(), track.readframes(track.getnframes()))
    window = lambda a, b: max(abs(v) for v in samples[round(a * audio_polish.RATE):round(b * audio_polish.RATE)])
    assert window(1.85, 2.3) > 500 and window(4.85, 5.3) > 500
    assert window(0, 1.8) == 0 and window(3, 4.8) == 0 and window(6, 8) == 0


def test_captions_are_two_short_lines():
    pages = caption_pages('Hurricane conditions are expected within the warning area tonight, with dangerous surge along the coast and flooding rain inland through Friday.')
    assert all(len(p.split('\n')) <= 2 and all(len(line) <= 42 for line in p.split('\n')) for p in pages)
    assert ' '.join(' '.join(p.split('\n')) for p in pages).startswith('Hurricane conditions')


@pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg/FFprobe required')
def test_narrated_broadcast_mixes_a_ducked_music_bed(tmp_path):
    from app.main import create_app
    from test_production import prepare, upload, wait_render
    with TestClient(create_app(tmp_path)) as client:
        _, plan, body = prepare(client)
        seconds = 2 * len(body['scenes'])
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
            # Speech-like bursts: one second of tone, one second of pause.
            wav.writeframes(b''.join(struct.pack('<h', round(8000 * math.sin(2 * math.pi * 220 * n / 16000)) if (n // 16000) % 2 == 0 else 0)
                                     for n in range(seconds * 16000)))
        narration = upload(client, stream.getvalue(), name='voice.wav', kind='audio', context='narration').json()
        body.update(presentation='broadcast', narration_id=narration['id'], narration_verified=True,
                    scenes=[{**s, 'seconds': 2} for s in body['scenes']])
        timeline = client.post('/api/production/timelines', json=body)
        assert timeline.status_code == 200, timeline.text
        assert timeline.json()['music_bed'] is True
        job = client.post('/api/production/renders', json={'timeline_id': timeline.json()['id']}).json()
        completed = wait_render(client, job['id'])
        work = tmp_path / 'production/renders' / job['id']
        assert completed['status'] == 'succeeded', completed.get('error')
        assert (work / 'mix.wav').exists()
        with wave.open(str(work / 'mix.wav')) as mix:
            rate = mix.getframerate();channels = mix.getnchannels()
            frames = mix.readframes(mix.getnframes())
        samples = struct.unpack('<%dh' % (len(frames) // 2), frames)
        level = lambda a, b: max(abs(v) for v in samples[round(a * rate) * channels:round(b * rate) * channels])
        # The bed is audible in pauses but sits well under the voice.
        assert 0 < level(1.3, 1.9) < level(0.3, 0.9)
