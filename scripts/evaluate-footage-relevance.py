"""Evaluate visual relevance on real provider candidates from a saved footage review.

Labels are editorial judgements from looking at each candidate's preview frame (1 = communicates its beat,
0 = does not). Passing this script does not prove visual relevance; it measures agreement with those labels.
Usage: .venv/bin/python scripts/evaluate-footage-relevance.py review.json labels.json
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from types import SimpleNamespace
from app.footage_review import assess, preview_features
from app import visual_concepts as vc


async def main(review_path, labels_path):
    review = json.loads(Path(review_path).read_text());labels = json.loads(Path(labels_path).read_text())
    advisory = SimpleNamespace(title='Hurricane Isaias Advisory 7A');cache = {};rows = [];offered = []
    for beat in review['beats']:
        scene = {'script_segment': beat['narration']}
        for c in beat['candidates']:
            label = next((v for k, v in labels.items() if c['title'].startswith(k)), None)
            if label is None:
                continue
            candidate = {'id': c['candidate_id'], 'title': c['title'], 'tags': [], 'provider': c['provider'], 'height': c['height'], 'seconds': c['seconds'],
                         'reuse_basis': 'stock_license', 'license': c['licence'], 'description': ''}
            features = await preview_features(c.get('thumbnail_url'), cache)
            meta = assess(candidate, scene, advisory)
            full = assess(candidate, scene, advisory, features, offered)
            if features:
                offered.append(features)
            rows.append({'title': c['title'], 'concept': full['visual']['concept'], 'label': label, 'metadata_tier': meta['tier'], 'tier': full['tier'],
                         'score': full['visual']['score'], 'flags': full['visual']['preview_flags'], 'preview': bool(features),
                         'provenance': full['provenance']['status'], 'claimed_event': full['provenance']['claimed_event']})
    def stats(key):
        chosen = [r for r in rows if r[key] in ('auto', 'recommended')];auto = [r for r in rows if r[key] == 'auto'];relevant = [r for r in rows if r['label']]
        return {'chosen': len(chosen), 'precision': round(sum(r['label'] for r in chosen) / max(1, len(chosen)), 3),
                'auto': len(auto), 'auto_precision': round(sum(r['label'] for r in auto) / max(1, len(auto)), 3),
                'recall': round(sum(r[key] in ('auto', 'recommended') for r in relevant) / max(1, len(relevant)), 3),
                'false_positives': [r['title'] for r in chosen if not r['label']], 'missed': [r['title'] for r in relevant if r[key] not in ('auto', 'recommended')]}
    result = {'candidates': len(rows), 'with_preview': sum(r['preview'] for r in rows), 'metadata_only': stats('metadata_tier'),
              'with_preview_screening': stats('tier'), 'flagged': [(r['title'], r['flags']) for r in rows if r['flags']],
              'claimed_events': [(r['title'], r['claimed_event']) for r in rows if r['claimed_event']], 'rows': rows}
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=1))
    return result


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], sys.argv[2]))
