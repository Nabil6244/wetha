"""Footage library analysis: internal shot changes, clean cut placement, frame fill and coverage."""
import re
import shutil
import subprocess
from . import media_selection, regional

SCENE_THRESHOLD = 0.32
EDGE = .05  # A cut may touch a shot change, not straddle one.
RECOVER = .2  # Pictures fade back in after black or a slate; start a little after the range ends.


def analyse(path, seconds):
    """Internal camera cuts and unusable ranges, from one low-resolution decode.

    Unusable ranges are black (fades, gaps between segments) or frozen picture (title slates,
    "starting soon" cards, static telemetry displays): never usable as moving footage. Returns
    {'shot_starts', 'unusable_ranges'}, or None when FFmpeg cannot analyse."""
    executable = shutil.which('ffmpeg')
    if not executable:
        return None
    try:
        result = subprocess.run([executable, '-hide_banner', '-nostats', '-protocol_whitelist', 'file,pipe', '-i', str(path),
                                 '-vf', f"scale=320:-2,blackdetect=d=0.2:pix_th=0.06,freezedetect=n=0.001:d=1.5,select='gt(scene,{SCENE_THRESHOLD})',showinfo",
                                 '-an', '-f', 'null', '-'],
                                capture_output=True, text=True, timeout=max(60, seconds * 2))
    except subprocess.SubprocessError:
        return None
    if result.returncode:
        return None
    log = result.stderr
    times = sorted({round(float(t), 3) for t in re.findall(r'pts_time:([0-9.]+)', log)})
    # Changes closer than half a second are flashes or dissolves, not separate shots.
    shots = []
    for t in times:
        if 0.5 < t < seconds - 0.5 and (not shots or t - shots[-1] >= .5):
            shots.append(t)
    ranges = [(float(a), float(b)) for a, b in re.findall(r'black_start:([0-9.]+) black_end:([0-9.]+)', log)]
    freezes = re.findall(r'freeze_(start|end): ([0-9.]+)', log)
    start = None
    for kind, value in freezes:
        if kind == 'start':
            start = float(value)
        elif start is not None:
            ranges.append((start, float(value)));start = None
    if start is not None:
        ranges.append((start, seconds))  # Frozen until the end of the recording.
    # Merge overlapping ranges and the brief flickers between them (a static display that updates).
    merged = []
    for a, b in sorted(ranges):
        if merged and a - merged[-1][1] < .5:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return {'shot_starts': shots, 'unusable_ranges': [[round(a, 3), round(b, 3)] for a, b in merged]}


def detect_shots(path, seconds):
    """Times of internal camera cuts. Decoded at low resolution; None when FFmpeg cannot analyse."""
    result = analyse(path, seconds)
    return result and result['shot_starts']


def place(asset, start, seconds):
    """Earliest start at or after `start` whose range stays inside one camera shot.

    Returns None when the clip cannot hold the range. Without shot analysis, or when no single
    shot is long enough, the plain start is used; a cut never loops or overlaps an earlier range."""
    limit = asset['seconds'] + .01
    changes = asset.get('shot_starts') or []
    unusable = asset.get('unusable_ranges') or []
    # Openings are often slates, titles or countdowns: skip the first camera shot of a longer clip,
    # or at least the first few seconds when shot analysis found no early camera change.
    if (asset.get('seconds') or 0) > 20:
        opening = next((c for c in changes if c <= 15), None) or min(4, asset['seconds'] * .1)
        start = max(start, opening)
    # Black and frozen picture are never footage: a cut may not show any part of them.
    def clear(at):
        for a, b in unusable:
            if a < at + seconds - EDGE and b + RECOVER > at + EDGE:
                return b + RECOVER
        return None
    while (after := clear(start)) is not None:
        start = after
    if start + seconds > limit:
        return None
    candidate = start
    for change in changes:
        if change <= candidate + EDGE:
            continue
        if change < candidate + seconds - EDGE:
            # Straddles a cut: start on the new shot instead, if that range is clean.
            if change + seconds > limit or clear(change) is not None:
                return start
            candidate = change
            continue
        break
    return candidate


# One mild, cool newsroom grade so footage from different sources sits together.
GRADE = 'eq=contrast=1.04:saturation=0.94,colorbalance=bs=0.03:bh=0.015,vignette=angle=PI/7'


def fill_filter(asset):
    """Fit footage to 1920x1080. Off-ratio sources fill the frame with a blurred copy instead of black bars."""
    width, height = asset.get('width'), asset.get('height')
    if not width or not height or abs(width / height - 16 / 9) <= .03:
        return f'[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,{GRADE},pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[base]'
    return ('[0:v]split[wide][fit];[wide]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,'
            'boxblur=40:2,eq=brightness=-0.12:saturation=0.8[back];[fit]scale=1920:1080:force_original_aspect_ratio=decrease[front];'
            f'[back][front]overlay=(W-w)/2:(H-h)/2,{GRADE},setsar=1,fps=30[base]')


