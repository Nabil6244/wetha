"""Compare heuristic footage screening with vision-assisted screening on labelled preview frames.

Each example in docs/benchmarks/vision-eval/labels.json is a real provider preview frame with a human judgement.
A clip counts as accepted when its tier is auto or recommended. Small, single-story sample: not a benchmark of
general performance. Usage: .venv/bin/python scripts/evaluate-vision-screening.py
"""
import json, sys, time
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from PIL import Image
from app.footage_review import assess
from app.footage_vision import VisionScreen, findings, adjust
from app.visual_concepts import measure
from app.media_selection import topics

DATA = ROOT / 'docs/benchmarks/vision-eval'


def main():
    examples = json.loads((DATA / 'labels.json').read_text())['examples']
    advisory = SimpleNamespace(title='Storm Surge Warning')
    screener = VisionScreen(ROOT / '.local' / 'vision-eval')
    cached = len(screener.results)
    started = time.monotonic()
    raw = screener.screen([DATA / e['frame'] for e in examples])
    vision_seconds = {'seconds': round(time.monotonic() - started, 2), 'frames_already_cached': cached}
    rows = []
    for e in examples:
        frame = DATA / e['frame']
        # Built exactly as the Pexels integration builds candidates: tags from the title, description = title.
        candidate = {'id': e['clip_id'], 'title': e['title'], 'tags': sorted(topics(e['title'])), 'provider': e['provider'], 'height': e['height'],
                     'seconds': e['seconds'], 'reuse_basis': 'stock_license', 'license': e['licence'], 'description': e['title']}
        scene = {'script_segment': e['narration']}
        base = assess(candidate, scene, advisory, measure(Image.open(frame)))
        found = findings(raw.get(str(frame)) if raw else None, base['visual']['concept'].split('→')[0])
        rows.append({**{k: e[k] for k in ('category', 'title', 'relevant', 'setting_mismatch_visible', 'reason')},
                     'heuristic': base['tier'], 'vision': adjust(base['tier'], found), 'vision_findings': found})
    def summary(key):
        accepted = lambda r: r[key] in ('auto', 'recommended')
        wrong = [r for r in rows if accepted(r) != bool(r['relevant'])]
        return {'correct': len(rows) - len(wrong), 'of': len(rows),
                'false_auto': [r['title'] for r in rows if r[key] == 'auto' and (not r['relevant'] or r['setting_mismatch_visible'])],
                'relevant_demoted': [r['title'] for r in rows if r['relevant'] and r[key] == 'weak'],
                'irrelevant_accepted': [r['title'] for r in rows if not r['relevant'] and accepted(r)],
                'by_category': {c: f"{sum(accepted(r) == bool(r['relevant']) for r in rows if r['category'] == c)}/{sum(r['category'] == c for r in rows)}"
                                for c in dict.fromkeys(r['category'] for r in rows)}}
    foreign = [r for r in rows if r['setting_mismatch_visible']]
    result = {'examples': len(rows), 'vision_available': raw is not None, 'vision_runtime': vision_seconds,
              'heuristic': summary('heuristic'), 'vision_assisted': summary('vision'),
              'foreign_setting_identified_by_vision': f"{sum(bool(r['vision_findings'] and r['vision_findings']['setting_cues']) for r in foreign)}/{len(foreign)}",
              'rows': rows}
    (DATA / 'results.json').write_text(json.dumps(result, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=1))
    for r in rows:
        f = r['vision_findings'] or {}
        print(f"{r['category']:<20} rel={r['relevant']} heur={r['heuristic']:<11} vision={r['vision']:<11} {r['title'][:40]:<40} | {f.get('rationale', 'no vision')[:90]}")


if __name__ == '__main__':
    main()
