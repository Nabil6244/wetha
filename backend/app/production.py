"""Local, revision-bound production previews. No speech synthesis or broadcast control."""
import asyncio
import copy
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4, UUID
from concurrent.futures.process import BrokenProcessPool

from PIL import Image, ImageDraw, ImageFont

from .storage import RevisionConflict, now
from . import cinematic, broadcast, media_selection, regional, footage_library, audio_polish, production_report, packaging

MAX_UPLOAD = 250 * 1024 * 1024
RENDERER_VERSION = 17
MAX_MAP_SHOT_SECONDS = 10
MAX_PROGRAM_SECONDS = 7200
EXTENSIONS = {'image': {'.png', '.jpg', '.jpeg', '.webp'}, 'video': {'.mp4', '.mov', '.mkv', '.webm'},
              'audio': {'.wav', '.mp3', '.m4a', '.flac', '.ogg'}}


def still_motion(frames, seed):
    """Slow push or drift across a still image. Upscaled first so zoompan moves without stepping."""
    n = max(1, frames - 1)
    zoom, x, y = [
        (f'1+0.10*on/{n}', 'iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)'),           # push in
        (f'1.10-0.10*on/{n}', 'iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)'),        # pull out
        ('1.08', f'(iw-iw/zoom)*on/{n}', 'ih/2-(ih/zoom/2)'),                 # drift right
        ('1.08', f'(iw-iw/zoom)*(1-on/{n})', 'ih/2-(ih/zoom/2)'),             # drift left
    ][seed % 4]
    return (f"[0:v]scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,setsar=1,"
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s=1920x1080:fps=30,{footage_library.GRADE}[base]")


def render_workers():
    """Scenes rendered at once. Each uses two encoder threads; leave room for the app."""
    try:
        return max(1, int(os.environ['WETHA_RENDER_WORKERS']))
    except (KeyError, ValueError):
        return max(1, min(4, (os.cpu_count() or 2) // 2))


def final_encoder(seconds):
    """Long programs use the hardware encoder when present; WETHA_VIDEO_ENCODER overrides."""
    preference = os.environ.get('WETHA_VIDEO_ENCODER') or ('auto' if seconds >= 600 else 'software')
    return broadcast.encoder_args(preference)


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def probe(path):
    executable = shutil.which('ffprobe')
    if not executable:
        raise ValueError('FFprobe is required to validate imported media and rendered output.')
    try:
        result = subprocess.run([executable, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                                 '-show_format', '-show_streams', '-of', 'json', str(path)],
                                capture_output=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        if not data.get('streams'):
            raise ValueError('No usable media streams found.')
        return data
    except (subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise ValueError('The media file could not be decoded by FFprobe.') from error


def duration(info):
    try:
        value = float(info['format']['duration'])
        if not math.isfinite(value) or value <= 0 or value > MAX_PROGRAM_SECONDS:
            raise ValueError()
        return value
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError('Media must have a measurable duration of at most two hours.') from error


def text_pages(text, width=88, lines=6):
    rows = textwrap.wrap(' '.join(text.split()), width=width) or ['']
    return ['\n'.join(rows[index:index + lines]) for index in range(0, len(rows), lines)]


def caption_pages(text, width=42):
    lines = textwrap.wrap(' '.join(text.split()), width) or ['']
    return ['\n'.join(lines[i:i+2]) for i in range(0, len(lines), 2)]


def srt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, ms = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{ms:03}'


class Production:
    def __init__(self, store, describe_script, describe_scripts=None):
        self.store = store
        self.describe_script = describe_script
        self.describe_scripts = describe_scripts
        self.root = store.path.parent / 'production'
        (self.root / 'media').mkdir(parents=True, exist_ok=True)
        (self.root / 'renders').mkdir(exist_ok=True)
        (self.root / 'observations').mkdir(exist_ok=True)
        self.tasks = {}
        self.serial = asyncio.Semaphore(1)
        self.imports = asyncio.Lock()
        self._pool = None

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def runtime(self):
        return {'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe')),
                'local_voiceover': False, 'output': '1920×1080 · 30 fps · H.264 / AAC',
                'max_upload_bytes': MAX_UPLOAD}

    def state(self):
        timelines = self.store.production_list('timelines')
        scripts = self.describe_scripts({t['script_id'] for t in timelines}) if self.describe_scripts and timelines else {}
        described = {t['id']:self.describe_timeline(t, scripts.get(t['script_id'])) for t in timelines}
        return {'runtime': self.runtime(), 'media': self.store.production_list('media'),
                'timelines': list(described.values()),
                'renders': [{**r, 'timeline_state':described[r['timeline_id']]} for r in self.store.production_list('renders')],
                'benchmark': self.benchmark_info(), 'complete_episode': self.episode_info(),
                'hour_graphics': self.hour_graphics_info(), 'documentary': self.documentary_info(),
                'regional_chapter': self.regional_chapter_info(),
                'forecast_news': self.forecast_news_info(), 'user_report': self.user_report_info(),
                'regions': regional.options(), 'regional_coverage': regional.coverage(self.store.visual_plans(), self.store.production_list('media'))}

    def user_report_info(self):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/user-voiceover-v2'
        try:
            manifest = json.loads((folder / 'manifest.json').read_text())
            return {'available':(folder / 'isaias-user-voiceover-v2.mp4').is_file(),
                    'title':'Your voiceover · geographic weather edit', 'seconds':manifest['output']['seconds'],
                    'shots':len(manifest['shots']), 'visual_revision':manifest['visual_revision']}
        except (OSError,ValueError,KeyError):
            return {'available':False}

    def user_report_path(self, kind):
        names = {'video':'isaias-user-voiceover-v2.mp4','manifest':'manifest.json','subtitles':'captions.srt'}
        if kind not in names:raise ValueError('Unknown narrated report artifact.')
        folder = Path(__file__).resolve().parents[2] / '.local/exports/user-voiceover-v2'
        manifest = json.loads((folder / 'manifest.json').read_text())
        if checksum(folder / names['video']) != manifest['output']['checksum']:
            raise ValueError('Narrated report changed after validation; render it again.')
        return folder / names[kind]

    def forecast_news_info(self):
        from .forecast_news import snapshot_status
        folder = Path(__file__).resolve().parents[2] / '.local/exports/forecast-news'
        try:
            manifest = json.loads((folder / 'manifest.json').read_text())
            if not (folder / 'florida-forecast-bulletin.mp4').is_file():
                return {'available': False}
            return snapshot_status(manifest, datetime.now(timezone.utc))
        except (OSError, ValueError, KeyError):
            return {'available': False}

    def forecast_news_path(self, kind):
        names = {'video': 'florida-forecast-bulletin.mp4', 'manifest': 'manifest.json',
                 'subtitles': 'captions.srt', 'narration': 'narration.wav'}
        if kind not in names:
            raise ValueError('Unknown forecast bulletin artifact.')
        folder = Path(__file__).resolve().parents[2] / '.local/exports/forecast-news'
        manifest = json.loads((folder / 'manifest.json').read_text())
        if checksum(folder / names['video']) != manifest['output']['checksum']:
            raise ValueError('Forecast bulletin changed after validation; render it again.')
        return folder / names[kind]

    def regional_chapter_info(self):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/florida-chapter'
        try:
            manifest = json.loads((folder / 'manifest.json').read_text())
            return {'available': (folder / 'south-florida-chapter.mp4').is_file(),
                    'title': manifest['title'], 'seconds': manifest['output']['seconds']}
        except (OSError, ValueError, KeyError):
            return {'available': False}

    def regional_chapter_path(self, kind):
        names = {'video': 'south-florida-chapter.mp4', 'manifest': 'manifest.json',
                 'subtitles': 'captions.srt', 'narration': 'narration.wav'}
        if kind not in names:
            raise ValueError('Unknown regional chapter artifact.')
        folder = Path(__file__).resolve().parents[2] / '.local/exports/florida-chapter'
        manifest = json.loads((folder / 'manifest.json').read_text())
        if checksum(folder / names['video']) != manifest['output']['checksum']:
            raise ValueError('Regional chapter changed after validation; render it again.')
        return folder / names[kind]

    def documentary_info(self):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/documentary'
        try:
            manifest = json.loads((folder / 'manifest.json').read_text())
            return {'available': (folder / 'isaias-documentary-90.mp4').is_file(),
                    'title': manifest['title'], 'output': manifest['output']}
        except (OSError, ValueError, KeyError):
            return {'available': False}

    def documentary_path(self, kind):
        names = {'video': 'isaias-documentary-90.mp4', 'manifest': 'manifest.json', 'subtitles': 'captions.srt'}
        if kind not in names:
            raise ValueError('Unknown documentary artifact.')
        folder = Path(__file__).resolve().parents[2] / '.local/exports/documentary'
        manifest = json.loads((folder / 'manifest.json').read_text())
        if checksum(folder / names['video']) != manifest['output']['checksum']:
            raise ValueError('Documentary changed after validation; render it again.')
        return folder / names[kind]

    def hour_graphics_info(self):
        folder=Path(__file__).resolve().parents[2]/'.local/exports/hour-graphics'
        try:
            manifest=json.loads((folder/'manifest.json').read_text())
            return {'available':(folder/'hour-graphics-60.mp4').is_file(),'output':manifest['output']}
        except (OSError,ValueError,KeyError):return {'available':False}

    def hour_graphics_path(self,kind):
        folder=Path(__file__).resolve().parents[2]/'.local/exports/hour-graphics'
        manifest=json.loads((folder/'manifest.json').read_text())
        video=folder/'hour-graphics-60.mp4'
        if checksum(video)!=manifest['output']['checksum']:raise ValueError('Graphics proof changed after validation; render it again.')
        return video if kind=='video' else folder/'manifest.json'

    def episode_info(self):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/complete-episode'
        try:
            manifest = json.loads((folder / 'manifest.json').read_text())
            return {'available': (folder / 'episode-60.mp4').is_file(),
                    'title': manifest['title'], 'output': manifest['output']}
        except (OSError, ValueError, KeyError):
            return {'available': False}

    def episode_path(self, kind):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/complete-episode'
        manifest = json.loads((folder / 'manifest.json').read_text())
        video = folder / 'episode-60.mp4'
        if checksum(video) != manifest['output']['checksum']:
            raise ValueError('Episode changed after validation; render it again.')
        return video if kind == 'video' else folder / 'manifest.json'

    def benchmark_info(self):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/phase7'
        try:
            manifest = json.loads((folder / 'manifest.json').read_text())
            return {'available': (folder / 'phase7-isaias-30s.mp4').exists(), 'event_id': manifest['event_id'],
                    'output': manifest['output'], 'limitations': manifest['limitations']}
        except (OSError, ValueError, KeyError):
            return {'available': False}

    def benchmark_path(self, kind):
        folder = Path(__file__).resolve().parents[2] / '.local/exports/phase7'
        manifest = json.loads((folder / 'manifest.json').read_text())
        video = folder / 'phase7-isaias-30s.mp4'
        if checksum(video) != manifest['output']['checksum']:
            raise ValueError('Benchmark video changed after validation; render it again.')
        return video if kind == 'video' else folder / 'manifest.json'

    def media_path(self, document):
        # IDs/filenames are generated here; request paths never become local file paths.
        path = self.root / 'media' / document['filename']
        if not path.is_file() or checksum(path) != document['checksum']:
            raise ValueError('Imported media is missing or its checksum changed. Import the original file again.')
        return path

    async def import_media(self, metadata, stream):
        async with self.imports:
            return await self._import_media(metadata, stream)

    async def _import_media(self, metadata, stream):
        if '/' in metadata.name or '\\' in metadata.name or '\0' in metadata.name:
            raise ValueError('Choose a plain filename without directory components.')
        suffix = Path(metadata.name).suffix.lower()
        if suffix not in EXTENSIONS[metadata.kind]:
            raise ValueError('Unsupported file extension for this media type.')
        if (metadata.kind == 'audio') != (metadata.context == 'narration'):
            raise ValueError('Audio imports are narration; images and footage must be illustrative or archival.')
        identity = str(uuid4())
        temporary = self.root / 'media' / (identity + '.upload' + suffix)
        size = 0
        try:
            with temporary.open('wb') as output:
                async for chunk in stream:
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise ValueError('Media imports are limited to 250 MiB per file.')
                    output.write(chunk)
            if not size:
                raise ValueError('The imported file is empty.')
            digest = await asyncio.to_thread(checksum, temporary)
            existing = next((a for a in self.store.production_list('media') if a['checksum'] == digest), None)
            if existing:
                fields = ('kind', 'context', 'license', 'attribution', 'source', 'rights_confirmed', 'source_provider', 'reuse_basis', 'reuse_evidence', 'preferred_clip_seconds')
                if any(existing.get(k, {'source_provider':'local','reuse_basis':None,'reuse_evidence':'','preferred_clip_seconds':3.5}.get(k)) != getattr(metadata, k) for k in fields):
                    raise ValueError('This file already has a different license/provenance record. The original record was preserved.')
                original = self.root / 'media' / existing['filename']
                if not original.exists() or checksum(original) != digest:
                    temporary.replace(original)
                return {**existing, 'duplicate': True}
            info = await asyncio.to_thread(probe, temporary)
            visual = next((s for s in info['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
            audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
            measured = None;shots = None
            if metadata.kind in ('image', 'video'):
                if not visual or not 1 <= visual.get('width', 0) <= 8192 or not 1 <= visual.get('height', 0) <= 8192:
                    raise ValueError('A visual stream with dimensions up to 8192 pixels is required.')
                if metadata.kind == 'image':
                    def inspect_image():
                        with Image.open(temporary) as image:
                            if image.format not in ('PNG', 'JPEG', 'WEBP') or getattr(image, 'n_frames', 1) != 1:
                                raise ValueError('Import a still PNG, JPEG or WebP image.')
                            image.verify()
                    try:
                        await asyncio.to_thread(inspect_image)
                    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
                        raise ValueError('The imported image is not a valid still image.') from error
                else:
                    measured = duration(info)
                    shots = await asyncio.to_thread(footage_library.detect_shots, temporary, measured)
            elif not audio or visual:
                raise ValueError('Import an audio-only narration file.')
            else:
                measured = duration(info)
            document = {**metadata.model_dump(), 'id': identity, 'checksum': digest, 'bytes': size,
                        'filename': identity + suffix, 'content_type': mimetypes.guess_type(metadata.name)[0] or 'application/octet-stream',
                        'seconds': measured, 'width': visual['width'] if visual else None,
                        'height': visual['height'] if visual else None, 'created_at': now()}
            if shots is not None:
                document['shot_starts'] = shots
            temporary.replace(self.root / 'media' / document['filename'])
            self.store.production_save('media', document)
            return document
        finally:
            temporary.unlink(missing_ok=True)

    def storyboard(self, timeline):
        """Contact sheet and animatic for a timeline (saved or prepared), before rendering."""
        from . import storyboard
        identity = str(uuid4());directory = self.root / 'storyboards' / identity
        media = {m['id']: m for m in self.store.production_list('media')}
        audio = self.media_path(media[timeline['narration_id']]) if timeline.get('narration_id') else None
        result = storyboard.build(self, timeline, media, directory, audio)
        return {'id': identity, **result}

    def storyboard_path(self, identity, kind):
        names = {'sheet': 'storyboard.jpg', 'preview': 'preview.mp4', 'json': 'storyboard.json'}
        str(UUID(identity))  # Only generated identifiers become paths.
        path = self.root / 'storyboards' / identity / names[kind]
        if not path.is_file():
            raise KeyError(identity)
        return path

    def analyze_shots(self):
        """Backfill internal shot changes for library videos imported before shot analysis."""
        analyzed, failed = 0, []
        for asset in self.store.production_list('media'):
            if asset['kind'] != 'video' or 'shot_starts' in asset:
                continue
            try:
                shots = footage_library.detect_shots(self.media_path(asset), asset['seconds'])
            except (ValueError, OSError):
                shots = None
            if shots is None:
                failed.append(asset['name']);continue
            self.store.production_update_media({**asset, 'shot_starts': shots})
            analyzed += 1
        return {'analyzed': analyzed, 'failed': failed}

    def validate_plan(self, plan, require_support=True):
        script = self.describe_script(self.store.script(plan['script_id']))
        if script['revision'] != plan['script_revision'] or hashlib.sha256(script['text'].encode()).hexdigest() != plan['script_text_checksum']:
            raise RevisionConflict('The script changed. Create a new visual plan and timeline from the latest revision.')
        if require_support and (not script.get('claims') or any(c['status'] == 'requires_verification' for c in script['claims'])):
            audit = script.get('preview_audit', {})
            if not audit.get('ready'):
                details = [f"Paragraph {i+1}: unsupported values {', '.join(row['unsupported_numbers']+row['conflicts'])}" for i,row in enumerate(audit.get('claims', [])) if row['status']=='needs_attention']
                raise ValueError('Automatic source check needs attention. ' + ' '.join(details) if details else 'Resolve unsupported script claims before rendering a production preview.')
        if any(issue['code'] == 'missing_context' for issue in script['editorial']['issues']):
            raise ValueError('Restore the original source-context opening before rendering.')
        if any(self.store.advisory(row['id']).checksum != row['checksum'] for row in plan['evidence_manifest']):
            raise ValueError('The pinned evidence manifest no longer matches preserved source content.')
        if script['label'] in ('withdrawn', 'cancelled', 'quarantined'):
            raise ValueError('Withdrawn, cancelled or quarantined evidence cannot start a new render.')
        return script

    def catalog_media(self, identity, body):
        asset = self.store.production_get('media', identity)
        if asset['kind'] == 'audio':
            raise ValueError('Catalogue weather footage or images; narration is not suggested as a visual.')
        self.media_path(asset)
        if asset['kind'] == 'video' and body.preferred_trim_start and body.preferred_trim_start + min(4, max(3, asset.get('preferred_clip_seconds', 3.5))) > asset['seconds'] + .01:
            raise ValueError('The preferred trim leaves less than a complete 3–4 second cut.')
        if asset['kind'] == 'image' and body.preferred_trim_start:
            raise ValueError('Still images do not have a trim point.')
        return self.store.production_catalog(identity, body.model_dump(mode='json'))

    def story(self, body):
        from .story import build
        plan = self.store.visual_plan(body.plan_id)
        script = self.validate_plan(plan)
        if len(script.get('selected_advisory_ids', [])) > 1:
            raise ValueError('Combined drafts already preserve topic order. Edit their narration directly instead of applying a single-storm story rewrite.')
        if plan.get('story_version'):
            raise ValueError('This plan already contains a story draft. Select the original plan to rebuild.')
        result = build({**plan, 'source_label':script['label']}, self.store.advisory(script['advisory_id']))
        self.store.save_visual_plan(result)
        return result

    def assist(self, body):
        plan = self.store.visual_plan(body.plan_id)
        script = self.validate_plan(plan)
        plan = copy.deepcopy(plan)
        known = {s['id'] for s in plan['scenes']}
        if set(body.regional_focus)-known:
            raise ValueError('Regional focus names an unknown scene.')
        allowed = {r['code'] for r in regional.options()} | {'auto'}
        for scene in plan['scenes']:
            focus = body.regional_focus.get(scene['id'],'auto')
            if focus not in allowed:raise ValueError('Unknown regional focus.')
            scene['regional_focus'] = focus
            regional.targets(scene)
        media = self.store.production_list('media')
        unavailable = []
        for asset in media:
            if asset['kind'] == 'audio':
                continue
            try:
                self.media_path(asset)
            except (ValueError, OSError):
                unavailable.append(asset['id'])
        result = media_selection.draft(plan, media, self.store.advisory(script['advisory_id']), unavailable, body.template)
        for row,scene in zip(result['scenes'],plan['scenes']):
            row['regional_focus']=scene['regional_focus']
        result['regional_requirements'] = [{'scene_id':s['id'],'regions':regional.targets(s)} for s in plan['scenes'] if regional.targets(s)]
        result['plan_id'] = plan['id']
        result['script_revision'] = plan['script_revision']
        result['issues'] += [{'code': 'unavailable_media', 'message': 'Media file missing or checksum mismatch: ' + asset['name']} for asset in media if asset['id'] in unavailable]
        return result

    def check_timeline(self, body):
        try:
            timeline = self.create_timeline(body, persist=False)
        except (ValueError, KeyError, OSError) as error:
            return {'ready': False, 'issues': [{'code': 'invalid_timeline', 'message': str(error)}]}
        issues = []
        for scene in timeline['scenes']:
            if body.presentation == 'broadcast' and not scene['media_id'] and not scene.get('cuts'):
                if scene['direction'].get('fallback'):
                    issues.append({'scene_id': scene['id'], 'code': 'graphic_fallback', 'message': scene['direction']['fallback']})
                if scene['parameters'].get('unavailable_requested_layer'):
                    issues.append({'scene_id': scene['id'], 'code': 'missing_observation', 'message': scene['parameters'].get('reason', 'Observation layer unavailable.')})
        issues += [{'scene_id':s['id'], 'code':'missing_regional_weather', 'message':s['parameters'].get('fallback_label','Local weather layer unavailable.')} for s in timeline['scenes'] if s.get('regional_relevance',{}).get('status')=='missing_regional_weather']
        coverage = self.visual_coverage(timeline)
        if body.presentation == 'broadcast':
            if not coverage['footage_clips']:
                issues.append({'code':'no_footage', 'message':'No footage selected. This export will contain maps and graphics only.'})
            if not coverage['observation_scenes']:
                issues.append({'code':'no_observations', 'message':'No satellite or radar observations selected. Geographic maps alone do not show observed weather.'})
            if coverage['longest_graphic_seconds'] > 12:
                issues.append({'code':'long_visual_hold', 'message':f"The longest map/graphic holds for {coverage['longest_graphic_seconds']:g} seconds. Add visual changes and footage before treating this as a finished edit."})
        map_issues = self.map_hold_issues(timeline)
        issues += map_issues
        missing_long_footage = timeline.get('bulletin_target_minutes',0)>=30 and timeline['seconds']>=600 and not coverage['footage_clips']
        return {'ready': not bool(map_issues) and not missing_long_footage, 'seconds': timeline['seconds'], 'issues': issues,
                'visual_coverage':coverage,
                'note': 'Technical render checks only. Review the visual mix separately.'}

    @staticmethod
    def map_hold_issues(timeline):
        issues = []
        for index, scene in enumerate(timeline['scenes']):
            if scene.get('media_id') or scene.get('cuts'):
                continue
            direction = scene.get('direction',{})
            kind = direction.get('scene_type',scene.get('type'))
            if kind not in ('storm_track','cinematic_weather_map','region_focus','satellite_wide','satellite_timelapse','radar_animation'):
                continue
            # A chart over cartography is a statistical shot, not a map hold.
            if scene['parameters'].get('report_graphs') or scene.get('graphic_style','auto')!='auto':
                continue
            handle = .3 if timeline.get('presentation')=='broadcast' and index and timeline['scenes'][index-1].get('transition')=='fade' else 0
            if round((scene['seconds']+handle)*30) > MAX_MAP_SHOT_SECONDS*30:
                issues.append({'scene_id':scene['id'],'code':'map_hold_limit',
                    'message':f"Map shot {index+1} lasts {scene['seconds']+handle:g} seconds. Maximum is 10 seconds, including transitions. Split it into distinct shots or add footage; preserve the narration duration."})
        return issues

    @staticmethod
    def visual_coverage(timeline):
        scenes = timeline['scenes']
        footage = [s for s in scenes if s.get('media_id') or s.get('cuts')]
        return {'footage_clips':sum(len(s.get('cuts',[])) or 1 for s in footage),
                'footage_seconds':round(sum(s['seconds'] for s in footage),1),
                'graph_scenes':sum(bool(s['parameters'].get('report_graphs')) or s.get('direction',{}).get('scene_type')=='statistics' for s in scenes),
                'observation_scenes':sum(bool(s.get('direction',{}).get('asset_ids')) for s in scenes),
                'longest_graphic_seconds':round(max((s['seconds'] for s in scenes if not s.get('media_id') and not s.get('cuts')),default=0),1)}

    def create_timeline(self, body, persist=True):
        plan = self.store.visual_plan(body.plan_id)
        script = self.validate_plan(plan)
        if len(script.get('selected_advisory_ids', [])) > 1 and body.presentation != 'broadcast':
            raise ValueError('Combined topics require Broadcast style to retain each topic’s source geography.')
        if body.presentation == 'cinematic' and (not body.satellite_context or any(s.media_id for s in body.scenes)):
            raise ValueError('Cinematic presentation requires satellite context and no imported scene media.')
        if body.music and body.narration_id:
            raise ValueError('Choose imported narration or the original instrumental bed for this preview.')
        if [s.id for s in body.scenes] != [s['id'] for s in plan['scenes']]:
            raise ValueError('Preserve every scene once and in its source-linked order.')
        media = {m['id']: m for m in self.store.production_list('media')}
        observations = self.pin_observations(script) if body.satellite_context and body.presentation != 'broadcast' else []
        scenes = []
        for index, (requested, original) in enumerate(zip(body.scenes, plan['scenes'])):
            if requested.map_mode != 'auto' and (body.presentation != 'broadcast' or requested.media_id or requested.cuts):
                raise ValueError('Map scenes require Broadcast style and no imported footage in that scene.')
            if requested.graphic_style != 'auto' and (body.presentation != 'broadcast' or requested.media_id or requested.cuts):
                raise ValueError('Motion graphics require Broadcast style and no imported footage in that scene.')
            if requested.graphic_style != 'auto' and requested.map_mode not in ('auto','forecast'):
                raise ValueError('Choose a map or a motion graphic for this scene, not both.')
            frames = round(requested.seconds * 30)
            seconds = frames / 30
            asset = media.get(requested.media_id) if requested.media_id else None
            cuts = []
            if requested.cuts:
                if body.presentation != 'broadcast' or requested.media_id or requested.trim_start:
                    raise ValueError('Footage sequences require Broadcast style with no single scene media or trim.')
                if requested.transition != 'cut' or (index and body.scenes[index-1].transition != 'cut'):
                    raise ValueError('Use cuts before and after footage sequences.')
                if sum(round(c.seconds*30) for c in requested.cuts) != frames:
                    raise ValueError('Footage cuts must total the scene duration exactly.')
                for cut in requested.cuts:
                    selected = media.get(cut.media_id)
                    if not selected or selected['kind'] == 'audio':
                        raise ValueError('Every footage cut needs an imported image or video.')
                    self.media_path(selected)
                    cut_seconds = round(cut.seconds*30)/30
                    if selected['kind'] == 'video' and cut.trim_start+cut_seconds > selected['seconds']+.01:
                        raise ValueError('A footage cut exceeds the source duration; looping is not allowed.')
                    if selected['kind'] == 'image' and cut.trim_start:
                        raise ValueError('Still images do not have trim points.')
                    cuts.append({**cut.model_dump(), 'seconds':cut_seconds, 'selection_catalog':selected.get('catalog',{})})
            if requested.media_id and not asset:
                raise KeyError(requested.media_id)
            if asset:
                if asset['kind'] == 'audio':
                    raise ValueError('Use images or video footage for scene visuals.')
                self.media_path(asset)
                handle = .3 if body.presentation == 'broadcast' and index > 0 and body.scenes[index-1].transition == 'fade' else 0
                if asset['kind'] == 'video' and requested.trim_start + seconds + handle > asset['seconds'] + 0.01:
                    raise ValueError(f"{asset['name']} is too short for this scene and trim point. Footage is never looped automatically.")
                if asset['kind'] == 'image' and requested.trim_start:
                    raise ValueError('Still images do not have a trim point.')
            elif requested.trim_start:
                raise ValueError('Source cards do not have a trim point.')
            scenes.append({**copy.deepcopy(original), **requested.model_dump(), 'seconds': seconds, 'frames': frames,
                           'cuts': cuts,
                           'selection_catalog': asset.get('catalog', {}) if asset else {},
                           'observations': observations if not asset else []})
        audit = script.get('preview_audit')
        if audit and audit['ready']:
            from .visuals import VisualEvidence
            visual = VisualEvidence(self.store)
            support = {r['claim_id']:r for r in audit['claims']}
            geography = {}
            for scene in scenes:
                row = support.get(scene.get('claim_id'))
                if not row or not row['primary_advisory_id']:continue
                identity = row['primary_advisory_id']
                if identity not in geography:geography[identity] = visual.geography(identity)
                p = scene['parameters']
                if p.get('source_advisory_id') != identity:
                    # Remove layers tied to the previous story rather than reattribute them.
                    for key in ('asset_ids','map_observations','report_graphs','location_labels','regional_weather'):
                        p.pop(key,None)
                    if scene['type'] in ('satellite_timelapse','satellite_wide','radar_animation'):
                        scene['type']='cinematic_weather_map'
                all_features=[]
                for source_id in row['source_advisory_ids']:
                    if source_id not in geography:geography[source_id]=visual.geography(source_id)
                    all_features.extend(geography[source_id]['geojson']['features'])
                p.update(source_advisory_id=identity,geojson={'type':'FeatureCollection','features':all_features})
                scene['source_refs']=row['source_advisory_ids']
                scene['source_advisory_ids']=row['source_advisory_ids']
                scene['source_audit']=row
                scene['advisory_timestamp']=self.store.advisory(identity).issued_at.isoformat()
        from .location_labels import apply as apply_places
        for scene in scenes:
            apply_places(scene['parameters'], self.store.advisory(scene['parameters'].get('source_advisory_id',script['advisory_id'])),scene['script_segment'])
        if body.presentation == 'broadcast':
            advisory = self.store.advisory(script['advisory_id'])
            story_layers = {}
            for scene in scenes:
                advisory = self.store.advisory(scene['parameters'].get('source_advisory_id', script['advisory_id']))
                source = broadcast.VisualSource(source_url=advisory.source_url, checksum=advisory.checksum,
                    event_id=advisory.event_key, data_type='reported_center', historical=script['label'] != 'current',
                    observation_start=advisory.issued_at, observation_end=advisory.issued_at,
                    advisory_issue_time=advisory.issued_at, coverage='Source-reported geography', projection='EPSG:4326',
                    attribution=advisory.provider, license='Source advisory; provenance in evidence manifest', catalogue_url=advisory.source_url)
                scene['direction'] = broadcast.director(scene, advisory.event_key, scene['seconds'], advisory.facts, source)
                if scene['media_id'] or scene['cuts']:
                    asset = media[scene['media_id'] or scene['cuts'][0]['media_id']]
                    scene['direction'].update(scene_type='ground_footage',headline=asset['context'].upper()+' FOOTAGE',
                        layers=['ground'],fallback='Imported contextual media; event/date/location attribution is not verified.')
                if scene['parameters'].get('story'):
                    scene['parameters']['story']['source_label'] = script['label']
                scene['parameters']['facts'] = advisory.facts
                if not scene['parameters'].get('geojson'):
                    # Borrow geography only from the same story; another topic's area would mislocate this one.
                    scene['parameters']['geojson'] = next((s['parameters']['geojson'] for s in scenes if s['parameters'].get('geojson')
                        and s['parameters'].get('source_advisory_id', script['advisory_id']) == advisory.id), None) or self.story_geography(advisory.id)
                scene['parameters']['credit'] = advisory.provider + ' · issued ' + advisory.issued_at.isoformat() + ' · Natural Earth'
                scene['parameters']['fallback_label'] = 'No verified event imagery; source geography retained'
                if scene['map_mode'] != 'auto':
                    from .map_scenes import prepare
                    scene['direction'] = prepare(self, scene, advisory, source)
                elif scene['type']=='satellite_timelapse' and scene['parameters'].get('asset_ids') and not scene['media_id'] and not scene['cuts']:
                    pinned = self.pin_observations({'advisory_id':advisory.id, 'source_issued_at':advisory.issued_at.isoformat()})
                    wanted = set(scene['parameters']['asset_ids'])
                    selected = [a for a in pinned if a['id'] in wanted]
                    if len(selected) < 2:
                        raise ValueError('The planned satellite sequence is unavailable. Collect matching observations and prepare a new plan.')
                    scene['parameters']['map_observations'] = selected
                    observation_sources = [broadcast.VisualSource(**{**source.model_dump(),
                        'data_type':'satellite_observation','source_url':a['source_url'],'checksum':a['checksum'],
                        'observation_start':datetime.fromisoformat(a['observed_at']),
                        'observation_end':datetime.fromisoformat(a['observed_at']),
                        'projection':'native_viewport','coverage':'Gulf/Atlantic regional context; event attribution unverified',
                        'attribution':'NOAA / NESDIS / STAR','license':a['license'],'catalogue_url':a['source_url']}) for a in selected]
                    scene['direction'] = broadcast.SceneDirection(scene_type='satellite_timelapse',event_id=advisory.event_key,
                        duration=scene['seconds'],headline='SATELLITE OBSERVATIONS',layers=['satellite'],
                        asset_ids=[a['id'] for a in selected],sources=observation_sources,
                        camera=broadcast.Camera(movement='smooth_zoom_in',end_zoom=1.06)).model_dump(mode='json')
                    scene['parameters']['credit']='NOAA / NESDIS / STAR · Regional observation context · independent observation times'
                if scene['graphic_style'] != 'auto':
                    from .graphic_styles import prepare as prepare_graphic
                    prepare_graphic(scene,advisory)
                if body.automatic_graphs and scene['map_mode'] == 'auto' and scene['graphic_style'] == 'auto' and not scene['media_id'] and not scene['cuts']:
                    # Real data layers the director may choose for this story: county outlines, radar, satellite.
                    if advisory.id not in story_layers:
                        from . import geography, observations
                        story_layers[advisory.id] = {
                            'county_shapes': geography.county_shapes(self.store, advisory) if advisory.provider == 'NWS' else [],
                            'radar_option': observations.radar_option(self, advisory, scene['parameters'], source),
                            'satellite_option': observations.satellite_option(self, advisory, scene['parameters'], source)}
                    for key, value in story_layers[advisory.id].items():
                        if value:
                            scene['parameters'][key] = value
        plotted_claims={}
        for scene in scenes:
            scene['regional_relevance'] = regional.focus(scene, media, body.presentation, body.unverified_location_footage)
            if body.automatic_graphs and body.presentation == 'broadcast':
                from .report_graphs import prepare as prepare_report_graphs
                advisory = self.store.advisory(scene['parameters'].get('source_advisory_id', script['advisory_id']))
                graph = prepare_report_graphs(scene, advisory)
                if graph:
                    key=(graph['source_advisory_id'],tuple((c['field'],tuple(c.get('range',[]))) for c in graph['charts']))
                    # Shots split from one section share its chart; other sections do not repeat it.
                    section = scene.get('parent_scene_id', scene['id'])
                    if plotted_claims.setdefault(key, section) == section:
                        scene['parameters']['report_graphs'] = graph
        if body.automatic_graphs and body.presentation == 'broadcast':
            # Severe-weather beats get the SPC outlook valid at their story time, when one was collected.
            from . import spc
            from .visual_director import classify, story_text
            for scene in scenes:
                if scene.get('media_id') or scene.get('cuts'):
                    continue
                advisory = self.store.advisory(scene['parameters'].get('source_advisory_id', script['advisory_id']))
                intent = classify(scene['script_segment'], story_text(advisory))
                if intent['intent'] == 'tornado' or intent['hazard'] in ('tornado', 'severe_storm'):
                    outlook = spc.find(self.store, advisory.issued_at)
                    if outlook:
                        scene['parameters']['outlook'] = outlook
            from .visual_states import assign as assign_states
            assign_states(scenes, lambda identity: self.store.advisory(identity or script['advisory_id']))
        visual_plan = []
        if body.presentation == 'broadcast':
            from .visual_states import transitions
            from .visual_director import annotate
            transitions(scenes)
            visual_plan = annotate(scenes, lambda identity: self.store.advisory(identity or script['advisory_id']), media)
        total = sum(s['frames'] for s in scenes) / 30
        targets = {'short_30':30,'report_60':60,'report_90':90}
        if body.template and total != targets[body.template]:
            raise ValueError(f'The selected template must total exactly {targets[body.template]} seconds. Reapply the template or use manual timing.')
        if body.template in ('report_60','report_90'):
            ranges = {}
            for scene in scenes:
                if not scene['cuts'] and scene['seconds'] > 6:
                    raise ValueError('Report templates keep graphic holds at six seconds or less. Add footage cuts.')
                for cut in scene['cuts']:
                    start, end = cut['trim_start'], cut['trim_start']+cut['seconds']
                    selected = media[cut['media_id']]
                    previous = ranges.setdefault(cut['media_id'], [])
                    if previous and (selected['kind']=='image' or any(start < b-.01 and end > a+.01 for a,b in previous)):
                        raise ValueError('Report templates cannot repeat images or overlap footage ranges.')
                    previous.append((start,end))
        if total > MAX_PROGRAM_SECONDS:
            raise ValueError('A video timeline is limited to two hours. Split longer programs into separate videos.')
        narration = media.get(body.narration_id) if body.narration_id else None
        if body.narration_id:
            if not narration:
                raise KeyError(body.narration_id)
            if narration['kind'] != 'audio' or not body.narration_verified:
                raise ValueError('Select narration audio and confirm that it matches this script revision.')
            self.media_path(narration)
            if abs(total - narration['seconds']) > 0.2:
                raise ValueError('Scene timing must match measured narration duration within 0.2 seconds.')
        aligned = None
        if body.alignment_id:
            job = self.alignment_jobs.get(body.alignment_id)
            if job['status'] != 'completed' or job['plan_id'] != plan['id'] or job['narration_id'] != body.narration_id or job['script_text_checksum'] != plan['script_text_checksum'] or not narration or job['audio_checksum'] != narration['checksum']:
                raise ValueError('Speech alignment belongs to a different script or audio. Align the current recording again.')
            aligned = job['result']
            if [(s['id'], round(s['seconds']*30)) for s in scenes] != [(s['id'], round(s['seconds']*30)) for s in aligned['scenes']]:
                raise ValueError('Scene durations changed after speech alignment. Realign or use manual timing.')
        document = {'id': str(uuid4()), 'plan_id': plan['id'], 'script_id': script['id'],
                    'script_revision': script['revision'], 'script_text_checksum': plan['script_text_checksum'],
                    'title': body.title.strip(), 'source_label': script['label'], 'source_issued_at': script['source_issued_at'],
                    'source_refs': script['source_refs'], 'evidence_manifest': script['evidence_manifest'],
                    'scenes': scenes, 'seconds': total, 'narration_id': body.narration_id,
                    'presentation': body.presentation, 'music': body.music,
                    'unverified_location_footage': body.unverified_location_footage,
                    'music_bed': bool(narration and body.music_bed and body.presentation == 'broadcast'),
                    'automatic_graphs': body.automatic_graphs, 'visual_preset': 'geographic_newsroom_v1' if body.presentation == 'broadcast' else body.presentation,
                    'bulletin_target_minutes':script.get('bulletin',{}).get('target_minutes',0),
                    'template': body.template, 'story_review_required': bool(plan.get('story_version')),
                    'story_version': plan.get('story_version'),
                    'reported_facts': self.store.advisory(script['advisory_id']).facts,
                    'report_title': self.store.advisory(script['advisory_id']).title,
                    'narration_verified': body.narration_verified, 'audio_mode': 'imported_narration' if narration else 'local_instrumental' if body.music else 'silent',
                    'alignment_id':body.alignment_id, 'alignment_coverage':aligned['coverage'] if aligned else None,
                    'timing_basis': aligned['timing_basis'] if aligned else 'Manual scene timing; matched to imported audio' if narration else 'Manual scene timing',
                    'preview_audit':script.get('preview_audit'),
                    'visual_plan':visual_plan,
                    'broadcast_eligible': False, 'created_at': now()}
        if persist:
            map_issues = self.map_hold_issues(document)
            if map_issues:
                raise ValueError(' '.join(issue['message'] for issue in map_issues))
        if persist:
            self.store.production_save('timelines', document)
        return self.describe_timeline(document)

    def story_geography(self, advisory_id):
        from .visuals import VisualEvidence
        try:
            return VisualEvidence(self.store).geography(advisory_id)['geojson']
        except (KeyError, ValueError):
            return {'type': 'FeatureCollection', 'features': []}

    def pin_observations(self, script):
        """Pin real regional imagery separately from the advisory's claim evidence."""
        advisory = self.store.advisory(script['advisory_id'])
        lon, lat = advisory.facts.get('longitude'), advisory.facts.get('latitude')
        if advisory.provider != 'NHC' or not isinstance(lon, (float, int)) or not isinstance(lat, (float, int)) or not (-100 <= lon <= -65 and 5 <= lat <= 40):
            raise ValueError('The GOES Gulf/Atlantic context requires a reported storm center in that region.')
        assets = sorted([row for row in self.store.visual_assets('goes')
                         if abs((datetime.fromisoformat(row['observed_at']) - advisory.issued_at).total_seconds()) <= 3600],
                        key=lambda row: row['observed_at'])[-12:]
        if len(assets) < 2:
            raise ValueError('Collect at least two NOAA observations within one hour of this advisory. Unrelated historical/current imagery is blocked.')
        pinned = []
        for asset in assets:
            row = self.store.visual_asset(asset['id'])
            if hashlib.sha256(row['body']).hexdigest() != asset['checksum']:
                raise ValueError('Cached NOAA observation checksum changed. Collect the original observations again.')
            with Image.open(io.BytesIO(row['body'])) as image:
                image.verify()
            path = self.root / 'observations' / (asset['checksum'] + '.image')
            temporary = path.with_name(str(uuid4()) + '.part')
            temporary.write_bytes(row['body'])
            temporary.replace(path)
            offset = (datetime.fromisoformat(asset['observed_at']) - datetime.fromisoformat(script['source_issued_at'])).total_seconds()
            pinned.append({k: asset[k] for k in ('id', 'source_url', 'observed_at', 'content_type', 'checksum', 'metadata')})
            pinned[-1].update(filename=path.name, issue_time_offset_seconds=offset,
                             license='NOAA STAR image reuse with NOAA/NESDIS/STAR credit',
                             license_url='https://www.star.nesdis.noaa.gov/star/productdisclaimer.php',
                             context='Regional observations; no claim of event attribution or exact issue-time alignment.')
        return pinned

    def map_asset(self, scene, identity):
        p=scene['parameters']
        rows=p.get('map_observations',[]) + ([p['map_legend']] if p.get('map_legend') else [])
        return self.observation_path(next(a for a in rows if a['id']==identity)).read_bytes()

    def observation_path(self, observation):
        path = self.root / 'observations' / observation['filename']
        if not path.is_file() or checksum(path) != observation['checksum']:
            raise ValueError('Pinned NOAA imagery is missing or changed. Save a new timeline after collecting observations.')
        return path

    def satellite_frames(self, scene, directory):
        for index, observation in enumerate(scene['observations']):
            with Image.open(self.observation_path(observation)) as original:
                image = Image.new('RGB', (1920, 1080), '#08121b')
                # Preserve the entire source image, including its footer and timestamp.
                from PIL import ImageOps
                original = ImageOps.contain(original.convert('RGB'), (1080, 1080))
                image.paste(original, (840 + (1080-original.width)//2, (1080-original.height)//2))
                draw = ImageDraw.Draw(image)
                draw.text((45, 805), 'Observed ' + observation['observed_at'], font=ImageFont.load_default(size=22), fill='#74e1cb')
                draw.multiline_text((45, 850), 'NOAA / NESDIS / STAR · GOES-19 GeoColor\nGulf / Atlantic regional context\nNighttime colors use infrared enhancement.\nObservation and advisory times are independent.', font=ImageFont.load_default(size=20), fill='#b7c9d5', spacing=10)
                image.save(directory / f'observation-{index:03}.png')

    def describe_timeline(self, document, script=None):
        result = dict(document)
        script = script or self.describe_script(self.store.script(document['script_id']))
        result['superseded'] = script['revision'] != document['script_revision']
        result['current_source_label'] = script['label']
        result['review_valid_now'] = script['review_valid'] and not result['superseded']
        return result

    def describe_render(self, document):
        return {**document, 'timeline_state': self.describe_timeline(self.store.production_get('timelines', document['timeline_id']))}

    def validate_timeline(self, timeline):
        map_issues = self.map_hold_issues(timeline)
        if map_issues:
            raise ValueError(' '.join(issue['message'] for issue in map_issues))
        if timeline.get('bulletin_target_minutes',0)>=30 and timeline['seconds']>=600 and not self.visual_coverage(timeline)['footage_clips']:
            raise ValueError('This long bulletin has no footage. Build and review the mixed bulletin edit before exporting.')
        script = self.validate_plan(self.store.visual_plan(timeline['plan_id']))
        # Source status is re-evaluated on each attempt; the job snapshot stores the actual label used.
        media = {}
        for scene in timeline['scenes']:
            for observation in scene.get('observations', []) + scene.get('parameters',{}).get('map_observations',[]):
                self.observation_path(observation)
            if scene.get('parameters',{}).get('map_legend'):
                self.observation_path(scene['parameters']['map_legend'])
        identities = {s['media_id'] for s in timeline['scenes'] if s['media_id']} | {c['media_id'] for s in timeline['scenes'] for c in s.get('cuts',[])}
        for identity in identities | ({timeline['narration_id']} if timeline['narration_id'] else set()):
            item = self.store.production_get('media', identity)
            self.media_path(item)
            media[identity] = item
        for scene in timeline['scenes']:
            if regional.targets(scene):
                pinned = {identity:{**asset, 'catalog':scene.get('selection_catalog',{})} for identity,asset in media.items()}
                for cut in scene.get('cuts',[]):
                    pinned[cut['media_id']] = {**media[cut['media_id']], 'catalog':cut.get('selection_catalog',{})}
                if scene.get('media_id') or scene.get('cuts'):
                    regional.focus(copy.deepcopy(scene), pinned, timeline.get('presentation','captioned'), timeline.get('unverified_location_footage', False))
                elif not scene.get('regional_relevance'):
                    raise ValueError('Re-save this regional timeline to apply location relevance checks.')
        return {**timeline, 'source_label': script['label']}, media

    def start(self, identity, retry_id=None):
        if len(self.tasks) >= 4:
            raise ValueError('The render queue is full. Wait for a job or cancel a queued render.')
        timeline, media = self.validate_timeline(self.store.production_get('timelines', identity))
        if retry_id:
            job = self.store.production_get('renders', retry_id)
            if job['status'] not in ('failed', 'cancelled') or job['id'] in self.tasks:
                raise ValueError('Only failed or cancelled renders can be retried.')
            if job['snapshot']['source_label'] != timeline['source_label']:
                raise ValueError('Source status changed. Start a new render to apply the updated labels.')
            if job.get('renderer_version') != RENDERER_VERSION:
                raise ValueError('The renderer changed. Start a new render to keep every scene consistent.')
            job.update(status='queued', error=None, progress=0, stage='Queued', attempts=job['attempts'] + 1)
            self.store.production_update_render(job)
        else:
            job = {'id': str(uuid4()), 'timeline_id': identity, 'status': 'queued', 'progress': 0, 'stage': 'Queued',
                   'error': None, 'attempts': 1, 'snapshot': timeline, 'media': media, 'cache': {},
                   'broadcast_eligible': False, 'created_at': now(), 'validation': None, 'renderer_version': RENDERER_VERSION}
            self.store.production_save('renders', job)
        if not retry_id:
            self.reuse_scene_cache(job)
            self.store.production_update_render(job)
        task = asyncio.create_task(self._render(job))
        self.tasks[job['id']] = task
        task.add_done_callback(lambda done: self.tasks.pop(job['id'], None))
        return self.describe_render(job)

    def reuse_scene_cache(self, job):
        """Reuse only identical pinned scenes with validated, unchanged encoded files."""
        destination = self.root / 'renders' / job['id']
        candidates = [r for r in self.store.production_list('renders') if r['id'] != job['id']
                      and r.get('renderer_version') == job['renderer_version']
                      and r['snapshot'].get('presentation') == job['snapshot'].get('presentation')
                      and r['snapshot']['source_label'] == job['snapshot']['source_label']][:5]
        reused=0
        for index, scene in enumerate(job['snapshot']['scenes']):
            for prior in candidates:
                previous = prior['snapshot']['scenes']
                digest = prior.get('cache',{}).get(str(index))
                if not digest or index >= len(previous) or previous[index] != scene:continue
                fade = index and job['snapshot']['scenes'][index-1]['transition']=='fade'
                old_fade = index and previous[index-1]['transition']=='fade'
                if fade != old_fade:continue
                source = self.root / 'renders' / prior['id'] / f'scene-{index:03}.mp4'
                if not source.is_file() or checksum(source) != digest:continue
                destination.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,destination / source.name)
                job['cache'][str(index)]=digest;reused+=1
                break
        job['reused_scenes']=reused

    async def cancel(self, identity):
        task = self.tasks.get(identity)
        if not task:
            raise ValueError('This render is no longer queued or running.')
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # A task cancelled before its first instruction still needs a durable status.
        job = self.store.production_get('renders', identity)
        if job['status'] in ('queued', 'running'):
            job.update(status='cancelled', stage='Cancelled', error='Cancelled by operator')
            self.store.production_update_render(job)
        return self.describe_render(self.store.production_get('renders', identity))

    def output_path(self, identity, kind):
        job = self.store.production_get('renders', identity)
        if job['status'] != 'succeeded':
            raise ValueError('A validated completed render is required for export.')
        names = {'video': 'program.mp4', 'subtitles': 'captions.srt', 'manifest': 'manifest.json', 'report': 'report.json',
                 'report_md': 'report.md', 'thumbnail': 'thumbnail.jpg', 'metadata': 'metadata.json'}
        path = self.root / 'renders' / job['id'] / names[kind]
        expected = job['validation']['checksums'].get(kind)
        if expected is None:
            raise ValueError('This render predates production reports; render again to create one.')
        if not path.is_file() or checksum(path) != expected:
            raise ValueError('The render export is missing or changed; it cannot be served as a validated output.')
        return path

    async def command(self, job, args, timeout=600, log_name='ffmpeg.log'):
        work = self.root / 'renders' / job['id']
        executable = shutil.which('ffmpeg')
        if not executable:
            raise ValueError('Install FFmpeg before starting a render.')
        with (work / log_name).open('ab' if log_name == 'ffmpeg.log' else 'wb') as log:
            process = await asyncio.create_subprocess_exec(executable, '-hide_banner', '-loglevel', 'warning', '-nostdin',
                                                         '-y', '-filter_complex_threads', '2', *args, cwd=work, stdout=asyncio.subprocess.DEVNULL, stderr=log)
            try:
                code = await asyncio.wait_for(process.wait(), timeout)
                if code:
                    raise ValueError('FFmpeg could not render or decode the media. Check this render’s ffmpeg.log.')
            except BaseException:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                raise

    def overlays(self, timeline, scene, asset, directory):
        satellite = bool(scene.get('observations'))
        pages = text_pages(scene['script_segment'], width=43, lines=15) if satellite else text_pages(scene['script_segment'])
        title = timeline['title'][:105]
        for index, page in enumerate(pages):
            image = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            if satellite:
                draw.rectangle((0, 0, 840, 790), fill=(8, 18, 27, 255))
                draw.text((45, 35), timeline['source_label'].upper().replace('_', ' ') + ' · PRODUCTION PREVIEW', font=ImageFont.load_default(size=24), fill='#e7b56e')
                draw.multiline_text((45, 95), '\n'.join(textwrap.wrap(title, 43)[:3]), font=ImageFont.load_default(size=30), fill='#e4edf5', spacing=8)
                draw.multiline_text((45, 230), page, font=ImageFont.load_default(size=28), fill='#e4edf5', spacing=7)
                draw.text((45, 965), ('IMPORTED NARRATION' if timeline['narration_id'] else 'NO VOICEOVER') + ' · NOT FOR BROADCAST', font=ImageFont.load_default(size=20), fill='#e7b56e')
                draw.text((45, 1005), 'Advisory issued ' + timeline['source_issued_at'], font=ImageFont.load_default(size=19), fill='#98afc0')
                draw.text((45, 1040), ' | '.join(timeline['source_refs'])[:70], font=ImageFont.load_default(size=17), fill='#98afc0')
                image.save(directory / f'overlay-{index:03}.png')
                continue
            draw.rectangle((0, 0, 1920, 145), fill=(8, 18, 27, 240))
            draw.rectangle((0, 680, 1920, 1080), fill=(8, 18, 27, 242))
            draw.rectangle((65, 32, 72, 115), fill='#74e1cb')
            draw.text((100, 30), f"{timeline['source_label'].upper().replace('_', ' ')} · PRODUCTION PREVIEW · NOT FOR BROADCAST", font=ImageFont.load_default(size=26), fill='#e7b56e')
            draw.text((100, 75), title, font=ImageFont.load_default(size=36), fill='#e4edf5')
            draw.multiline_text((100, 705), page, font=ImageFont.load_default(size=32), fill='#e4edf5', spacing=7)
            context = (asset['context'].upper() + ' MEDIA · ' + asset['attribution']) if asset else 'SOURCE-LINKED GRAPHIC · No observation imagery rendered'
            draw.text((100, 995), context[:110], font=ImageFont.load_default(size=21), fill='#74e1cb')
            draw.text((100, 1032), ('Issued ' + timeline['source_issued_at'] + ' · ' + ' | '.join(timeline['source_refs']))[:145], font=ImageFont.load_default(size=18), fill='#98afc0')
            image.save(directory / f'overlay-{index:03}.png')
        return pages

    def background(self, scene, path):
        """Draw only plan-pinned geometry/measurements; missing layers use a source card."""
        image = Image.new('RGB', (1920, 1080), '#0b1c29')
        draw = ImageDraw.Draw(image)
        features = scene.get('parameters', {}).get('geojson', {}).get('features', [])
        map_box = (80, 175, 1840, 640)
        if scene['type'] in ('cinematic_weather_map', 'storm_track', 'forecast_cone') and features:
            def all_points(value):
                if len(value) >= 2 and isinstance(value[0], (int, float)):
                    return [value[:2]]
                return [point for child in value for point in all_points(child)]
            coordinates = [coord for feature in features for coord in all_points(feature['geometry']['coordinates'])]
            longitudes, latitudes = zip(*coordinates)
            center_lon = (min(longitudes) + max(longitudes)) / 2
            center_lat = (min(latitudes) + max(latitudes)) / 2
            longitude_span = max(45, max(longitudes) - min(longitudes) + 12)
            latitude_span = max(25, max(latitudes) - min(latitudes) + 8)
            west, east = max(-180, center_lon - longitude_span / 2), min(180, center_lon + longitude_span / 2)
            south, north = max(-90, center_lat - latitude_span / 2), min(90, center_lat + latitude_span / 2)
            # The extent contains all plan-pinned geometry; linear coordinates are labeled schematic.
            def point(coord):
                return (80 + (coord[0] - west) / (east - west) * 1760, 640 - (coord[1] - south) / (north - south) * 465)
            canvas = Image.new('RGB', (1760, 465), '#102733')
            land = ImageDraw.Draw(canvas)
            def local(coord):
                x, y = point(coord)
                return x - 80, y - 175
            countries = json.loads((Path(__file__).parent / 'data/countries.geojson').read_text())
            for feature in countries['features']:
                geometry = feature['geometry']
                polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
                for polygon in polygons:
                    land.polygon([local(c) for c in polygon[0]], fill='#1c3e48', outline='#46636a')
                    for hole in polygon[1:]:
                        land.polygon([local(c) for c in hole], fill='#102733')
            for longitude in range(math.ceil(west / 10) * 10, math.floor(east) + 1, 10):
                x, _ = local((longitude, 5))
                land.line((x, 0, x, 465), fill='#29414e')
            for latitude in range(math.ceil(south / 10) * 10, math.floor(north) + 1, 10):
                _, y = local((-130, latitude))
                land.line((0, y, 1760, y), fill='#29414e')
            for feature in features:
                geometry = feature['geometry']
                coords = geometry['coordinates']
                kind = geometry['type']
                if kind == 'Point':
                    x, y = local(coords)
                    land.ellipse((x - 9, y - 9, x + 9, y + 9), fill='#74e1cb', outline='#ffffff', width=2)
                elif kind == 'LineString':
                    land.line([local(c) for c in coords], fill='#74e1cb', width=5)
                elif kind in ('Polygon', 'MultiPolygon'):
                    for polygon in coords if kind == 'MultiPolygon' else [coords]:
                        land.line([local(c) for c in polygon[0]], fill='#e7b56e', width=4)
            image.paste(canvas, map_box[:2])
            draw.text((100, 651), 'Plan-pinned reported geometry · schematic geographic view · Natural Earth / official source attribution in manifest', font=ImageFont.load_default(size=18), fill='#98b5c6')
        elif scene['type'] == 'what_changed':
            changes = scene.get('parameters', {}).get('changes', [])
            numeric = [c for c in changes if isinstance(c.get('previous'), (int, float)) and isinstance(c.get('current'), (int, float))][:3]
            if numeric:
                for index, change in enumerate(numeric):
                    x = 100 + index * 590
                    draw.rounded_rectangle((x, 220, x + 550, 610), radius=14, fill='#15313b', outline='#375c62', width=2)
                    draw.text((x + 30, 250), change['field'].replace('_', ' ').upper()[:28], font=ImageFont.load_default(size=23), fill='#91bcc7')
                    draw.text((x + 30, 320), f"{change['previous']}  →  {change['current']}", font=ImageFont.load_default(size=46), fill='#dbedea')
                    scale = max(abs(change['previous']), abs(change['current']), 1)
                    for row, value in enumerate((change['previous'], change['current'])):
                        y = 435 + row * 55
                        draw.rectangle((x + 30, y, x + 30 + abs(value) / scale * 470, y + 18), fill='#6c8f9c' if row == 0 else '#74e1cb')
                    draw.text((x + 30, 555), f"Change: {change.get('delta', 'n/a')}", font=ImageFont.load_default(size=25), fill='#e7b56e')
            else:
                draw.text((100, 315), 'Read the source-linked comparison below.', font=ImageFont.load_default(size=46), fill='#c9e6e3')
        else:
            draw.text((100, 275), scene['type'].replace('_', ' ').upper(), font=ImageFont.load_default(size=26), fill='#74e1cb')
            draw.multiline_text((100, 335), 'WEATHER\nINTELLIGENCE STUDIO', font=ImageFont.load_default(size=70), fill='#d8e9ee', spacing=15)
            draw.text((100, 565), 'Source-linked narration · original timestamps retained', font=ImageFont.load_default(size=26), fill='#89aaba')
        image.save(path)

    def footage_overlay(self, asset, path, scene=None):
        image = Image.new('RGBA', (1920,1080), (0,0,0,0))
        draw = ImageDraw.Draw(image)
        catalog = asset.get('catalog', {})
        context = asset['context'].upper()
        event = catalog.get('event_id') or ''
        stamp = catalog.get('captured_at') or catalog.get('capture_date') or ''
        caption = ' · '.join(str(v) for v in (context, event, stamp) if v)
        if scene is not None and regional.location_status(scene, asset) == 'unverified':
            caption += ' · LOCATION NOT VERIFIED'
        draw.rounded_rectangle((45,40,1100,95),radius=12,fill=(6,23,36,220))
        broadcast.label(draw,(65,55),caption[:95],24,'#e7f1f8')
        if scene is not None:
            from .geography import mentions, locator
            places = mentions(scene.get('script_segment', ''))
            if places:
                inset = locator(places)
                image.alpha_composite(inset, (1920 - inset.width - 45, 1080 - inset.height - 60))
        image.save(path)

    def captions(self, timeline):
        """Caption file for the whole program, written before scenes render in parallel."""
        rows, cursor = [], 0.0
        for scene in timeline['scenes']:
            if timeline.get('presentation') == 'broadcast':
                pages = caption_pages(scene['script_segment'])
            elif timeline.get('presentation') == 'cinematic' or not scene.get('observations'):
                pages = text_pages(scene['script_segment'])
            else:
                pages = text_pages(scene['script_segment'], width=43, lines=15)
            spoken = scene.get('word_frames')
            counts = [len(page.split()) for page in pages]
            if spoken and len(spoken) == sum(counts):
                # Recognized speech: each page appears when its first word is spoken.
                starts, index = [], 0
                for count in counts:
                    starts.append(cursor + spoken[index] / 30);index += count
                ends = starts[1:] + [cursor + scene['seconds']]
            else:
                # No word timing: each page holds the screen in proportion to its words.
                weights = [max(1, c) for c in counts];total = sum(weights);elapsed = 0;starts, ends = [], []
                for weight in weights:
                    starts.append(cursor + scene['seconds'] * elapsed / total);elapsed += weight
                    ends.append(cursor + scene['seconds'] * elapsed / total)
            for page, start, end in zip(pages, starts, ends):
                if end - start >= 1 / 30:
                    rows.append(f'{len(rows)+1}\n{srt_time(start)} --> {srt_time(end)}\n{page}\n')
            cursor += scene['seconds']
        return '\n'.join(rows)

    def scene_assets(self, scene):
        p = scene['parameters']
        rows = p.get('map_observations', []) + ([p['map_legend']] if p.get('map_legend') else [])
        return {row['id']: self.observation_path(row).read_bytes() for row in rows}

    def pool(self):
        if self._pool is None:
            from concurrent.futures import ProcessPoolExecutor
            self._pool = ProcessPoolExecutor(max_workers=render_workers())
        return self._pool

    async def assemble(self, job, timeline, work):
        """List every scene for one continuous encode. Each fade becomes a short dissolve piece between
        trimmed neighbours, so the work per fade is constant however long the program is."""
        scenes = timeline['scenes'];broadcast_fades = timeline.get('presentation') == 'broadcast'
        handles = [.3 if broadcast_fades and s['transition'] == 'fade' and i < len(scenes) - 1 else 0 for i, s in enumerate(scenes)]
        files = []
        for index, scene in enumerate(scenes):
            segment = f'scene-{index:03}.mp4'
            lead = handles[index-1] if index else 0
            tail = handles[index]
            if lead or tail:
                body = f'body-{index:03}.mp4'
                await self.command(job, ['-ss', f'{lead:.6f}', '-i', segment, '-frames:v', str(round((scene['seconds'] - tail) * 30)), '-an',
                                         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '14', '-pix_fmt', 'yuv420p', body])
                files.append(body)
            else:
                files.append(segment)
            if tail:
                piece = f'fade-{index:03}.mp4';frames = round(tail * 30)
                start = scene['seconds'] + lead - tail
                await self.command(job, ['-ss', f'{start:.6f}', '-i', segment, '-i', f'scene-{index+1:03}.mp4', '-filter_complex',
                                         f'[0:v]trim=end_frame={frames},setpts=PTS-STARTPTS[a];[1:v]trim=end_frame={frames},setpts=PTS-STARTPTS[b];[a][b]xfade=transition=fade:duration={tail}:offset=0[out]',
                                         '-map', '[out]', '-frames:v', str(frames), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '14', '-pix_fmt', 'yuv420p', piece])
                files.append(piece)
        listing = work / 'concat.txt'
        listing.write_text(''.join(f"file '{name}'\n" for name in files))
        return listing

    async def render_scene(self, job, timeline, media, work, index):
        """Render one scene segment. Broadcast segments after a fade carry a 0.3 second lead-in handle."""
        scenes = timeline['scenes'];scene = scenes[index]
        handle = .3 if timeline.get('presentation') == 'broadcast' and index and scenes[index-1]['transition'] == 'fade' else 0
        segment = work / f'scene-{index:03}.mp4'
        clip = work / f'frames-{index:03}'
        clip.mkdir(exist_ok=True)
        asset = media.get(scene['media_id'])
        is_cinematic = timeline.get('presentation') == 'cinematic'
        is_broadcast = timeline.get('presentation') == 'broadcast'
        pages = None if is_cinematic or is_broadcast else await asyncio.to_thread(self.overlays, timeline, scene, asset, clip)
        if is_broadcast and scene.get('cuts'):
            files = []
            for cut_index, cut in enumerate(scene['cuts']):
                cut_asset = media[cut['media_id']]
                overlay = clip / f'cut-label-{cut_index}.png'
                await asyncio.to_thread(self.footage_overlay, cut_asset, overlay, scene)
                path = self.media_path(cut_asset)
                source = ['-loop','1','-framerate','30'] if cut_asset['kind']=='image' else ['-ss',str(cut['trim_start'])]
                piece = clip / f'cut-{cut_index}.mp4'
                base = still_motion(round(cut['seconds']*30), index+cut_index) if cut_asset['kind']=='image' else footage_library.fill_filter(cut_asset)
                await self.command(job,[*source,'-protocol_whitelist','file,pipe','-i',str(path),'-loop','1','-i',str(overlay),'-filter_complex',
                    base+';[base][1:v]overlay=0:0:format=auto[out]',
                    '-map','[out]','-an','-frames:v',str(round(cut['seconds']*30)),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-threads','2',str(piece)])
                files.append(f"file '{piece.name}'\n")
            listing = clip / 'cuts.txt'
            listing.write_text(''.join(files))
            await self.command(job,['-f','concat','-safe','0','-i',str(listing),'-c:v','copy','-an',str(segment)])
        elif is_broadcast and asset:
            seconds=scene['seconds'] + handle
            overlay=clip/'footage-label.png'
            await asyncio.to_thread(self.footage_overlay,asset,overlay,scene)
            path=self.media_path(asset)
            source=['-loop','1','-framerate','30'] if asset['kind']=='image' else ['-ss',str(scene['trim_start'])]
            source+=['-protocol_whitelist','file,pipe','-i',str(path),'-loop','1','-i',str(overlay)]
            base=still_motion(round(seconds*30), index) if asset['kind']=='image' else footage_library.fill_filter(asset)
            await self.command(job,[*source,'-filter_complex',
                base+';[base][1:v]overlay=0:0:format=auto[out]',
                '-map','[out]','-an','-frames:v',str(round(seconds*30)),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-threads','2',str(segment)])
        elif is_broadcast:
            before = scenes[index-1] if index else None
            previous = (before['direction'], before['parameters'], self.scene_assets(before), before['seconds']) if before and scene['parameters'].get('transition_in') else None
            arguments = (scene['direction'], scene['parameters'], str(segment), self.scene_assets(scene), scene['seconds'] + handle, previous)
            try:
                await asyncio.get_running_loop().run_in_executor(self.pool(), broadcast.render_clip_blocking, *arguments)
            except BrokenProcessPool:
                # Worker processes could not start (e.g. an unimportable main module); render here instead.
                self._pool = None
                await asyncio.to_thread(broadcast.render_clip_blocking, *arguments)
        else:
            if is_cinematic:
                shots, count = await asyncio.to_thread(cinematic.frames, timeline, scene, clip, self.observation_path)
                source = ['-framerate', str(len(scene['observations']) / scene['seconds']), '-i', str(clip / 'observation-%03d.png')]
                source += ['-framerate', str(count / scene['seconds']), '-i', str(clip / 'overlay-%04d.png')]
            elif asset:
                path = self.media_path(asset)
                source = ['-loop', '1', '-framerate', '30'] if asset['kind'] == 'image' else ['-ss', str(scene['trim_start'])]
                source += ['-protocol_whitelist', 'file,pipe', '-i', str(path)]
            elif scene.get('observations'):
                await asyncio.to_thread(self.satellite_frames, scene, clip)
                source = ['-framerate', str(len(scene['observations']) / scene['seconds']), '-i', str(clip / 'observation-%03d.png')]
            else:
                background = clip / 'background.png'
                await asyncio.to_thread(self.background, scene, background)
                source = ['-loop', '1', '-framerate', '30', '-i', str(background)]
            if not is_cinematic:
                source += ['-framerate', str(len(pages) / scene['seconds']), '-i', str(clip / 'overlay-%03d.png')]
            filters = '[0:v:0]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0b1118,setsar=1,fps=30[base];[base][1:v:0]overlay=0:0:format=auto'
            if is_cinematic:
                # A modest camera push changes presentation only; weather pixels remain the actual source.
                filters = f"[0:v:0]scale=2048:1152,fps=30,crop=1920:1080:x='64+24*sin(t/10)':y='36+12*sin(t/13)',setsar=1,fps=30[base];[base][1:v:0]overlay=0:0:format=auto"
            if scene['transition'] == 'fade':
                filters += f",fade=t=in:st=0:d=0.25,fade=t=out:st={scene['seconds']-0.25}:d=0.25"
            filters += '[out]'
            await self.command(job, [*source, '-filter_complex', filters, '-map', '[out]', '-an',
                                     '-frames:v', str(scene['frames']), '-c:v', 'libx264', '-preset', 'veryfast',
                                     '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '2', str(segment)],
                               timeout=max(120, scene['seconds'] * 10))
        info = await asyncio.to_thread(probe, segment)
        if abs(duration(info) - (scene['seconds'] + handle)) > 0.1:
            raise ValueError('A rendered scene failed duration validation.')

    async def premix(self, job, timeline, media, work):
        """Voice on top; the instrumental ducks whenever the voice speaks; soft sounds mark transitions."""
        seconds = timeline['seconds']
        inputs = ['-protocol_whitelist', 'file,pipe', '-i', str(self.media_path(media[timeline['narration_id']])),
                  '-f', 'lavfi', '-i', cinematic.score_filter(seconds)]
        cues, cursor = [], 0.0
        for scene in timeline['scenes']:
            if scene['parameters'].get('transition_in'):
                cues.append(cursor)
            cursor += scene['seconds']
        graph = ('[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][key];'
                 '[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.35,afade=t=in:d=2,afade=t=out:st=' + str(max(0, seconds - 3)) + ':d=3[bed];'
                 '[bed][key]sidechaincompress=threshold=0.02:ratio=12:attack=15:release=450[ducked];')
        if cues:
            await asyncio.to_thread(audio_polish.write_cues, work / 'transitions.wav', cues, seconds)
            inputs += ['-i', str(work / 'transitions.wav')]
            graph += '[2:a]aformat=sample_rates=48000:channel_layouts=stereo[cues];[voice][ducked][cues]amix=inputs=3:normalize=0:duration=first'
        else:
            graph += '[voice][ducked]amix=inputs=2:normalize=0:duration=first'
        graph += ',loudnorm=I=-16:TP=-1.5:LRA=11[mix]'
        await self.command(job, [*inputs, '-filter_complex', graph, '-map', '[mix]', '-t', str(seconds), '-c:a', 'pcm_s16le', str(work / 'mix.wav')],
                           timeout=max(600, seconds * 2), log_name='audio.log')

    async def _render(self, job):
        try:
            async with self.serial:
                # Re-check after waiting in the queue, before consuming resources.
                timeline, media = self.validate_timeline(job['snapshot'])
                if timeline['source_label'] != job['snapshot']['source_label']:
                    raise ValueError('Source status changed while queued. Start a new render with current labels.')
                job.update(status='running', stage='Preparing scenes')
                self.store.production_update_render(job)
                work = self.root / 'renders' / job['id']
                work.mkdir(parents=True, exist_ok=True)
                clock = time.monotonic();timings = {}
                def lap(name):
                    nonlocal clock
                    timings[name] = round(time.monotonic() - clock, 2);clock = time.monotonic()
                (work / 'captions.srt').write_text(self.captions(timeline), encoding='utf-8')
                scenes = timeline['scenes'];done = [0];cached_scenes = [0]
                workers = asyncio.Semaphore(render_workers())
                async def one(index):
                    async with workers:
                        segment = work / f'scene-{index:03}.mp4'
                        cached = job['cache'].get(str(index))
                        if not (cached and segment.exists() and await asyncio.to_thread(checksum, segment) == cached):
                            await self.render_scene(job, timeline, media, work, index)
                            job['cache'][str(index)] = await asyncio.to_thread(checksum, segment)
                        else:
                            cached_scenes[0] += 1
                        done[0] += 1
                        job.update(progress=round(done[0] / len(scenes) * 75), stage=f"Rendered {done[0]} of {len(scenes)} scenes")
                        self.store.production_update_render(job)
                pending = [asyncio.create_task(one(i)) for i in range(len(scenes))]
                try:
                    await asyncio.gather(*pending)
                except BaseException:
                    for task in pending:task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    raise
                job['cached_scenes'] = cached_scenes[0];lap('scenes')
                job.update(stage='Joining scenes', progress=78)
                self.store.production_update_render(job)
                listing = await self.assemble(job, timeline, work);lap('joins')
                job.update(stage='Assembling video and audio', progress=80)
                self.store.production_update_render(job)
                audio = ['-protocol_whitelist', 'file,pipe', '-i', str(self.media_path(media[timeline['narration_id']]))] if timeline['narration_id'] else ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
                if timeline.get('music'):
                    audio = ['-f', 'lavfi', '-i', cinematic.score_filter(timeline['seconds'])]
                voice_filter = 'loudnorm=I=-16:TP=-1.5:LRA=11,apad'
                if timeline['narration_id'] and timeline.get('music_bed'):
                    job.update(stage='Mixing voiceover, music bed and transition sounds')
                    self.store.production_update_render(job)
                    await self.premix(job, timeline, media, work)
                    audio = ['-i', str(work / 'mix.wav')];voice_filter = 'apad'
                lap('audio_mix')
                audio_filter = ('loudnorm=I=-22:TP=-2:LRA=9,afade=t=in:d=1,afade=t=out:st=' + str(max(0, timeline['seconds']-2)) + ':d=2,apad') if timeline.get('music') else voice_filter
                # One continuous encode: no decoder reconfiguration at cuts, and no filter graph that grows with scene count.
                job.update(stage='Encoding the full program')
                self.store.production_update_render(job)
                await self.command(job, ['-f', 'concat', '-safe', '0', '-i', listing.name, *audio,
                                         '-map', '0:v:0', '-map', '1:a:0', *final_encoder(timeline['seconds']), '-pix_fmt', 'yuv420p',
                                         '-r', '30', '-fps_mode', 'cfr', '-af', audio_filter,
                                         '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-t', str(timeline['seconds']),
                                         '-movflags', '+faststart', 'program.mp4'], timeout=max(600, timeline['seconds'] * 3))
                lap('final_encode')
                job.update(stage='Validating output', progress=90)
                self.store.production_update_render(job)
                output = work / 'program.mp4'
                info = await asyncio.to_thread(probe, output)
                video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                audio_stream = next(s for s in info['streams'] if s['codec_type'] == 'audio')
                if (video['codec_name'], video['width'], video['height'], video['r_frame_rate'], audio_stream['codec_name']) != ('h264', 1920, 1080, '30/1', 'aac') or abs(duration(info) - timeline['seconds']) > 0.15:
                    raise ValueError('The output did not pass codec, resolution, frame-rate and duration checks.')
                if abs(float(video.get('duration',0)) - timeline['seconds']) > .15 or abs(int(video.get('nb_frames',0))-round(timeline['seconds']*30)) > 1:
                    raise ValueError('The video stream ended early or has an incorrect frame count; audio duration cannot validate the picture.')
                # Decode every output frame/sample; probing headers alone is insufficient.
                await self.command(job, ['-loglevel', 'info', '-xerror', '-i', 'program.mp4', '-map', '0:v:0', '-map', '0:a:0',
                                         '-vf', f'blackdetect=d=1:pix_th=0.005:pic_th=0.995,freezedetect=n=0.001:d={production_report.FREEZE_SECONDS}',
                                         '-af', 'silencedetect=noise=-50dB:d=2,ebur128=peak=true', '-f', 'null', '-'], log_name='qc.log')
                qc = (work / 'qc.log').read_text(errors='replace')
                if re.search(r'black_start:', qc):
                    raise ValueError('The output contains an extended nearly black interval. Inspect the scene assets and qc.log.')
                warnings = ['Imported narration contains extended silence; listen to the preview.'] if timeline['narration_id'] and 'silence_start:' in qc else []
                if any(scene.get('observations') for scene in timeline['scenes']):
                    warnings.append('Satellite observations are regional context with independent timestamps; they do not establish event attribution or exact advisory-time alignment.')
                manifest = {'timeline': timeline, 'media': media, 'render_id': job['id'], 'output': {'width': 1920, 'height': 1080, 'fps': 30, 'video_codec': 'h264', 'audio_codec': 'aac', 'seconds': duration(info)},
                            'quality_warnings': warnings, 'broadcast_eligible': False,
                            'scene_directions': [scene.get('direction') for scene in timeline['scenes']],
                            'presentation_beats': [cinematic.beats(timeline, scene) for scene in timeline['scenes']] if timeline.get('presentation') == 'cinematic' else None,
                            'music': {'creator': 'Weather Intelligence Studio', 'source': 'Original locally synthesized instrumental pulse; no voice or third-party samples'} if timeline.get('music') else None,
                            'notice': 'Production preview only. Source-linked captions are burned in; footage is explicitly contextual. No local voiceover generated.'}
                (work / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                lap('quality_control')
                report = production_report.build(job, timeline, media, qc, (work / 'captions.srt').read_text(encoding='utf-8'), self.store.advisory, timings)
                await asyncio.to_thread(packaging.package, work, timeline, report)
                report['timings_seconds']['packaging'] = round(time.monotonic() - clock, 2)
                report['packaging'] = json.loads((work / 'metadata.json').read_text())
                (work / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                (work / 'report.md').write_text(production_report.markdown(report), encoding='utf-8')
                job['report'] = {'errors': report['errors'], 'warnings': report['warnings'], 'timings_seconds': report['timings_seconds'],
                                 'cache': report['cache'], 'checks': report['checks'], 'findings': report['findings'][:30]}
                job.update(status='succeeded', stage='Validated preview ready', progress=100,
                           validation={**manifest['output'], 'decoded': True, 'black_frame_check': True, 'warnings': warnings, 'audio_mode': timeline['audio_mode'],
                                       'checksums': {kind: await asyncio.to_thread(checksum, work / filename) for kind, filename in
                                                     [('video', 'program.mp4'), ('subtitles', 'captions.srt'), ('manifest', 'manifest.json'),
                                                      ('report', 'report.json'), ('report_md', 'report.md'), ('thumbnail', 'thumbnail.jpg'), ('metadata', 'metadata.json')]}})
                self.store.production_update_render(job)
        except asyncio.CancelledError:
            job.update(status='cancelled', stage='Cancelled', error='Render stopped; completed scenes can be reused on retry.')
            self.store.production_update_render(job)
            raise
        except Exception as error:
            job.update(status='failed', stage='Failed', error='FFmpeg exceeded the render timeout.' if isinstance(error, asyncio.TimeoutError) else str(error) if isinstance(error, (ValueError, RevisionConflict)) else 'Unexpected render failure; inspect backend.log and ffmpeg.log.')
            self.store.production_update_render(job)