def usable_cuts(asset, seconds=3.5):
    if asset['kind'] == 'image':
        return 1
    return int((asset.get('seconds') or 0) // seconds)


def coverage(media, plan=None, advisory_lookup=None):
    """What the library holds by topic, region, context and event, and where a plan's needs exceed it."""
    visual = [a for a in media if a['kind'] in ('video', 'image') and a.get('rights_confirmed') and not a.get('quarantined')]
    names = {r['code']: r['name'] for r in regional.options()}
    by_topic, by_region, by_context, by_event = {}, {}, {}, {}
    def add(table, key, asset):
        row = table.setdefault(key, {'key': key, 'clips': 0, 'seconds': 0, 'cuts': 0})
        row['clips'] += 1;row['seconds'] += asset.get('seconds') or 0;row['cuts'] += usable_cuts(asset)
    for asset in visual:
        catalog = asset.get('catalog', {})
        for topic in media_selection.topics(' '.join(catalog.get('tags', [])) + ' ' + asset['name']) or {'untagged'}:
            add(by_topic, topic, asset)
        regions = catalog.get('region_codes', []) if catalog.get('location_reviewed') else []
        for code in regions or ['unreviewed']:
            add(by_region, names.get(code, code), asset)
        add(by_context, asset.get('context', 'unknown'), asset)
        add(by_event, catalog.get('event_id') or 'no event declared', asset)
    videos = [a for a in visual if a['kind'] == 'video']
    result = {'clips': len(visual), 'videos': len(videos),
              'seconds': round(sum(a.get('seconds') or 0 for a in videos), 1),
              'usable_cuts': sum(usable_cuts(a) for a in visual),
              'needs_location_review': sum(1 for a in visual if not a.get('catalog', {}).get('location_reviewed')),
              'needs_shot_analysis': sum(1 for a in videos if 'shot_starts' not in a),
              'off_ratio': sum(1 for a in videos if a.get('width') and a.get('height') and abs(a['width'] / a['height'] - 16 / 9) > .03),
              'by_topic': sorted(by_topic.values(), key=lambda r: -r['cuts']),
              'by_region': sorted(by_region.values(), key=lambda r: -r['cuts']),
              'by_context': sorted(by_context.values(), key=lambda r: -r['cuts']),
              'by_event': sorted(by_event.values(), key=lambda r: -r['cuts'])[:20],
              'gaps': []}
    for table in ('by_topic', 'by_region', 'by_context', 'by_event'):
        for row in result[table]:
            row['seconds'] = round(row['seconds'], 1)
    if plan:
        result['gaps'] = gaps(plan, visual, advisory_lookup)
    return result


def gaps(plan, assets, advisory_lookup):
    """Per topic and region: beats in the plan that want footage versus distinct matching cuts available."""
    needs = {}
    for scene in plan['scenes']:
        wanted = media_selection.topics(scene.get('source_claim_text') or scene['script_segment'])
        if not wanted:
            continue
        advisory = advisory_lookup(scene['parameters'].get('source_advisory_id') or plan.get('advisory_id'))
        matching = media_selection.rank(scene, assets, advisory, limit=None)
        regions = regional.targets(scene)
        key = (tuple(sorted(regions)), tuple(sorted(wanted)))
        row = needs.setdefault(key, {'regions': sorted(regions), 'topics': sorted(wanted), 'beats': 0, 'seconds': 0,
                                     'available_cuts': 0, 'clip_ids': set()})
        row['beats'] += 1;row['seconds'] += scene.get('target_seconds') or 4
        row['clip_ids'] |= {c['media_id'] for c in matching}
    by_id = {a['id']: a for a in assets}
    result = []
    for row in needs.values():
        row['available_cuts'] = sum(usable_cuts(by_id[i]) for i in row['clip_ids'])
        # The bulletin uses footage for about 40% of beats; a recording cannot return within two minutes.
        wanted_cuts = max(1, round(row['beats'] * .4))
        clips = row.pop('clip_ids')
        row.update(seconds=round(row['seconds'], 1), matching_clips=len(clips), wanted_cuts=wanted_cuts,
                   short_by=max(0, wanted_cuts - row['available_cuts']),
                   status='missing' if not clips else 'thin' if row['available_cuts'] < wanted_cuts or len(clips) < 2 else 'covered')
        result.append(row)
    return sorted(result, key=lambda r: ({'missing': 0, 'thin': 1, 'covered': 2}[r['status']], -r['beats']))
