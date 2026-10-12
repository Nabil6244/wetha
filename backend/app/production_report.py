"""Measured quality checks and the production report for a finished render.

Only conditions that are actually measured are reported as checked. Hard failures stop the render
elsewhere; everything here is a finding with a severity, the measurement and where it happened.
"""
import os
import re
from datetime import datetime, timezone

FREEZE_SECONDS = 6  # Cards hold still after their reveal; only longer stillness is suspicious.
# The first QC blackdetect fails the render on a fully black picture; the second, which tolerates
# captions and labels, reports footage that is black apart from its overlay.
BLACK_FRAME = r'(?m)^(?!.*Parsed_blackdetect_1).*black_start:'
NEAR_BLACK = r'Parsed_blackdetect_1[^\n]*black_start:([\d.]+) black_end:([\d.]+)'


def loudness_target():
    try:
        return float(os.environ.get('WETHA_LOUDNESS_TARGET', '-16'))
    except ValueError:
        return -16.0


def parse_qc(log):
    """Read FFmpeg blackdetect, freezedetect, silencedetect and ebur128 output."""
    integrated = re.findall(r'^\s*I:\s*(-?[\d.]+) LUFS', log, re.M)
    peak = re.findall(r'^\s*Peak:\s*(-?[\d.]+|-inf) dBFS', log, re.M)
    freezes = [(float(a), float(b)) for a, b in re.findall(r'freeze_start: ([\d.]+).*?freeze_end: ([\d.]+)', log, re.S)]
    silences = [float(v) for v in re.findall(r'silence_duration: ([\d.]+)', log)]
    return {'integrated_lufs': float(integrated[-1]) if integrated else None,
            'true_peak_dbtp': (float(peak[-1]) if peak[-1] != '-inf' else None) if peak else None,
            'black_intervals': len(re.findall(BLACK_FRAME, log)),
            'near_black': [(float(a), float(b)) for a, b in re.findall(NEAR_BLACK, log)],
            'freezes': freezes, 'silences': silences}


def caption_checks(srt):
    findings = [];rows = [r for r in srt.strip().split('\n\n') if r.strip()]
    def seconds(stamp):
        h, m, rest = stamp.split(':');s, ms = rest.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    for row in rows:
        lines = row.split('\n')
        if len(lines) < 2 or '-->' not in lines[1]:
            continue
        start, end = (seconds(t.strip()) for t in lines[1].split('-->'))
        text = ' '.join(lines[2:]).strip()
        if not text:
            findings.append(('warning', 'blank_caption', f'Blank caption at {start:.2f}s.'))
        elif len(lines) - 2 > 2 or any(len(l) > 42 for l in lines[2:]):
            findings.append(('warning', 'caption_layout', f'Caption at {start:.2f}s exceeds two lines of 42 characters.'))
        if end - start < .5 and text:
            findings.append(('warning', 'caption_flash', f'Caption at {start:.2f}s is on screen for {end - start:.2f}s.'))
        elif text and len(text) / max(.01, end - start) > 25:
            findings.append(('warning', 'caption_speed', f'Caption at {start:.2f}s needs {len(text) / (end - start):.0f} characters per second.'))
    return len(rows), findings


def plan_checks(timeline, media):
    findings = [];scenes = timeline['scenes']
    for index, scene in enumerate(scenes):
        decision = scene['parameters'].get('visual_decision') or {}
        if index:
            before = scenes[index - 1]['parameters'].get('visual_decision') or {}
            # Shots of one section, or a shot deliberately continuing the previous one, are one continuous picture.
            same_parent = (scene.get('parent_scene_id') and scene.get('parent_scene_id') == scenes[index - 1].get('parent_scene_id')) \
                or scene['parameters'].get('continues') == scenes[index - 1].get('id')
            # The same state over a different picture (another place, another story's map) is not a repeat.
            same_picture = scene['parameters'].get('visual_layer') == scenes[index - 1]['parameters'].get('visual_layer')
            if decision.get('chosen') and decision.get('chosen') == before.get('chosen') and decision['chosen'] not in ('footage', 'hold') and not same_parent and same_picture:
                findings.append(('warning', 'repeated_visual', f"Shots {index} and {index + 1} use the same {decision['chosen'].replace('_', ' ')} view."))
        if not (scene['parameters'].get('credit') or scene.get('media_id') or scene.get('cuts')):
            findings.append(('warning', 'missing_credit', f'Shot {index + 1} has no source credit line.'))
        for warning in decision.get('warnings', []):
            findings.append(('notice', 'visual_gap', f'Shot {index + 1}: {warning}'))
        clips = ([scene['media_id']] if scene.get('media_id') else []) + [c['media_id'] for c in scene.get('cuts', [])]
        for clip in clips:
            asset = media.get(clip, {})
            if not asset.get('attribution') or not asset.get('license'):
                findings.append(('error', 'missing_attribution', f'Shot {index + 1}: clip {asset.get("name", clip)} lacks licence or attribution.'))
    return findings


def source_ages(timeline, advisory_lookup, now=None):
    now = now or datetime.now(timezone.utc);rows = {}
    for scene in timeline['scenes']:
        identity = scene['parameters'].get('source_advisory_id')
        if identity and identity not in rows:
            try:
                advisory = advisory_lookup(identity)
            except KeyError:
                continue
            rows[identity] = {'id': identity, 'title': advisory.title, 'provider': advisory.provider,
                              'issued_at': advisory.issued_at.isoformat(), 'age_hours': round((now - advisory.issued_at).total_seconds() / 3600, 1)}
    return list(rows.values())


