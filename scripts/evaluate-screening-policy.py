"""Conservative screening and automatic fallback: before/after evaluation.

offline: the 34 labelled preview frames (docs/benchmarks/vision-eval/labels.json) as a US NWS story.
  before = current production tier (heuristics + geographic gate); after = the same plus Apple Vision as weak
  evidence (cached results; can only hold 'auto' back for review) and the clean/ambiguous split that decides
  whether a beat searches for alternatives.
live: one plan's footage review without and with fallback (same process, so the second run measures cache
  reuse). Metadata searches and preview frames only: nothing is downloaded or imported.

Usage: .venv/bin/python scripts/evaluate-screening-policy.py offline
       .venv/bin/python scripts/evaluate-screening-policy.py live PLAN_ID DATA_DIR
"""
import asyncio, json, sys, time
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from PIL import Image
from app import footage_review as fr
from app.footage_vision import VisionScreen, findings
from app.visual_concepts import measure, beat_need
from app.media_selection import topics

DATA = ROOT / 'docs/benchmarks/vision-eval'
US = SimpleNamespace(title='Flash Flood Warning', provider='NWS')
UNTESTED = {'valid_us_urban_flooding': 'No real, geographically verified US urban-flood preview frames are available '
                                       '(Pexels US-city flood searches return foreign clips; Archive/FEMA open-licence searches returned 0; Commons unreachable). Untested.'}


def offline():
    examples = json.loads((DATA / 'labels.json').read_text())['examples']
    raw = VisionScreen(ROOT / '.local' / 'vision-eval').screen([DATA / e['frame'] for e in examples]) or {}
    rows = []
    for e in examples:
        frame = DATA / e['frame']
        candidate = {'id': e['clip_id'], 'title': e['title'], 'tags': sorted(topics(e['title'])), 'provider': e['provider'], 'height': e['height'],
                     'seconds': e['seconds'], 'reuse_basis': 'stock_license', 'license': e['licence'], 'description': e['title']}
        scene = {'script_segment': e['narration']};features = measure(Image.open(frame))
        before = fr.assess(candidate, scene, US, features)
        found = findings(raw.get(str(frame)), beat_need(e['narration']))
        after = fr.assess(candidate, scene, US, features, vision=found)
        rows.append({'title': e['title'], 'category': e['category'], 'relevant': e['relevant'], 'geo': e['geo'], 'before': before['tier'], 'after': after['tier'],
                     'clean_before': fr.clean(before), 'clean_after': fr.clean(after), 'vision_cues': (found or {}).get('setting_cues', []),
                     'compatibility': after['location'].get('geography', {}).get('compatibility')})
    accepted = lambda tier: tier in ('auto', 'recommended')
    valid = [r for r in rows if r['relevant'] and r['geo'] == 'ok']
    foreign = [r for r in rows if r['geo'] != 'ok']
    def side(key, clean_key):
        return {'auto': sum(r[key] == 'auto' for r in rows), 'recommended': sum(r[key] == 'recommended' for r in rows), 'weak': sum(r[key] == 'weak' for r in rows),
                'false_auto': [r['title'] for r in rows if r[key] == 'auto' and (not r['relevant'] or r['geo'] != 'ok')],
                'accepted_correct': sum(accepted(r[key]) == bool(r['relevant']) for r in rows),
                'valid_accepted': f"{sum(accepted(r[key]) for r in valid)}/{len(valid)}",
                'valid_clean_without_further_search': f"{sum(r[clean_key] for r in valid)}/{len(valid)}",
                'foreign_clean_offered': [r['title'] for r in foreign if r[clean_key]],
                'review_load_accepted_but_not_clean': sum(accepted(r[key]) and not r[clean_key] for r in rows)}
    report = {'examples': len(rows), 'vision_available': bool(raw), 'before': side('before', 'clean_before'), 'after': side('after', 'clean_after'),
              'tier_changes': [f"{r['title']}: {r['before']} -> {r['after']} ({'; '.join(r['vision_cues']) or 'vision issue'})" for r in rows if r['before'] != r['after']],
              'valid_held_for_fallback': [r['title'] for r in valid if not r['clean_after']],
              'valid_excluded': [r['title'] for r in valid if accepted(r['before']) and not accepted(r['after'])],
              'untested': UNTESTED, 'rows': rows}
    (DATA / 'policy-results.json').write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=1, ensure_ascii=False))


async def live(plan_id, data_dir):
    from fastapi.testclient import TestClient
    from app.main import create_app
    scratch = Path(data_dir)
    with TestClient(create_app(scratch)) as client:
        discovery = client.app.state.discovery;out = {}
        frames = scratch / 'frames';screener = VisionScreen(scratch)
        for name, options in (('before', {'fallback': False}), ('fallback', {'fallback': True}), ('fallback_and_vision', {'fallback': True, 'screener': screener, 'frames': frames})):
            started = time.monotonic()
            rows, warnings, stats = await fr.review(discovery, plan_id, **options)
            offered = [c for r in rows for c in r['candidates']]
            out[name] = {'seconds': round(time.monotonic() - started, 1), 'searches': stats,
                         'status': {s: sum(r['status'] == s for r in rows) for s in ('ready', 'review', 'needs_attention', 'graphics')},
                         'auto': sum(c['tier'] == 'auto' for c in offered), 'recommended': sum(c['tier'] == 'recommended' for c in offered),
                         'clean_offered': sum(fr.clean(c) for c in offered), 'distinct_clips': len({c['candidate_id'] for c in offered}),
                         'conflicts_auto': [c['title'] for c in offered if c['tier'] == 'auto' and (c['location'].get('geography') or {}).get('compatibility') in ('conflict', 'possible_conflict')],
                         'vision_held': [c['title'] for c in offered if c['location'].get('visual_setting')],
                         'warnings': warnings,
                         'beats': [{'narration': r['narration'][:80], 'concept': r['concept'], 'status': r['status'], 'fallback': r['fallback'],
                                    'offered': [(c['tier'], c['title'][:50], (c['location'].get('geography') or {}).get('compatibility')) for c in r['candidates']]} for r in rows]}
        print(json.dumps({k: {x: y for x, y in v.items() if x != 'beats'} for k, v in out.items()}, indent=1))
        (DATA / 'fallback-live-results.json').write_text(json.dumps({'plan_id': plan_id, 'runs': out}, indent=1))


if __name__ == '__main__':
    if sys.argv[1] == 'offline':
        offline()
    else:
        asyncio.run(live(sys.argv[2], sys.argv[3]))
