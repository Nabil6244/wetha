"""Render synthetic 30-second and five-minute previews in an isolated database."""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi.testclient import TestClient
from app.main import create_app


def main():
    output = ROOT / '.local/phase5-validation'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wetha-production-validation-') as temporary:
        with TestClient(create_app(Path(temporary))) as client:
            client.post('/api/training/load').raise_for_status()
            response = client.post('/api/scripts', json={'advisory_id': 'training:cyclone:2'})
            response.raise_for_status()
            script = response.json()
            response = client.post('/api/visuals/plans', json={'script_id': script['id'], 'expected_revision': 1})
            response.raise_for_status()
            plan = response.json()
            for seconds, name in [(30, 'training-30-second'), (300, 'training-5-minute')]:
                per_scene = seconds / len(plan['scenes'])
                if per_scene > 120:
                    raise RuntimeError('Too few source-linked scenes for the selected demo duration.')
                response = client.post('/api/production/timelines', json={'plan_id': plan['id'],
                    'title': 'Synthetic training demonstration', 'scenes': [
                        {'id': scene['id'], 'seconds': per_scene, 'transition': 'fade'} for scene in plan['scenes']]})
                response.raise_for_status()
                timeline = response.json()
                response = client.post('/api/production/renders', json={'timeline_id': timeline['id']})
                response.raise_for_status()
                job = response.json()
                started = time.monotonic()
                last_stage = None
                while time.monotonic() - started < 600:
                    job = next(row for row in client.get('/api/production').json()['renders'] if row['id'] == job['id'])
                    if job['stage'] != last_stage:
                        print(json.dumps({'demo': name, 'stage': job['stage'], 'progress': job['progress']}), flush=True)
                        last_stage = job['stage']
                    if job['status'] not in ('queued', 'running'):
                        break
                    time.sleep(1)
                if job['status'] != 'succeeded':
                    log = Path(temporary) / 'production/renders' / job['id'] / 'ffmpeg.log'
                    raise RuntimeError(f"{job['status']}: {job.get('error')}\n" + (log.read_text()[-3000:] if log.exists() else ''))
                for kind, suffix in [('video', '.mp4'), ('subtitles', '.srt'), ('manifest', '.json')]:
                    shutil.copyfile(client.app.state.production.output_path(job['id'], kind), output / (name + suffix))
                (output / (name + '-validation.json')).write_text(json.dumps(job['validation'], indent=2))
                print(json.dumps({'demo': name, 'validated_seconds': job['validation']['seconds'],
                                  'elapsed_seconds': round(time.monotonic() - started, 1), 'output': str(output / (name + '.mp4'))}), flush=True)


if __name__ == '__main__':
    main()
