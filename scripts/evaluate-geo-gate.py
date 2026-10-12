"""US-story geographic gate: before/after on labelled preview frames.

Labels (docs/benchmarks/vision-eval/labels.json): 'relevant' (does the frame show the beat) and 'geo'
('conflict_visible': setting visibly outside the US; 'conflict_metadata': metadata names a non-US place; 'ok').
The story is treated as a US NWS story. Accepted = auto or recommended. Small labelled sample, one region.
Usage: .venv/bin/python scripts/evaluate-geo-gate.py
"""
import json, sys
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from PIL import Image
from app.footage_review import assess
from app.visual_concepts import measure
from app.media_selection import topics

DATA = ROOT / 'docs/benchmarks/vision-eval'
US = SimpleNamespace(title='Flash Flood Warning', provider='NWS')


def main():
    rows = []
    for e in json.loads((DATA / 'labels.json').read_text())['examples']:
        candidate = {'id': e['clip_id'], 'title': e['title'], 'tags': sorted(topics(e['title'])), 'provider': e['provider'], 'height': e['height'],
                     'seconds': e['seconds'], 'reuse_basis': 'stock_license', 'license': e['licence'], 'description': e['title']}
        features = measure(Image.open(DATA / e['frame']));scene = {'script_segment': e['narration']}
        before = assess(candidate, scene, US, features, geo_gate=False)
        after = assess(candidate, scene, US, features)
        rows.append({'title': e['title'], 'category': e['category'], 'relevant': e['relevant'], 'geo': e['geo'], 'before': before['tier'], 'after': after['tier'],
                     'compatibility': after['location'].get('geography', {}).get('compatibility')})
    order = {'weak': 0, 'recommended': 1, 'auto': 2}
    conflicts = [r for r in rows if r['geo'] != 'ok']
    report = {
        'examples': len(rows), 'conflict_examples': len(conflicts),
        'false_auto_before': [r['title'] for r in conflicts if r['before'] == 'auto'],
        'false_auto_after': [r['title'] for r in conflicts if r['after'] == 'auto'],
        'conflicts_still_recommended_after': [r['title'] for r in conflicts if r['after'] == 'recommended'],
        'valid_unnecessarily_demoted': [r['title'] for r in rows if r['geo'] == 'ok' and r['relevant'] and order[r['after']] < order[r['before']]],
        'sent_to_review_by_gate': [r['title'] for r in rows if r['compatibility'] == 'possible_conflict'],
        'gate_verdicts': {c: sum(r['compatibility'] == c for r in rows) for c in ('conflict', 'possible_conflict', 'compatible', 'no_conflict_evident')},
        'rows': rows}
    (DATA / 'geo-results.json').write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=1))
    for r in rows:
        print(f"{r['category']:<20} rel={r['relevant']} geo={r['geo']:<17} {r['before']:<11} -> {r['after']:<11} [{r['compatibility']}] {r['title'][:44]}")


if __name__ == '__main__':
    main()
