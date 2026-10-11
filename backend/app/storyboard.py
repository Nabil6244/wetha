"""Storyboard contact sheet and a quick animatic preview of a timeline, before the full render.

One real frame per shot (graphics drawn by the renderer, footage taken from the chosen clip at its
cut point), annotated with time, visual and underlying layer. The animatic holds each frame for the
shot's real duration over the voiceover, so pacing and repetition can be judged in seconds.
"""
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from . import broadcast, footage_library

THUMB = (384, 216)
COLUMNS = 8


def shot_layer(scene):
    from .visual_states import layer_of
    if scene.get('media_id') or scene.get('cuts'):
        return layer_of('footage', '', scene)
    if scene['parameters'].get('visual_layer'):
        return scene['parameters']['visual_layer']
    # Older timelines: derive the layer from the recorded choice so before/after comparisons are fair.
    chosen = (scene['parameters'].get('visual_decision') or {}).get('chosen') or ('chart' if scene['parameters'].get('report_graphs') else 'hold')
    return 'chart' if chosen == 'chart' else layer_of(chosen, scene['parameters'].get('source_advisory_id', ''))


def frame(production, scene, media, scratch, index):
    if scene.get('cuts') or scene.get('media_id'):
        cut = scene['cuts'][0] if scene.get('cuts') else {'media_id': scene['media_id'], 'trim_start': scene.get('trim_start', 0), 'seconds': scene['seconds']}
        asset = media[cut['media_id']];path = production.media_path(asset)
        if asset['kind'] == 'image':
            return Image.open(path).convert('RGB').resize(broadcast.SIZE)
        out = scratch / f'shot-{index:04}.png';label = scratch / f'label-{index:04}.png'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', f"{cut['trim_start'] + min(1, cut['seconds'] / 2):.3f}", '-i', str(path),
                        '-filter_complex', footage_library.fill_filter(asset), '-map', '[base]', '-frames:v', '1', str(out)], check=True, timeout=60)
        picture = Image.open(out).convert('RGBA')
        production.footage_overlay(asset, label, scene)  # The same on-screen labels and story-area inset as the render.
        return Image.alpha_composite(picture, Image.open(label).convert('RGBA')).convert('RGB')
    span = scene['parameters'].get('camera_span')
    t = (span[0] + span[1]) / 2 if span else .6
    assets = production.scene_assets(scene)
    return broadcast.Composer(scene['direction'], scene['parameters'], assets.__getitem__).frame(t)


def metrics(timeline, layers):
    longest, run = 1, 1
    for a, b in zip(layers, layers[1:]):
        run = run + 1 if a == b else 1;longest = max(longest, run)
    seconds = timeline['seconds'] or 1
    share = lambda test: round(sum(s['seconds'] for s, l in zip(timeline['scenes'], layers) if test(s, l)) / seconds, 3)
    clips = {c['media_id'] for s in timeline['scenes'] for c in s.get('cuts', [])} | {s['media_id'] for s in timeline['scenes'] if s.get('media_id')}
    from .geography import mentions
    named = [s for s in timeline['scenes'] if mentions(s['script_segment'])]
    # Shown: a place shot, or footage carrying the story-area locator for the places it names.
    shown = [s for s in named if s['parameters'].get('visual_state') == 'place_focus' or s.get('cuts') or s.get('media_id')]
    return {'shots': len(layers), 'distinct_visuals': len(set(layers)), 'longest_same_layer_run': longest,
            'footage_share': share(lambda s, l: l.startswith('footage')), 'story_map_share': share(lambda s, l: l == 'story_map'),
            'data_layer_shots': sum(l in ('radar_loop', 'satellite_loop', 'severe_outlook') or l.startswith(('county_focus', 'place_focus')) for l in layers),
            'distinct_clips': len(clips), 'beats_naming_places': len(named), 'place_beats_shown': len(shown),
            'layers_used': sorted({l.split(':')[0] for l in layers})}


