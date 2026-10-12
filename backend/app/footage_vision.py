"""Optional vision screening of footage preview frames. Footage review uses it only as weak evidence
(weak_evidence): it can hold a clip back from automatic selection, never exclude it. Not used by library ranking.

Uses Apple's on-device Vision framework (macOS) through a small Objective-C tool compiled on first use:
image classification labels plus recognized text. No network, no model download, nothing required at app
startup. When the tool cannot be built or run, every call returns None and callers keep the heuristics.

Findings are observable evidence only: visible scene labels, sky and weather cues, space/night imagery,
inland terrain, and possible setting cues (rickshaws, non-Latin signage). Geography is never identified;
setting cues are reported as uncertain. Licensing and provenance are not part of this.
"""
import hashlib
import json
import platform
import shutil
import subprocess
import unicodedata
from pathlib import Path

VERSION = 'apple-vision-1'
SOURCE = Path(__file__).parent / 'vision' / 'screen.m'
WATER = {'water', 'liquid', 'ocean', 'water_body', 'sea', 'waves', 'surf', 'rain', 'flood', 'river', 'puddle', 'wet'}
SKY_STORM = {'cloudy', 'overcast', 'storm', 'rain', 'fog', 'lightning'}
SPACE = {'celestial_body', 'celestial_body_other', 'night_sky', 'moon', 'planet', 'space', 'astronomy', 'satellite'}
INLAND = {'hill', 'mountain', 'mountains', 'land', 'forest', 'desert', 'canyon'}
SETTING = {'rickshaw', 'tuk_tuk', 'auto_rickshaw', 'pagoda', 'temple', 'mosque'}


class VisionScreen:
    def __init__(self, folder):
        self.folder = Path(folder) / 'vision';self.folder.mkdir(parents=True, exist_ok=True)
        self.cache = self.folder / f'cache-{VERSION}.json'
        try:
            self.results = json.loads(self.cache.read_text())
        except (OSError, ValueError):
            self.results = {}

    def tool(self):
        """Compiled screening tool, built once per source version; None where unavailable."""
        if platform.system() != 'Darwin' or not shutil.which('clang') or not SOURCE.exists():
            return None
        digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()[:12]
        binary = self.folder / f'screen-{digest}'
        if not binary.exists():
            built = subprocess.run(['clang', '-O2', '-fobjc-arc', '-framework', 'Foundation', '-framework', 'Vision', str(SOURCE), '-o', str(binary)],
                                   capture_output=True, timeout=120)
            if built.returncode:
                return None
        return binary

    def screen(self, frames):
        """Raw Vision output per frame path, cached by frame content and screening version."""
        keys = {str(f): hashlib.sha256(Path(f).read_bytes()).hexdigest() + ':' + VERSION for f in frames}
        missing = [f for f, k in keys.items() if k not in self.results]
        if missing:
            tool = self.tool()
            if tool is None:
                return None
            try:
                out = subprocess.run([str(tool), *missing], capture_output=True, text=True, timeout=30 + 5 * len(missing))
            except subprocess.SubprocessError:
                return None
            for line in out.stdout.splitlines():
                row = json.loads(line)
                if 'error' not in row:
                    self.results[keys[row['path']]] = {k: row[k] for k in ('labels', 'text', 'text_regions')}
            self.cache.write_text(json.dumps(self.results))
        return {f: self.results.get(k) for f, k in keys.items()}


def non_latin(text):
    """Letters from scripts other than Latin (e.g. Bengali, Thai, Devanagari, Chinese) in recognized text."""
    return [c for c in text if c.isalpha() and 'LATIN' not in unicodedata.name(c, '')]


def findings(raw, concept):
    """Structured, evidence-only findings for one frame and beat concept."""
    if not raw:
        return None
    labels = {name: conf for name, conf in raw['labels']}
    top = [name for name, _ in raw['labels'][:6]]
    def strongest(group):
        return max((labels.get(name, 0) for name in group), default=0)
    text = ' '.join(t for t, c in raw['text'] if c > .3)
    foreign_script = non_latin(text)
    sunlit = labels.get('blue_sky', 0)
    evidence = {'water': round(strongest(WATER), 2), 'stormy_sky': round(strongest(SKY_STORM), 2), 'blue_sky': round(sunlit, 2),
                'space': round(strongest(SPACE), 2), 'inland_terrain': round(strongest(INLAND), 2), 'palms': round(labels.get('palm_tree', 0), 2)}
    setting = []
    if strongest(SETTING) >= .2:
        setting.append('vehicle or building type common outside the US (' + ', '.join(n for n in SETTING if labels.get(n, 0) >= .2) + ')')
    if len(foreign_script) >= 3:
        setting.append('signage in a non-Latin script')
    issues = []
    active = concept in ('storm_surge', 'hurricane_wind', 'rainfall', 'flash_flood', 'general_context')
    if active and sunlit >= .8:
        issues.append(('sunlit blue sky', 'demote'))
    elif active and sunlit >= .6:
        issues.append(('blue sky visible', 'review'))
    if concept != 'forecast_warning' and evidence['space'] >= .1 and evidence['water'] < .3:
        issues.append(('space or night-sky imagery', 'demote'))
    if concept in ('storm_surge', 'forecast_warning', 'general_context') and evidence['inland_terrain'] >= .6 and evidence['water'] < .3:
        issues.append(('inland terrain, no water', 'demote'))
    if setting:
        issues.append(('possible setting outside the story region (uncertain)', 'review'))
    confidence = 'medium' if raw['labels'] and raw['labels'][0][1] >= .5 else 'low'
    return {'version': VERSION, 'visible_scene': top, 'evidence': evidence, 'setting_cues': setting,
            'issues': [i for i, _ in issues], 'actions': [a for _, a in issues], 'confidence': confidence,
            'rationale': '; '.join([f"sees {', '.join(top[:3])}" if top else 'no confident labels'] + [i for i, _ in issues])}


def weak_evidence(tier, found):
    """Production policy: vision findings are weak supporting evidence. They can only hold a clip back from
    automatic selection for a human look; they never demote it to weak, never exclude it and never create a
    geographic conflict (that needs metadata or a reviewer). Only setting cues hold a clip back: on the labelled
    frames the sky and night-sky labels held back valid clips and caught nothing the heuristics missed, so they
    are recorded for the reviewer without changing the tier."""
    if found and found['setting_cues'] and tier == 'auto':
        return 'recommended'
    return tier


def adjust(tier, found):
    """Experimental tier after vision evidence. Demotes on clear contradictions; caps at review when uncertain."""
    if not found:
        return tier
    if 'demote' in found['actions']:
        return 'weak'
    if 'review' in found['actions'] and tier == 'auto':
        return 'recommended'
    return tier
