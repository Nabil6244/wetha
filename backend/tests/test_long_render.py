"""Phase 5: parallel scenes and constant-cost assembly for long programs."""
import asyncio
import shutil
import subprocess
import pytest
from types import SimpleNamespace
from PIL import Image
from app.production import Production, probe, render_workers

pytestmark = pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg/FFprobe required')
COLORS = ['red', 'blue', 'green', 'yellow', 'white', 'cyan']


def segments(work, seconds, fades):
    """Synthetic scene files in the renderer's layout: after a fade, the next scene carries a 0.3 s lead-in."""
    for index, (length, color) in enumerate(zip(seconds, COLORS)):
        lead = .3 if index and fades[index - 1] else 0
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={color}:s=320x180:r=30',
                        '-frames:v', str(round((length + lead) * 30)), '-pix_fmt', 'yuv420p', str(work / f'scene-{index:03}.mp4')], check=True)


def assemble(work, seconds, fades):
    async def command(job, args, **kwargs):
        subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], cwd=work, check=True)
    stub = SimpleNamespace(command=command)
    timeline = {'presentation': 'broadcast', 'scenes': [{'seconds': s, 'transition': 'fade' if f else 'cut'} for s, f in zip(seconds, fades)]}
    listing = asyncio.run(Production.assemble(stub, {'id': 'job'}, timeline, work))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', listing.name, '-c:v', 'libx264', '-r', '30',
                    '-fps_mode', 'cfr', '-pix_fmt', 'yuv420p', 'program.mp4'], cwd=work, check=True)
    return work / 'program.mp4'


def test_fades_keep_exact_program_length_and_dissolve_between_neighbours(tmp_path):
    seconds = [2, 1.5, 2, 1, 2];fades = [True, False, True, True, False]
    segments(tmp_path, seconds, fades)
    output = assemble(tmp_path, seconds, fades)
    info = probe(output)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    frames = int(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v', '-show_entries', 'stream=nb_read_frames',
                                 '-of', 'csv=p=0', str(output)], capture_output=True, text=True).stdout)
    assert frames == round(sum(seconds) * 30)
    # Mid-fade between red and blue is a blend; the body of each scene is its own colour.
    def colour(second):
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(second), '-i', str(output), '-frames:v', '1', str(tmp_path / 'f.png')], check=True)
        return Image.open(tmp_path / 'f.png').convert('RGB').getpixel((160, 90))
    red, blend, blue = colour(1.0), colour(1.85), colour(2.6)
    assert red[0] > 200 and red[2] < 60
    assert blue[2] > 200 and blue[0] < 60
    assert 60 < blend[0] < 220 and 60 < blend[2] < 220
    assert '.' not in video['r_frame_rate'] and video['r_frame_rate'] == '30/1'


def test_render_workers_respect_override(monkeypatch):
    monkeypatch.setenv('WETHA_RENDER_WORKERS', '3')
    assert render_workers() == 3
    monkeypatch.delenv('WETHA_RENDER_WORKERS')
    assert 1 <= render_workers() <= 4


def test_broadcast_with_fades_renders_in_parallel_and_validates(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_production import prepare, wait_render
    monkeypatch.setenv('WETHA_RENDER_WORKERS', '3')
    with TestClient(create_app(tmp_path)) as client:
        _, _, body = prepare(client)
        body['presentation'] = 'broadcast'
        body['scenes'] = [{**s, 'seconds': 1.5, 'transition': 'fade' if i % 2 == 0 else 'cut'} for i, s in enumerate(body['scenes'])]
        timeline = client.post('/api/production/timelines', json=body)
        assert timeline.status_code == 200, timeline.text
        job = client.post('/api/production/renders', json={'timeline_id': timeline.json()['id']}).json()
        completed = wait_render(client, job['id'], timeout=180)
        assert completed['status'] == 'succeeded', completed.get('error')
        assert abs(completed['validation']['seconds'] - 1.5 * len(body['scenes'])) < .15
        work = tmp_path / 'production/renders' / job['id']
        assert list(work.glob('fade-*.mp4'))
