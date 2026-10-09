#!/usr/bin/env python3
"""Edit licensed local footage with the verified historical benchmark; no paid APIs."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.broadcast import label
from app.cinematic import score_filter
from app.production import checksum, probe


def ffmpeg(args):
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', *args], check=True)


def run():
    pool = ROOT / '.local/media-pool'
    output = ROOT / '.local/exports/mixed-sample'
    benchmark = ROOT / '.local/exports/phase7'
    output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((pool / 'catalog.json').read_text())
    for asset in catalog['assets']:
        if checksum(pool / asset['filename']) != asset['checksum']:
            raise ValueError('Media differs from the reviewed catalogue: ' + asset['filename'])
    evidence = json.loads((benchmark / 'manifest.json').read_text())
    if checksum(benchmark / 'phase7-isaias-30s.mp4') != evidence['output']['checksum']:
        raise ValueError('Historical benchmark checksum mismatch; rerun render-benchmark.py.')
    # Use the validated final benchmark rather than unvalidated intermediate caches.
    official = benchmark / 'phase7-isaias-30s.mp4'
    shots = [
        ('rain-wind-4436187.mp4', 2, 4, 'REAL WEATHER / HISTORICAL REPORT', 'ILLUSTRATIVE · Startup MrParag / Pexels · not Isaias footage'),
        (None, 5.3, 4, None, None),
        (None, 10.3, 4, None, None),
        (None, 15.6, 4, None, None),
        ('st-lucia-irma-waves.webm', 5, 4, 'COASTAL CONDITIONS / ARCHIVAL EXAMPLE', 'Irma · St. Lucia · 05 SEP 2017 · Bruce and Tammy Swart · CC BY 3.0'),
        ('storm-sea-1879456.mp4', 6, 4, 'ROUGH SEAS / ILLUSTRATIVE FOOTAGE', 'Peggy Johnson Philip Waikoloa / Pexels · not Isaias footage'),
        (None, 25.5, 4, None, None),
        (None, 0.5, 2, 'ISAIAS / 85 MPH BEFORE LANDFALL', 'HISTORICAL · 04 AUG 2020, 03 UTC · NOAA / NHC advisory 28'),
    ]
    edit = []
    for i, (filename, start, seconds, headline, credit) in enumerate(shots):
        source = pool / filename if filename else official
        args = ['-ss', str(start), '-i', str(source)]
        base = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1'
        if headline:
            overlay = Image.new('RGBA', (1920, 1080))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((0, 905, 1920, 1080), fill=(6, 23, 36, 240))
            label(draw, (65, 930), headline, 43)
            label(draw, (65, 1000), credit, 25, '#a8c4d0')
            if filename == 'st-lucia-irma-waves.webm':
                label(draw, (65, 1043), 'youtube.com/watch?v=f5mtyHSyUp8 · creativecommons.org/licenses/by/3.0 · trimmed; audio removed', 20, '#a8c4d0')
            overlay_path = output / f'overlay-{i}.png'
            overlay.save(overlay_path)
            args += ['-loop', '1', '-i', str(overlay_path), '-filter_complex', f'[0:v]{base}[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]', '-map', '[v]']
        else:
            args += ['-vf', base, '-map', '0:v:0']
        segment = output / f'shot-{i}.mp4'
        key = hashlib.sha256(json.dumps(shots[i]).encode() + source.read_bytes() + Path(__file__).read_bytes()).hexdigest()
        marker = segment.with_suffix('.sha256')
        valid = segment.exists() and marker.exists() and marker.read_text() == key + ':' + checksum(segment)
        print(f'Shot {i + 1}/8: ' + ('cached' if valid else 'rendering'), flush=True)
        if not valid:
            ffmpeg(args + ['-t', str(seconds), '-an', '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', str(segment)])
            marker.write_text(key + ':' + checksum(segment))
        edit.append({'start_seconds': sum(x['duration'] for x in edit), 'duration': seconds, 'source': filename or 'verified historical benchmark', 'source_trim_start': start, 'headline': headline, 'credit': credit})
    concat = output / 'concat.txt'
    concat.write_text(''.join(f"file 'shot-{i}.mp4'\n" for i in range(8)))
    video = output / 'weather-mixed-30s.mp4'
    ffmpeg(['-f', 'concat', '-safe', '0', '-i', str(concat), '-f', 'lavfi', '-i', score_filter(30), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-af', 'loudnorm=I=-22:TP=-2:LRA=9,afade=t=in:d=0.5,afade=t=out:st=28:d=2', '-c:a', 'aac', '-ar', '48000', '-t', '30', '-movflags', '+faststart', str(video)])
    info = probe(video)
    v = next(x for x in info['streams'] if x['codec_type'] == 'video')
    assert (v['width'], v['height'], v['r_frame_rate']) == (1920, 1080, '30/1')
    assert abs(float(info['format']['duration']) - 30) < 0.05
    qc = subprocess.run(['ffmpeg', '-hide_banner', '-xerror', '-i', str(video), '-vf', 'blackdetect=d=1:pix_th=0.005:pic_th=0.995', '-f', 'null', '-'], capture_output=True, check=True)
    assert b'black_start:' not in qc.stderr
    (output / 'qc.log').write_bytes(qc.stderr)
    manifest = {'title': 'Isaias historical report / mixed footage sample', 'event_id': 'AL092020', 'historical': True, 'shots': edit, 'media': catalog, 'weather_evidence': evidence['evidence'], 'output': {'path': str(video), 'checksum': checksum(video), 'seconds': 30, 'full_decode': True, 'black_check': True}, 'limitations': ['Stock and Irma clips illustrate weather conditions; they do not show Isaias.', 'No voiceover; original locally synthesized instrumental.', 'YouTube-origin clip obtained from its license-reviewed Wikimedia archive.'], 'paid_generation_calls': 0}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    contact = Image.new('RGB', (960, 540))
    for i, t in enumerate((2, 6, 10, 14, 18, 22, 26, 29)):
        frame = output / f'frame-{i}.jpg'
        ffmpeg(['-ss', str(t), '-i', str(video), '-frames:v', '1', '-vf', 'scale=320:180', str(frame)])
        contact.paste(Image.open(frame), ((i % 3) * 320, (i // 3) * 180))
    contact.save(output / 'contact.jpg')
    print(video, flush=True)


if __name__ == '__main__':
    run()
