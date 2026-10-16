"""Documentary checks use synthetic footage and projected map coordinates."""
import asyncio
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from app.broadcast import fit_bounds, project
from app.documentary import render, viewport
from app.main import create_app
from app.production import probe


def test_traveling_camera_preserves_projection_aspect_and_endpoints():
    start = (-84, 27, -72, 39)
    end = (-81, 30, -75, 36)
    assert viewport(start, end, 0) == pytest.approx(fit_bounds(start))
    assert viewport(start, end, 1) == pytest.approx(fit_bounds(end))
    for t in (0, .25, .5, .75, 1):
        west, south, east, north = viewport(start, end, t)
        x0, y0 = project(west, north)
        x1, y1 = project(east, south)
        assert (x1-x0)/(y1-y0) == pytest.approx(1920/1080)
    assert viewport(start, end, .5) != viewport(start, end, 0)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_footage_overlay_keeps_all_picture_frames_and_moving_source(tmp_path):
    source = tmp_path/'synthetic.mp4'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=30:duration=2', '-c:v', 'libx264', str(source)], check=True)
    row = {'seconds': 1, 'trim_start': .5, 'text': 'Synthetic motion test',
           'context': 'SYNTHETIC TEST', 'credit': 'Owned test pattern',
           'stat': {'label': 'TEST VALUE', 'value': '85', 'detail': 'A static reported value'}}
    output = tmp_path/'documentary.mp4'
    asyncio.run(render(row, output, lambda _: b'', source))
    video = next(s for s in probe(output)['streams'] if s['codec_type']=='video')
    assert (video['width'], video['height'], int(video['nb_frames'])) == (1920, 1080, 30)
    assert float(video['duration']) == pytest.approx(1)
    frames = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-vf',
                             'crop=300:300:1300:500,fps=2', '-f', 'framemd5', '-'],
                            check=True, capture_output=True, text=True).stdout
    hashes = [line.split(',')[-1].strip() for line in frames.splitlines() if not line.startswith('#')]
    assert len(hashes) == 2 and hashes[0] != hashes[1]


def test_documentary_route_rejects_unknown_artifacts_and_serves_captions(tmp_path):
    subtitles = tmp_path/'captions.srt'
    subtitles.write_text('1\n00:00:00,000 --> 00:00:03,000\nSynthetic caption\n')
    app = create_app(tmp_path/'app')
    with TestClient(app) as client:
        app.state.production.documentary_info = lambda: {'available': False}
        assert client.get('/api/production/documentary/video').status_code == 404
        app.state.production.documentary_info = lambda: {'available': True}
        app.state.production.documentary_path = lambda kind: subtitles
        assert client.get('/api/production/documentary/unknown').status_code == 404
        response = client.get('/api/production/documentary/subtitles')
        assert response.status_code == 200
        assert response.content == subtitles.read_bytes()   # served byte for byte; Windows text mode would turn \n into \r\n
        assert response.headers['content-type'].startswith('application/x-subrip')
