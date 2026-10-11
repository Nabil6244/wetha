"""Upload-ready package for a finished render: thumbnail from a real frame, title options, description.

Nothing here publishes. Text comes from the user's title, their narration and the source records;
no claim is added. Upload privacy defaults to private.
"""
import json
import re
import subprocess
import textwrap
from PIL import Image, ImageDraw


def stamp(seconds):
    seconds = int(seconds);h, rest = divmod(seconds, 3600);m, s = divmod(rest, 60)
    return f'{h}:{m:02}:{s:02}' if h else f'{m}:{s:02}'


def chapters(timeline, report):
    """Story changes as chapters. YouTube needs the first at 0:00, at least three, each at least ten seconds."""
    titles = {s['id']: s['title'] for s in report['sources']};rows = [];cursor = 0.0
    for scene in timeline['scenes']:
        story = scene['parameters'].get('source_advisory_id')
        if story and (not rows or rows[-1]['story'] != story):
            rows.append({'story': story, 'start': cursor, 'title': titles.get(story, 'Update')})
        cursor += scene['seconds']
    if rows:
        rows[0]['start'] = 0
    lengths = [b['start'] - a['start'] for a, b in zip(rows, rows[1:])] + [timeline['seconds'] - rows[-1]['start']] if rows else []
    return rows if len(rows) >= 3 and all(n >= 10 for n in lengths) else []


def summary(timeline, limit=280):
    text = ' '.join(s['script_segment'] for s in timeline['scenes'])
    sentences = re.split(r'(?<=[.!?])\s+', ' '.join(text.split()))
    out = ''
    for sentence in sentences:
        if len(out) + len(sentence) > limit:
            break
        out = (out + ' ' + sentence).strip()
    return out or text[:limit]


def metadata(timeline, report):
    hazards = sorted({row['hazard'].replace('_', ' ') for row in report['visual_plan'] if row.get('hazard') not in (None, 'general')})
    places = sorted({name for s in timeline['scenes'] for name, _ in s['parameters'].get('places', [])})[:8]
    title = timeline['title'].strip()
    options = [title]
    if timeline.get('report_title') and timeline['report_title'] not in title:
        options.append(f"{title} | {timeline['report_title']}"[:100])
    if places:
        options.append(f"{title}: {', '.join(places[:2])}"[:100])
    marks = chapters(timeline, report)
    lines = [summary(timeline), '']
    if marks:
        lines += ['Chapters'] + [f"{stamp(m['start'])} {m['title']}" for m in marks] + ['']
    lines += ['Sources'] + [f"- {s['provider']}: {s['title']} (issued {s['issued_at']})" for s in report['sources']] + ['']
    if report['footage']:
        lines += ['Footage'] + [f"- {f['attribution']} · {f['license']}" + (' · archival, not the current event' if f['context'] == 'archival' else ' · illustrative') for f in report['footage']] + ['']
    lines += ['Produced with Weather Intelligence Studio. Always follow your local National Weather Service office and emergency managers.']
    return {'title_options': [t[:100] for t in dict.fromkeys(options)], 'description': '\n'.join(lines)[:5000],
            'tags': (hazards + places + ['weather', 'forecast'])[:15], 'chapters': marks, 'privacy': 'private',
            'publishing': {'status': 'not_configured', 'note': 'Upload is a separate, optional step. Nothing has been published.'}}


def thumbnail_time(report, seconds):
    plan = report['visual_plan']
    pick = next((r for r in plan if r['family'] == 'footage'), None) or next((r for r in plan if r['chosen'] in ('stat_card', 'change_gauge', 'place_callout')), None)
    return (pick['start'] + pick['end']) / 2 if pick else seconds / 2


def thumbnail(work, timeline, report):
    from .broadcast import font
    frame = work / 'thumbnail-frame.png'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{thumbnail_time(report, timeline["seconds"]):.3f}', '-i', str(work / 'program.mp4'),
                    '-frames:v', '1', str(frame)], check=True, timeout=60)
    image = Image.open(frame).convert('RGB').resize((1280, 720), Image.Resampling.LANCZOS)
    shade = Image.linear_gradient('L').rotate(90, expand=True).resize((1280, 720))
    image = Image.composite(image, Image.new('RGB', (1280, 720), '#061724'), shade.point(lambda v: min(255, 60 + v)))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 18, 720), fill='#65e1d1')
    lines = textwrap.wrap(timeline['title'].upper(), 18)[:3]
    for i, line in enumerate(lines):
        draw.text((60, 120 + i * 112), line, font=font(96), fill='#ffffff', stroke_width=4, stroke_fill='#061724')
    draw.text((62, 640), 'WEATHER INTELLIGENCE', font=font(30), fill='#65e1d1')
    image.save(work / 'thumbnail.jpg', quality=90)
    frame.unlink(missing_ok=True)


def package(work, timeline, report):
    thumbnail(work, timeline, report)
    (work / 'metadata.json').write_text(json.dumps(metadata(timeline, report), indent=2), encoding='utf-8')
