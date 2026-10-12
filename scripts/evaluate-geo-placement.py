"""Final-selection geographic gate: would each labelled clip be placed by the automatic edit, before and after?

Each labelled frame is treated as an imported library clip (name and source slug from its title, tags as the
provider integration sets them) in a US NWS story beat. 'Placed' = returned by media_selection.rank.
Usage: .venv/bin/python scripts/evaluate-geo-placement.py
"""
import json, re, sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import media_selection, geo_gate
from app.media_selection import topics

DATA = ROOT / 'docs/benchmarks/vision-eval'
US = SimpleNamespace(provider='NWS', title='Flash Flood Warning', event_key='urn:x', issued_at=None)


def placed(asset, narration):
    return bool(media_selection.rank({'id': 's', 'script_segment': narration, 'parameters': {}}, [asset], US, limit=None, allow_unverified=True))


def main():
    rows = []
    for e in json.loads((DATA / 'labels.json').read_text())['examples']:
        slug = re.sub(r'[^a-z0-9]+', '-', e['title'].lower()).strip('-')
        asset = {'id': e['clip_id'], 'kind': 'video', 'name': f"pexels-{e['clip_id'][:6]}.mp4", 'seconds': e['seconds'] or 20, 'rights_confirmed': True,
                 'context': 'illustrative', 'attribution': 'Pexels', 'width': 1920, 'source': f'https://www.pexels.com/video/{slug}-1/',
                 'catalog': {'tags': sorted(topics(e['title']))}}
        with mock.patch.object(geo_gate, 'placement', lambda *a: {'allowed': True, 'compatibility': 'off', 'reason': ''}):
            before = placed(asset, e['narration'])
        after = placed(asset, e['narration'])
        verdict = geo_gate.placement(asset, e['narration'], US)
        rows.append({'title': e['title'], 'geo': e['geo'], 'relevant': e['relevant'], 'before': before, 'after': after, 'gate': verdict['compatibility']})
    conflicts = [r for r in rows if r['geo'] != 'ok']
    report = {'examples': len(rows),
              'conflicting_clips_placed_before': [r['title'] for r in conflicts if r['before']],
              'conflicting_clips_placed_after': [r['title'] for r in conflicts if r['after']],
              'valid_relevant_clips_excluded': [r['title'] for r in rows if r['geo'] == 'ok' and r['relevant'] and r['before'] and not r['after']],
              'gate_verdicts': {c: sum(r['gate'] == c for r in rows) for c in ('conflict', 'possible_conflict', 'compatible', 'no_conflict_evident')},
              'rows': rows}
    (DATA / 'geo-placement-results.json').write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=1))
    for r in rows:
        print(f"geo={r['geo']:<17} rel={r['relevant']} placed {str(r['before']):<5} -> {str(r['after']):<5} [{r['gate']}] {r['title'][:46]}")


if __name__ == '__main__':
    main()
