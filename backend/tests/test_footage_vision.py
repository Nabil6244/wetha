"""Experimental vision screening: evidence-only findings, safe fallback, caching."""
from app import footage_vision as fv

SUNNY = {'labels': [['blue_sky', .97], ['palm_tree', .88], ['outdoor', .9]], 'text': [], 'text_regions': 0}
STORM = {'labels': [['liquid', .79], ['water', .79], ['ocean', .79], ['cloudy', .58]], 'text': [], 'text_regions': 0}
ABROAD = {'labels': [['people', .86], ['rickshaw', .31], ['bicycle', .6]], 'text': [['UltraTech', 1], ['วลูส้เดอ', .5]], 'text_regions': 2}
SPACE = {'labels': [['night_sky', .2], ['celestial_body', .12]], 'text': [], 'text_regions': 0}


def test_findings_are_observable_evidence_and_never_name_a_country():
    sunny = fv.findings(SUNNY, 'hurricane_wind')
    assert 'sunlit blue sky' in sunny['issues'] and fv.adjust('recommended', sunny) == 'weak'
    storm = fv.findings(STORM, 'storm_surge')
    assert storm['issues'] == [] and fv.adjust('auto', storm) == 'auto'
    abroad = fv.findings(ABROAD, 'flash_flood')
    assert abroad['setting_cues'] and 'uncertain' in abroad['issues'][0]
    assert fv.adjust('auto', abroad) == 'recommended' and fv.adjust('recommended', abroad) == 'recommended'  # review, not reject
    assert not any(country in str(abroad).lower() for country in ('india', 'bangladesh', 'thailand'))
    assert fv.adjust('recommended', fv.findings(SPACE, 'storm_surge')) == 'weak'
    assert fv.adjust('recommended', fv.findings(SPACE, 'forecast_warning')) == 'recommended'


def test_unavailable_vision_falls_back_to_the_heuristic_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(fv.platform, 'system', lambda: 'Linux')
    screener = fv.VisionScreen(tmp_path)
    frame = tmp_path / 'f.jpg';frame.write_bytes(b'not an image')
    assert screener.screen([frame]) is None
    assert fv.findings(None, 'storm_surge') is None and fv.adjust('auto', None) == 'auto'


def test_results_are_cached_by_frame_content_and_version(tmp_path, monkeypatch):
    calls = []
    screener = fv.VisionScreen(tmp_path)
    frame = tmp_path / 'f.jpg';frame.write_bytes(b'frame-bytes')
    class Done:
        stdout = '{"path": "%s", "labels": [["ocean", 0.9]], "text": [], "text_regions": 0}' % frame
    monkeypatch.setattr(screener, 'tool', lambda: tmp_path / 'tool')
    monkeypatch.setattr(fv.subprocess, 'run', lambda *a, **k: calls.append(a) or Done())
    first = screener.screen([frame]);second = fv.VisionScreen(tmp_path).screen([frame])
    assert first == second and len(calls) == 1
    assert fv.VERSION in next(iter(fv.VisionScreen(tmp_path).results))
