"""Render a silent, source-linked report through the running desktop API."""
import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True, help='Running desktop backend origin, e.g. http://127.0.0.1:61591')
parser.add_argument('--seconds', type=int, default=300)
parser.add_argument('--presentation', choices=['captioned', 'cinematic'], default='captioned')
parser.add_argument('--music', action='store_true', help='Original local instrumental soundtrack; no voiceover')
args = parser.parse_args()
if not 3 <= args.seconds <= 600:
    parser.error('Use a duration from 3 to 600 seconds.')
output = Path(__file__).resolve().parents[1] / '.local/exports'
output.mkdir(parents=True, exist_ok=True)
with httpx.Client(base_url=args.url.rstrip('/') + '/api', timeout=90) as client:
    def call(path, body=None):
        response = client.get(path) if body is None else client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    for provider in ('nhc',):
        try:
            print(json.dumps({'refresh': call('/providers/' + provider + '/refresh', {})}), flush=True)
        except httpx.HTTPError as error:
            print('Refresh unavailable; cached source labels will remain visible: ' + str(error), flush=True)
    sources = call('/advisories')
    candidates = [a for a in sources if a['provider'] == 'NHC' and a['provenance'] == 'official_fetch'
                  and isinstance(a['facts'].get('longitude'), (int, float)) and isinstance(a['facts'].get('latitude'), (int, float))
                  and -100 <= a['facts']['longitude'] <= -65 and 5 <= a['facts']['latitude'] <= 40]
    if not candidates:
        raise RuntimeError('No officially fetched advisory with a reported center in the satellite region.')
    advisory = max(candidates, key=lambda a: a['issued_at'])
    script = call('/scripts', {'advisory_id': advisory['id']})
    if any(c['status'] == 'requires_verification' for c in script['claims']):
        raise RuntimeError('Resolve unsupported script claims before rendering.')
    plan = call('/visuals/plans', {'script_id': script['id'], 'expected_revision': script['revision'], 'style': 'map'})
    # Allocate the exact frame count, with the same 1–120 second per-scene bounds as the UI.
    scenes = plan['scenes']
    if not len(scenes) <= args.seconds <= len(scenes) * 120:
        raise RuntimeError('Requested duration exceeds scene timing limits.')
    weights = [max(1, len(s['script_segment'].split())) for s in scenes]
    counts = [30] * len(scenes)
    for _ in range(args.seconds * 30 - sum(counts)):
        index = min((i for i in range(len(scenes)) if counts[i] < 3600), key=lambda i: counts[i] / weights[i])
        counts[index] += 1
    title = advisory['title'] + ' · five-minute satellite report' if args.seconds == 300 else advisory['title'] + ' · satellite report'
    if args.presentation == 'cinematic':
        title = advisory['title'] + ' · Weather Brief'
    timeline = call('/production/timelines', {'plan_id': plan['id'], 'title': title, 'satellite_context': True, 'presentation': args.presentation, 'music': args.music,
        'scenes': [{'id': s['id'], 'seconds': frames / 30, 'transition': 'fade'} for s, frames in zip(scenes, counts)]})
    job = call('/production/renders', {'timeline_id': timeline['id']})
    print(json.dumps({'render_id': job['id'], 'title': title, 'seconds': timeline['seconds']}), flush=True)
    last_stage = None
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        job = next(r for r in call('/production')['renders'] if r['id'] == job['id'])
        if job['stage'] != last_stage:
            print(json.dumps({'stage': job['stage'], 'progress': job['progress']}), flush=True)
            last_stage = job['stage']
        if job['status'] not in ('queued', 'running'):
            break
        time.sleep(3)
    if job['status'] != 'succeeded':
        raise RuntimeError(str(job.get('error') or 'Render did not complete before timeout.'))
    stem = ('weather-cinematic-five-minute' if args.seconds == 300 else 'weather-cinematic') if args.presentation == 'cinematic' else ('real-noaa-five-minute-report' if args.seconds == 300 else 'real-noaa-report')
    for kind, suffix in [('video', '.mp4'), ('subtitles', '.srt'), ('manifest', '.json')]:
        response = client.get('/production/renders/' + job['id'] + '/' + kind)
        response.raise_for_status()
        (output / (stem + suffix)).write_bytes(response.content)
    (output / (stem + '-validation.json')).write_text(json.dumps(job['validation'], indent=2))
    print(json.dumps({'file': str(output / (stem + '.mp4')), 'render_id': job['id'], 'validation': job['validation']}), flush=True)
