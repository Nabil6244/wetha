"""End-to-end production benchmark: voiceover in, finished video out, on this machine.

Uses the synthetic training advisory and a completed alignment fixture so no network or speech model
is needed; everything after alignment (shot planning, visuals, render, audio mix, QC, packaging) is real.
Usage: .venv/bin/python scripts/benchmark-production.py 60 300 600 1800
"""
import io, json, math, os, platform, resource, struct, sys, tempfile, time, wave
from pathlib import Path
from uuid import uuid4
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend' / 'tests')]


def narration(seconds):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
        frames = bytearray()
        for n in range(seconds * 16000):
            frames += struct.pack('<h', round(5000 * math.sin(2 * math.pi * 180 * n / 16000)) if (n // 8000) % 3 else 0)
        wav.writeframes(bytes(frames))
    return stream.getvalue()


def run(client, seconds):
    from test_production import prepare, upload
    _, plan, _ = prepare(client)
    audio = upload(client, narration(seconds), name=f'voice-{seconds}.wav', kind='audio', context='narration').json()
    per = seconds / len(plan['scenes']);frames = [round(per * 30)] * len(plan['scenes'])
    frames[-1] = seconds * 30 - sum(frames[:-1])
    identity = str(uuid4())
    words = {s['id']: [round(i * (f - 10) / max(1, len(s['script_segment'].split()))) for i in range(len(s['script_segment'].split()))] for s, f in zip(plan['scenes'], frames)}
    client.app.state.alignment.jobs[identity] = {'id': identity, 'status': 'completed', 'plan_id': plan['id'], 'narration_id': audio['id'],
        'script_text_checksum': plan['script_text_checksum'], 'audio_checksum': audio['checksum'],
        'result': {'scenes': [{'id': s['id'], 'seconds': f / 30, 'media_id': None, 'trim_start': 0, 'transition': 'cut'} for s, f in zip(plan['scenes'], frames)],
                   'coverage': .98, 'timing_basis': 'Benchmark fixture', 'issues': [], 'word_frames': words}}
    def produce(title):
        start = time.monotonic()
        job = client.post('/api/production/auto', json={'plan_id': plan['id'], 'narration_id': audio['id'], 'title': title}).json()
        while job['status'] in ('queued', 'running'):
            time.sleep(1);job = client.get('/api/production/auto/' + job['id']).json()
        return job, round(time.monotonic() - start, 1)
    job, wall = produce(f'Benchmark {seconds}s')
    if job['status'] != 'succeeded':
        return {'seconds': seconds, 'status': job['status'], 'error': job['error']}
    report = client.get(f"/api/production/renders/{job['render_id']}/report").json()
    rerun, rerun_wall = produce(f'Benchmark {seconds}s')  # identical inputs: every scene should be reused
    rerun_render = client.app.state.store.production_get('renders', rerun['render_id'])
    return {'seconds': seconds, 'status': 'succeeded', 'shots': report['scenes'], 'wall_seconds': wall,
            'realtime_factor': round(seconds / wall, 2), 'stage_seconds': report['timings_seconds'],
            'loudness_lufs': report['checks']['loudness_lufs'], 'errors': report['errors'], 'warnings': report['warnings'],
            'rerun_wall_seconds': rerun_wall, 'rerun_reused_scenes': rerun_render.get('reused_scenes', 0)}


if __name__ == '__main__':
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.production import render_workers
    from app.broadcast import encoder_args
    durations = [int(a) for a in sys.argv[1:]] or [60]
    results = {'machine': {'platform': platform.platform(), 'processor': platform.processor(), 'cpus': os.cpu_count(),
                           'render_workers': render_workers(), 'hardware_encoder_available': encoder_args('auto')[1] != 'libx264'}, 'runs': []}
    for seconds in durations:
        with tempfile.TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp))) as client:
            row = run(client, seconds)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN);own = resource.getrusage(resource.RUSAGE_SELF)
        row['peak_rss_mb'] = {'backend': round(own.ru_maxrss / 1048576, 1), 'largest_child': round(usage.ru_maxrss / 1048576, 1)}
        results['runs'].append(row);print(json.dumps(row), flush=True)
    out = ROOT / 'docs' / 'benchmarks' / 'production-latest.json'
    out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(results, indent=2))
    print('saved', out)