def build(production, timeline, media, directory, audio=None):
    directory = Path(directory);directory.mkdir(parents=True, exist_ok=True)
    scratch = directory / 'frames';scratch.mkdir(exist_ok=True)
    layers, cursor, rows = [], 0.0, []
    for index, scene in enumerate(timeline['scenes']):
        image = frame(production, scene, media, scratch, index)
        small = image.resize((640, 360), Image.Resampling.LANCZOS);small.save(scratch / f'preview-{index:04}.png')
        layer = shot_layer(scene);layers.append(layer)
        decision = scene['parameters'].get('visual_decision') or {}
        rows.append({'shot': index + 1, 'start': round(cursor, 2), 'seconds': scene['seconds'], 'layer': layer,
                     'visual': decision.get('chosen') or layer.split(':')[0], 'narration': scene['script_segment'],
                     'thumb': image.resize(THUMB, Image.Resampling.LANCZOS)})
        cursor += scene['seconds']
    stats = metrics(timeline, layers)
    # Contact sheet.
    count = len(rows);height = 120 + ((count + COLUMNS - 1) // COLUMNS) * (THUMB[1] + 64)
    sheet = Image.new('RGB', (COLUMNS * (THUMB[0] + 12) + 12, height), '#050f17');draw = ImageDraw.Draw(sheet)
    draw.text((16, 16), f"{timeline['title']} · {count} shots · {stats['distinct_visuals']} distinct visuals · {stats['distinct_clips']} clips · "
              f"footage {stats['footage_share']:.0%} · same story map {stats['story_map_share']:.0%} · longest same-layer run {stats['longest_same_layer_run']}",
              font=broadcast.font(26), fill='#e7f1f8')
    draw.text((16, 60), f"Places named in {stats['beats_naming_places']} beats, shown in {stats['place_beats_shown']} · layers: {', '.join(stats['layers_used'])}",
              font=broadcast.font(22), fill='#9dbbc6')
    for i, row in enumerate(rows):
        x = 12 + (i % COLUMNS) * (THUMB[0] + 12);y = 110 + (i // COLUMNS) * (THUMB[1] + 64)
        repeat = i and rows[i - 1]['layer'] == row['layer']
        sheet.paste(row['thumb'], (x, y))
        draw.rectangle((x - 2, y - 2, x + THUMB[0] + 1, y + THUMB[1] + 1), outline='#ffb347' if repeat else '#1d3a48', width=3)
        draw.text((x, y + THUMB[1] + 6), f"{row['shot']} · {int(row['start'] // 60)}:{row['start'] % 60:04.1f} · {row['visual'].replace('_', ' ')}", font=broadcast.font(18), fill='#e7f1f8')
        draw.text((x, y + THUMB[1] + 30), row['narration'][:48], font=broadcast.font(15), fill='#8fb0bf')
    sheet.save(directory / 'storyboard.jpg', quality=88)
    # Animatic: each frame for its real duration, over the voiceover when there is one.
    listing = directory / 'animatic.txt'
    listing.write_text(''.join(f"file 'frames/preview-{i:04}.png'\nduration {r['seconds']:.4f}\n" for i, r in enumerate(rows)) + f"file 'frames/preview-{count - 1:04}.png'\n")
    command = ['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing)]
    if audio:
        command += ['-i', str(audio), '-map', '0:v', '-map', '1:a', '-c:a', 'aac', '-b:a', '96k', '-shortest']
    command += ['-vf', 'fps=10,format=yuv420p', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', str(directory / 'preview.mp4')]
    subprocess.run(command, check=True, timeout=600, cwd=directory)
    plan = [{k: v for k, v in r.items() if k != 'thumb'} for r in rows]
    (directory / 'storyboard.json').write_text(json.dumps({'metrics': stats, 'shots': plan}, indent=2))
    return {'metrics': stats, 'shots': plan}
