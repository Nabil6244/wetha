"""Script + voiceover in, finished video out: one saved, resumable production job.

It drives the existing steps rather than duplicating them: speech alignment, shot planning and the
mixed edit (prepare), optional footage search for reported gaps, timeline creation, the parallel
renderer, quality control and packaging. Every stage is persisted; a restart marks the job
interrupted and Resume re-runs it, reusing the completed alignment and rendered scenes.
"""
import asyncio
import copy
import httpx
from uuid import uuid4
from .contracts import FootageExpansionRequest, TimelineRequest
from .storage import now

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

    def stage(self, job, key, status, detail=''):
        row = next(s for s in job['stages'] if s['key'] == key)
        row.update(status=status, detail=detail)
        if status == 'running':
            job['stage'] = row['label']
        done = sum(s['status'] in ('done', 'skipped') for s in job['stages'])
        job['progress'] = round(done / len(job['stages']) * 100)
        self.save(job)

    def base_body(self, job, plan):
        request = job['request']
        return {'plan_id': plan['id'], 'title': request['title'], 'narration_id': request['narration_id'],
                'narration_verified': request['narration_verified'], 'presentation': 'broadcast', 'automatic_graphs': True,
                'music': False, 'music_bed': request['music_bed'], 'template': None,
                'scenes': request.get('scenes') or [{'id': s['id'], 'seconds': max(1, min(120, s.get('target_seconds') or 4)), 'transition': 'cut'} for s in plan['scenes']]}

    async def prepared(self, job, body):
        """Run prepare; when it starts speech alignment, wait for it and prepare again."""
        while True:
            result = await asyncio.to_thread(self.prepare, TimelineRequest(**body))
            if result['status'] != 'aligning':
                return result
            alignment = result['alignment'];job['alignment_id'] = alignment['id']
            self.stage(job, 'align', 'running', 'Listening locally')
            while alignment['status'] in ('queued', 'running'):
                await asyncio.sleep(POLL)
                alignment = self.alignment.get(alignment['id'])
                self.stage(job, 'align', 'running', f"{alignment['stage']} · {round(alignment.get('progress', 0) * 100)}%")
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
        from . import geography, spc
        from .observations import story_bounds
        from .visual_director import classify, story_text
        self.stage(job, 'data', 'running')
        plan = self.store.visual_plan(plan_id);found = [];problems = []
        stories = list(dict.fromkeys(s['parameters'].get('source_advisory_id') or plan['advisory_id'] for s in plan['scenes']))
        stories = [i for i in stories if self.store.advisory(i).provider != 'TRAINING']
        if not stories:
            # Synthetic training stories never receive real observations.
            self.stage(job, 'data', 'skipped', 'Training stories use no live observations');return
        severe = False
        for identity in stories:
            advisory = self.store.advisory(identity)
            severe = severe or any(classify(s['script_segment'], story_text(advisory))['hazard'] in ('tornado', 'severe_storm') for s in plan['scenes'] if s['parameters'].get('source_advisory_id') == identity)
            if advisory.provider == 'NWS':
                problems += await geography.fetch_counties(self.store, self.visuals.client, advisory)
                found.append(f"{len(geography.county_shapes(self.store, advisory))} county outlines for {advisory.title.split(' issued')[0]}")
            region = story_bounds({'geojson': self.visuals.geography(identity)['geojson']})
            if region:
                try:
                    found.append(f"{len(await self.visuals.collect_radar_at(advisory.issued_at, region))} radar frames at {advisory.issued_at:%H:%M UTC}")
                except (ValueError, KeyError, httpx.HTTPError) as error:
                    # nowCOAST keeps only a few hours; older stories use the archived NEXRAD composites.
                    from . import radar_archive
                    try:
                        found.append(f"{len(await radar_archive.collect(self.visuals, advisory.issued_at, region))} archived radar frames at {advisory.issued_at:%d %b %Y %H:%M UTC}")
                    except (ValueError, KeyError, OSError, httpx.HTTPError) as archive_error:
                        # Radar is optional evidence: a network or image failure leaves this story without it, not the video.
                        problems.append(f'Radar: {error or error.__class__.__name__} Archive: {archive_error or archive_error.__class__.__name__}')
        try:
            await self.visuals.collect('goes')
        except ValueError as error:
            problems.append('Satellite: ' + str(error))
        if severe:
            try:
                await spc.collect(self.store, self.visuals.client, 1)
            except ValueError as error:
                problems.append(str(error))
        job['issues'] += [{'code': 'data_unavailable', 'message': m} for m in problems]
        job['data'] = {'collected': found, 'unavailable': problems}
        self.stage(job, 'data', 'done', ' · '.join(found)[:180] or 'No story data available')

    async def run(self, job):
        try:
            job['status'] = 'running';self.save(job)
            request = job['request']
            # 1. Validate.
            self.stage(job, 'validate', 'running')
            plan = self.store.visual_plan(job['plan_id'])
            self.production.validate_plan(plan)
            narration = self.store.production_get('media', request['narration_id'])
            if narration['kind'] != 'audio':
                raise ValueError('Choose the uploaded voiceover audio.')
            self.production.media_path(narration)
            self.stage(job, 'validate', 'done', f"Voiceover {narration['seconds']:.1f}s · {len(plan['scenes'])} script sections")
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
            render = self.production.start(timeline['id'])
            job['render_id'] = render['id']
            while True:
                await asyncio.sleep(POLL)
                render = self.store.production_get('renders', job['render_id'])
                self.stage(job, 'render', 'running', f"{render['stage']} · {render.get('progress', 0)}%")
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
            for stage in job['stages']:
                if stage['status'] == 'running':
                    stage['status'] = 'failed'
            from pydantic import ValidationError
            if isinstance(error, ValidationError):
                fields = sorted({'.'.join(str(part) for part in e['loc'][:1]) for e in error.errors()})
                message = f"The prepared edit failed {len(error.errors())} internal checks ({', '.join(fields)}). This is an application bug, not a problem with your script or audio; please report it."
            else:
                message = str(error) if isinstance(error, (ValueError, KeyError)) else 'Unexpected production failure; inspect backend.log.'
            job.update(status='failed', stage='Needs attention', error=message)
            self.save(job)
