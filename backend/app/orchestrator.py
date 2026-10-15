"""Script + voiceover in, finished video out: one saved, resumable production job.

It drives the existing steps rather than duplicating them: speech alignment, shot planning and the
mixed edit (prepare), optional footage search for reported gaps, timeline creation, the parallel
renderer, quality control and packaging. Every stage is persisted; a restart marks the job
interrupted and Resume re-runs it, reusing the completed alignment and rendered scenes.
"""
import logging
import asyncio
import copy
import httpx
from .storage import RevisionConflict
from uuid import uuid4
from .contracts import FootageExpansionRequest, TimelineRequest
from .storage import now
from .alignment import AlignmentBusy

STAGES = [('validate', 'Check script and voiceover'), ('align', 'Match the voiceover to the script'),
          ('plan', 'Plan shots, visuals and footage'), ('data', 'Collect maps and observations'), ('footage', 'Find footage for gaps'),
          ('timeline', 'Build the timeline'), ('storyboard', 'Storyboard and quick preview'), ('render', 'Render scenes and assemble'),
          ('report', 'Quality control and production report')]
POLL = 1.0


class Orchestrator:
    def __init__(self, store, production, alignment, footage, prepare, visuals=None):
        self.store, self.production, self.alignment, self.footage, self.prepare = store, production, alignment, footage, prepare
        self.visuals = visuals
        self.tasks = {}

    def describe(self, job):
        return copy.deepcopy(job)

    def list(self):
        return [self.describe(j) for j in self.store.production_list('jobs')][:20]

    def get(self, identity):
        return self.describe(self.store.production_get('jobs', identity))

    def start(self, body):
        if getattr(self.production, 'maintenance', False):
            raise ValueError('Storage cleanup is finishing. Try again in a moment.')
        request = body.model_dump()
        for existing in self.store.production_list('jobs'):
            if existing['status'] in ('queued', 'running') and existing['request'] == request:
                return self.describe(existing)
        if len([t for t in self.tasks.values() if not t.done()]) >= 2:
            raise ValueError('Two productions are already running. Wait for one to finish.')
        plan = self.store.visual_plan(body.plan_id)
        job = {'id': str(uuid4()), 'status': 'queued', 'request': body.model_dump(), 'plan_id': plan['id'],
               'stages': [{'key': k, 'label': label, 'status': 'pending', 'detail': ''} for k, label in STAGES],
               'stage': 'Queued', 'progress': 0, 'error': None, 'issues': [], 'timeline_id': None, 'render_id': None,
               'footage_job_id': None, 'alignment_id': None, 'report': None, 'attempts': 1, 'created_at': now(), 'updated_at': now()}
        self.store.production_save('jobs', job)
        self.launch(job)
        return self.describe(job)

    def resume(self, identity):
        if getattr(self.production, 'maintenance', False):
            raise ValueError('Storage cleanup is finishing. Try again in a moment.')
        job = self.store.production_get('jobs', identity)
        if job['status'] not in ('failed', 'interrupted', 'cancelled') or (identity in self.tasks and not self.tasks[identity].done()):
            raise ValueError('Only failed, cancelled or interrupted productions can be resumed.')
        job.update(status='queued', error=None, attempts=job.get('attempts', 1) + 1)
        for stage in job['stages']:
            if stage['status'] in ('running', 'failed'):
                stage['status'] = 'pending'
        self.save(job)
        self.launch(job)
        return self.describe(job)

    async def cancel(self, identity):
        task = self.tasks.get(identity)
        if not task or task.done():
            raise ValueError('This production is not running.')
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return self.get(identity)

    def launch(self, job):
        task = asyncio.create_task(self.run(job))
        self.tasks[job['id']] = task
        task.add_done_callback(lambda done: self.tasks.pop(job['id'], None) if self.tasks.get(job['id']) is done else None)

    async def close(self):
        tasks = [t for t in self.tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def save(self, job):
        job['updated_at'] = now()
        self.store.production_update_job(job)

    def stage(self, job, key, status, detail='', fraction=0):
        row = next(s for s in job['stages'] if s['key'] == key)
        if row['status'] == status and row['detail'] == detail:
            return
        row.update(status=status, detail=detail)
        if status == 'running':
            job['stage'] = row['label']
        done = sum(s['status'] in ('done', 'skipped') for s in job['stages'])
        job['progress'] = min(99, round((done + min(.99, max(0, fraction))) / len(job['stages']) * 100))
        self.save(job)

    def base_body(self, job, plan):
        request = job['request']
        return {'plan_id': plan['id'], 'title': request['title'], 'narration_id': request['narration_id'],
                'narration_verified': request['narration_verified'], 'presentation': 'broadcast', 'automatic_graphs': True,
                'music': False, 'music_bed': request['music_bed'], 'template': None,
                'scenes': request.get('scenes') or [{'id': s['id'], 'seconds': max(1, min(120, s.get('target_seconds') or 4)), 'transition': 'cut'} for s in plan['scenes']]}

    async def prepared(self, job, body):
        """Run prepare; when it starts speech alignment, wait for it and prepare again."""
        if any(i['code'] == 'timing_fallback' for i in job['issues']):
            return await asyncio.to_thread(self.prepare, TimelineRequest(**body), False)
        while True:
            try:
                result = await asyncio.to_thread(self.prepare, TimelineRequest(**body))
            except AlignmentBusy as busy:
                if job['request'].get('scenes') and job['request'].get('narration_verified'):
                    job['issues'].append({'code': 'timing_fallback', 'message': 'Another recording is being aligned. Using your confirmed fitted scene timing; word-level alignment was not applied.'})
                    self.stage(job, 'align', 'done', 'Confirmed fitted timing used; speech engine busy')
                    return await asyncio.to_thread(self.prepare, TimelineRequest(**body), False)
                self.stage(job, 'align', 'running', 'Waiting for the other recording to finish alignment')
                while self.alignment.get(busy.job_id)['status'] in ('queued', 'running'):
                    await asyncio.sleep(POLL)
                continue
            if result['status'] != 'aligning':
                return result
            alignment = result['alignment'];job['alignment_id'] = alignment['id']
            self.stage(job, 'align', 'running', 'Listening locally')
            while alignment['status'] in ('queued', 'running'):
                await asyncio.sleep(POLL)
                alignment = self.alignment.get(alignment['id'])
                self.stage(job, 'align', 'running', f"{alignment['stage']} · {round(alignment.get('progress', 0) * 100)}%", alignment.get('progress', 0))
            if alignment['status'] != 'completed':
                reason = alignment.get('error') or 'Speech alignment failed.'
                if not job['request'].get('scenes'):
                    raise ValueError(reason)
                # Estimated timing fallback: the editor's fitted scene durations, checked against the voiceover length.
                job['issues'].append({'code': 'timing_fallback', 'message': reason + ' Using your fitted scene timing instead of spoken word timing.'})
                self.stage(job, 'align', 'done', 'Fitted timing used; speech alignment unavailable')
                return await asyncio.to_thread(self.prepare, TimelineRequest(**body), False)

    async def collect_data(self, job, plan_id):
        if self.visuals is None:
            self.stage(job, 'data', 'skipped', 'No data collector configured');return
        from . import geography, satellite, radar_archive, spc
        from .observations import story_bounds
        from .visual_director import classify, story_text
        from .intelligence import IntelligenceDesk
        self.stage(job, 'data', 'running', 'Checking cached observations before downloading')
        plan = self.store.visual_plan(plan_id);found = [];problems = []
        stories = list(dict.fromkeys(s['parameters'].get('source_advisory_id') or plan['advisory_id'] for s in plan['scenes']))
        stories = [i for i in stories if self.store.advisory(i).provider != 'TRAINING']
        if not stories:
            self.stage(job, 'data', 'skipped', 'Training stories use no live observations');return
        intelligence = IntelligenceDesk(self.store.advisories(), self.store.feeds(), self.store.memberships())
        limit = asyncio.Semaphore(2)
        completed = 0
        async def story(identity):
            nonlocal completed
            async with limit:
                advisory = self.store.advisory(identity)
                name = advisory.title.split(' issued')[0]
                async def optional(label, operation, seconds):
                    try:
                        return await asyncio.wait_for(operation(), seconds)
                    except (ValueError, KeyError, OSError, httpx.HTTPError, TimeoutError) as error:
                        problems.append(f'{name} · {label}: {str(error) or "source timed out; cached observations retained"}')
                        return None
                if advisory.provider == 'NWS':
                    result = await optional('county outlines', lambda:geography.fetch_counties(self.store, self.visuals.client, advisory), 10)
                    problems.extend(result or [])
                geo = self.visuals.geography(identity, intelligence)['geojson']
                region = story_bounds({'geojson':geo})
                if not region and advisory.provider == 'NWS':
                    region = story_bounds({'geojson':{'features':[{'geometry':shape['geometry']} for shape in geography.county_shapes(self.store, advisory)]}})
                if region:
                    # For past stories go straight to the archive; live nowCOAST cannot supply yesterday's radar.
                    from datetime import datetime, timezone, timedelta
                    historical = advisory.issued_at < datetime.now(timezone.utc)-timedelta(hours=3)
                    radar = await optional('radar',
                        (lambda:radar_archive.collect(self.visuals, advisory.issued_at, region)) if historical else
                        (lambda:self.visuals.collect_radar_at(advisory.issued_at, region)), 30)
                    if radar:
                        found.append(f'{name}: {len(radar)} radar frames at {advisory.issued_at:%d %b %H:%M UTC}')
                    frames = await optional('satellite', lambda:satellite.collect(self.visuals, advisory.issued_at, region), 25)
                    if frames:
                        found.append(f'{name}: {len(frames)} time-matched GeoColor frames')
                else:
                    problems.append(f'{name}: no source geography for observation collection')
                completed += 1
                self.stage(job, 'data', 'running', f'Checked observations for {completed} of {len(stories)} stories', completed/len(stories))
        # Optional providers cannot hold the whole production indefinitely. Partial downloads remain reusable.
        try:
            await asyncio.wait_for(asyncio.gather(*(story(identity) for identity in stories)), 90)
        except TimeoutError:
            problems.append('Observation collection reached its 90-second budget; using available cached frames and named maps.')
        severe = any(classify(s['script_segment'], story_text(self.store.advisory(s['parameters'].get('source_advisory_id') or plan['advisory_id'])))['hazard'] in ('tornado','severe_storm') for s in plan['scenes'])
        if severe:
            for product in ('cat', *spc.PROBABILITY):
                try:
                    await asyncio.wait_for(spc.collect(self.store, self.visuals.client, 1, product=product), 6)
                    found.append('SPC '+product+' outlook collected; applied only when valid at the story time')
                except (ValueError, OSError, httpx.HTTPError, TimeoutError) as error:
                    problems.append('SPC '+product+': '+(str(error) or 'source timed out'))
        job['issues'] += [{'code':'data_unavailable','message':m} for m in problems]
        job['data'] = {'collected':found,'unavailable':problems}
        self.stage(job, 'data', 'done', f'{len(found)} source layers collected · {len(problems)} availability notes')

    def current_plan(self, job, plan):
        """A script edited after its plan was made gets a fresh plan from the latest revision instead of failing the job."""
        script = self.production.describe_script(self.store.script(plan['script_id']))
        if script['revision'] == plan['script_revision'] or not script.get('is_latest', True) or not self.visuals:
            return plan
        fresh = self.visuals.plan(script, plan.get('style', 'map'))
        job['plan_id'] = job['request']['plan_id'] = fresh['id']
        self.save(job)
        return fresh

    async def run(self, job):
        try:
            job['status'] = 'running';self.save(job)
            request = job['request']
            # 1. Validate.
            self.stage(job, 'validate', 'running')
            plan = self.current_plan(job, self.store.visual_plan(job['plan_id']))
            self.production.validate_plan(plan)
            narration = self.store.production_get('media', request['narration_id'])
            if narration['kind'] != 'audio':
                raise ValueError('Choose the uploaded voiceover audio.')
            self.production.media_path(narration)
            self.stage(job, 'validate', 'done', f"Voiceover {narration['seconds']:.1f}s · {len(plan['scenes'])} script sections")
            # Library clips imported before analysis would otherwise be cut blind across slates, black and camera changes.
            if self.production.unanalyzed_media():
                def progress(index, total, name):
                    self.stage(job, 'plan', 'running', f'Checking library clip {index + 1} of {total} for slates, black and camera cuts')
                analysis = await asyncio.to_thread(self.production.analyze_shots, progress)
                job['issues'] += [{'code': 'footage_analysis', 'message': f'{name} could not be analysed; its cuts may include black or title frames.'} for name in analysis['failed']]
            # 2-3. Align, then plan shots, visuals and footage.
            body = self.base_body(job, plan)
            result = await self.prepared(job, body)
            if not any(i['code'] == 'timing_fallback' for i in job['issues']):
                self.stage(job, 'align', 'done', f"{round((result.get('alignment') or {}).get('result', {}).get('coverage', 1) * 100)}% of script words matched")
            self.stage(job, 'plan', 'running')
            needs = (result.get('mixed_edit') or {}).get('footage_needs', [])
            self.stage(job, 'plan', 'done', f"{len(result['body']['scenes'])} shots · {len(needs)} footage gaps")
            # Real data layers for each story: county outlines, radar at the story time, satellite, SPC outlook.
            await self.collect_data(job, result['body']['plan_id'])
            # 4. Optional footage search for reported gaps, then plan again with the larger library.
            if request['find_footage'] and needs:
                self.stage(job, 'footage', 'running', f'{len(needs)} gaps')
                search = self.footage.start(FootageExpansionRequest(plan_id=result['body']['plan_id'], max_new_clips=request['max_new_clips']))
                job['footage_job_id'] = search['id']
                while search['status'] in ('queued', 'running'):
                    await asyncio.sleep(POLL)
                    search = self.footage.get(search['id'])
                    self.stage(job, 'footage', 'running', search['stage'])
                job['issues'] += [{'code': 'footage_search', 'message': m} for m in search.get('issues', [])[:5]]
                result = await self.prepared(job, {**result['body']})
                self.stage(job, 'footage', 'done', f"{len(search.get('imported', []))} clips added")
            else:
                self.stage(job, 'footage', 'skipped', 'Footage search off' if not request['find_footage'] else 'No gaps')
                if self.visuals is not None and job.get('data', {}).get('collected'):
                    result = await self.prepared(job, {**result['body']})
            check = result['check']
            job['issues'] += [{'code': i['code'], 'message': i['message']} for i in check['issues']]
            if not check['ready']:
                raise ValueError('The edit is not ready: ' + (' '.join(i['message'] for i in check['issues']) or 'see the production issues.'))
            # 5. Timeline.
            self.stage(job, 'timeline', 'running')
            timeline = await asyncio.to_thread(self.production.create_timeline, TimelineRequest(**result['body']))
            job['timeline_id'] = timeline['id']
            self.stage(job, 'timeline', 'done', f"{timeline['seconds']:.1f}s")
            # Storyboard before the full render, so repetition and gaps are visible early.
            self.stage(job, 'storyboard', 'running')
            board = await asyncio.to_thread(self.production.storyboard, self.store.production_get('timelines', timeline['id']))
            job['storyboard'] = {'id': board['id'], 'metrics': board['metrics']}
            m = board['metrics']
            self.stage(job, 'storyboard', 'done', f"{m['distinct_visuals']} distinct visuals · {m['distinct_clips']} clips · places shown {m['place_beats_shown']}/{m['beats_naming_places']}")
            # 6. Render with the existing parallel, resumable renderer.
            self.stage(job, 'render', 'running')
            render = await self.production.start_async(timeline['id'])
            job['render_id'] = render['id']
            while True:
                await asyncio.sleep(POLL)
                render = self.store.production_get('renders', job['render_id'])
                self.stage(job, 'render', 'running', f"{render['stage']} · {render.get('progress', 0)}%", render.get('progress', 0) / 100)
                if render['status'] in ('succeeded', 'failed', 'cancelled'):
                    break
            if render['status'] != 'succeeded':
                raise ValueError(render.get('error') or 'Render ' + render['status'])
            self.stage(job, 'render', 'done', f"{render.get('cached_scenes', 0) + render.get('reused_scenes', 0)} scenes reused")
            # 7. Report.
            job['report'] = render.get('report')
            summary = render.get('report') or {}
            self.stage(job, 'report', 'done', f"{summary.get('errors', 0)} errors · {summary.get('warnings', 0)} warnings")
            job.update(status='succeeded', stage='Finished video ready', progress=100)
            self.save(job)
        except asyncio.CancelledError:
            job.update(status='cancelled', stage='Cancelled', error='Production cancelled. Resume to continue.')
            self.save(job)
            raise
        except Exception as error:
            logging.getLogger(__name__).exception('Automatic production failed')
            for stage in job['stages']:
                if stage['status'] == 'running':
                    stage['status'] = 'failed'
            from pydantic import ValidationError
            if isinstance(error, ValidationError):
                fields = sorted({'.'.join(str(part) for part in e['loc'][:1]) for e in error.errors()})
                message = f"The prepared edit failed {len(error.errors())} internal checks ({', '.join(fields)}). This is an application bug, not a problem with your script or audio; please report it."
            else:
                message = str(error) if isinstance(error, (ValueError, KeyError, RevisionConflict)) else 'Unexpected production failure; inspect backend.log.'
            job.update(status='failed', stage='Needs attention', error=message)
            self.save(job)