def build(job, timeline, media, qc_log, srt, advisory_lookup, timings):
    measured = parse_qc(qc_log);findings = []
    target = loudness_target()
    if measured['integrated_lufs'] is not None and abs(measured['integrated_lufs'] - target) > 2:
        findings.append(('warning', 'loudness', f"Integrated loudness {measured['integrated_lufs']:.1f} LUFS; target {target:g} ± 2."))
    if measured['true_peak_dbtp'] is not None and measured['true_peak_dbtp'] > -0.5:
        findings.append(('warning', 'clipping', f"Peak {measured['true_peak_dbtp']:.1f} dBFS is close to clipping."))
    for start, end in measured['near_black']:
        findings.append(('warning', 'near_black_picture', f'Picture is black apart from labels from {start:.1f}s to {end:.1f}s.'))
    for start, end in measured['freezes']:
        if end - start >= FREEZE_SECONDS:
            findings.append(('warning', 'frozen_picture', f'Picture does not change from {start:.1f}s to {end:.1f}s.'))
    if timeline.get('narration_id') and any(s >= 2 for s in measured['silences']):
        findings.append(('warning', 'silence', f"{sum(1 for s in measured['silences'] if s >= 2)} silent passages of two seconds or more in the narration."))
    captions, caption_findings = caption_checks(srt)
    findings += caption_findings + plan_checks(timeline, media)
    sources = source_ages(timeline, advisory_lookup)
    if timeline.get('source_label') == 'current':
        findings += [('warning', 'stale_source', f"{s['title']} was issued {s['age_hours']:g} hours ago.") for s in sources if s['age_hours'] > 12]
    plan = [s['parameters'].get('visual_decision') for s in timeline['scenes'] if s['parameters'].get('visual_decision')]
    families = {}
    for row in plan:
        families[row['family']] = families.get(row['family'], 0) + (row['end'] - row['start'])
    clips = {c['media_id'] for s in timeline['scenes'] for c in s.get('cuts', [])} | {s['media_id'] for s in timeline['scenes'] if s.get('media_id')}
    order = {'error': 0, 'warning': 1, 'notice': 2}
    return {
        'render_id': job['id'], 'title': timeline['title'], 'created_at': datetime.now(timezone.utc).isoformat(),
        'seconds': timeline['seconds'], 'scenes': len(timeline['scenes']),
        'checks': {'duration_and_frames': True, 'codecs': True, 'decoded': True, 'black_frames': measured['black_intervals'] == 0,
                   'loudness_lufs': measured['integrated_lufs'], 'true_peak_dbfs': measured['true_peak_dbtp'], 'loudness_target': target,
                   'frozen_intervals': len([f for f in measured['freezes'] if f[1] - f[0] >= FREEZE_SECONDS]), 'captions': captions},
        'visual_mix_seconds': {k: round(v, 1) for k, v in sorted(families.items())},
        'footage': [{'id': c, 'name': media.get(c, {}).get('name'), 'context': media.get(c, {}).get('context'),
                     'license': media.get(c, {}).get('license'), 'attribution': media.get(c, {}).get('attribution'),
                     'source': media.get(c, {}).get('source')} for c in sorted(clips)],
        'sources': sources,
        'cache': {'reused_scenes': job.get('reused_scenes', 0), 'cached_on_retry': job.get('cached_scenes', 0), 'total_scenes': len(timeline['scenes'])},
        'timings_seconds': timings,
        'findings': [{'severity': s, 'code': c, 'message': m} for s, c, m in sorted(findings, key=lambda f: order[f[0]])],
        'errors': sum(1 for f in findings if f[0] == 'error'), 'warnings': sum(1 for f in findings if f[0] == 'warning'),
        'visual_plan': plan,
        'note': 'Measured checks: duration, frame count, codecs, full decode, black frames, frozen picture, loudness, peak, silence, caption layout and timing, repeated adjacent views, credits and attribution. Geographic correctness and footage relevance are traced to sources, not visually inspected.',
    }


def markdown(report):
    lines = [f"# Production report: {report['title']}", '',
             f"{report['seconds']:.1f} seconds · {report['scenes']} shots · {report['errors']} errors · {report['warnings']} warnings", '',
             '## Checks', '']
    checks = report['checks']
    lines += [f"- Duration, frame count, codecs and full decode: passed",
              f"- Black frames: {'none' if checks['black_frames'] else 'found'}",
              f"- Frozen picture (≥{FREEZE_SECONDS}s): {checks['frozen_intervals']}",
              f"- Loudness: {checks['loudness_lufs'] if checks['loudness_lufs'] is not None else 'not measured'} LUFS (target {checks['loudness_target']:g}); peak {checks['true_peak_dbfs'] if checks['true_peak_dbfs'] is not None else 'n/a'} dBFS",
              f"- Captions: {checks['captions']}", '', '## Visual mix', '']
    lines += [f"- {k}: {v}s" for k, v in report['visual_mix_seconds'].items()] or ['- none']
    lines += ['', '## Timings', ''] + [f"- {k}: {v}s" for k, v in report['timings_seconds'].items()]
    lines += ['', f"Scenes reused from earlier renders: {report['cache']['reused_scenes']} of {report['cache']['total_scenes']}", '', '## Findings', '']
    lines += [f"- **{f['severity']}** {f['message']}" for f in report['findings']] or ['- none']
    lines += ['', '## Sources', ''] + [f"- {s['provider']}: {s['title']} (issued {s['issued_at']}, {s['age_hours']}h before render)" for s in report['sources']]
    lines += ['', '## Footage', ''] + ([f"- {f['name']} · {f['context']} · {f['attribution']} · {f['license']}" for f in report['footage']] or ['- none'])
    lines += ['', '_' + report['note'] + '_', '']
    return '\n'.join(lines)
