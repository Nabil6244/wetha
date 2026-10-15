import asyncio
import csv
import io
import json
import logging
import os
import shutil
import errno
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from platformdirs import user_data_dir
from .contracts import ImportRequest, FetchRequest, ScriptRequest, ReviewRequest, PollingRequest, EditRequest, ClaimSupportRequest, VisualPlanRequest, SceneImportRequest
from .storage import Store, RevisionConflict
from .weather import parse_nhc, nhc_url, fetch_official
from .pipeline import Newsroom
from .editorial import evaluate, edited, attest, legacy_document
from . import polished
from .alignment import AlignmentJobs
from .footage_expansion import FootageExpansion
from .contracts import FootageExpansionRequest, AutoProductionRequest
from .contracts import PolishedRequest, SourceMapRequest, AlignmentRequest
from .models import model_status
from .fixtures import training_advisories
from .collector import Collector
from .intelligence import IntelligenceDesk
from .visuals import VisualEvidence
from .production import Production
from .broadcast import SceneDirection
from .media_discovery import MediaDiscovery
from .contracts import MediaImportMetadata, MediaCatalogRequest, ProductionAssistRequest, MediaDiscoveryRequest, DiscoveryImportRequest, TimelineRequest, RenderRequest, LongformCheckRequest

logger = logging.getLogger("wetha")


def create_app(data_dir: Path | None = None, source_transport=None, model_transport=None, visual_transport=None, discovery_transport=None) -> FastAPI:
    directory = data_dir or Path(os.environ.get("WETHA_DATA_DIR", user_data_dir("WeatherIntelligenceStudio")))
    store = Store(directory / "studio.sqlite3")

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        collector = Collector(store, source_transport)
        app.state.collector = collector
        app.state.newsroom = Newsroom(store, collector, model_transport)
        app.state.visuals = VisualEvidence(store, visual_transport)
        app.state.production = Production(store, describe_script, describe_scripts)
        app.state.alignment = AlignmentJobs(app.state.production)
        app.state.production.alignment_jobs = app.state.alignment
        app.state.discovery = MediaDiscovery(app.state.production, discovery_transport)
        app.state.footage_expansion = FootageExpansion(app.state.discovery)
        from .orchestrator import Orchestrator
        app.state.orchestrator = Orchestrator(store, app.state.production, app.state.alignment, app.state.footage_expansion, prepare_production, app.state.visuals)
        from .maintenance import cleanup
        # Only regenerable, terminal render files; exports and uploaded media are never candidates.
        await asyncio.to_thread(cleanup, store, 'scene_cache', 30)
        await asyncio.to_thread(cleanup, store, 'temporary')
        collector.start()
        logger.info(json.dumps({"event":"backend_ready", "database":str(store.path)}))
        try:
            yield
        finally:
            await app.state.orchestrator.close()
            await app.state.production.close()
            await app.state.footage_expansion.close()
            await app.state.discovery.close()
            await app.state.visuals.close()
            await collector.close()

    app = FastAPI(title="Weather Intelligence Studio", version="0.5.0", lifespan=lifespan)
    app.state.store = store

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Protect local mutation endpoints from arbitrary websites and DNS rebinding.
        if request.headers.get("host", "").split(":")[0] not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail":"Local connections only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in ("http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000", os.environ.get("WETHA_DESKTOP_ORIGIN")):
            return JSONResponse({"detail":"Origin is not allowed"}, status_code=403)
        response = await call_next(request)
        if not request.url.path.startswith(('/api/', '/assets/')):
            # A desktop update must load its current entry point, not an old cached script list.
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ValueError)
    async def invalid_request(request, error):
        return JSONResponse({"detail":str(error)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_record(request, error):
        return JSONResponse({"detail":"Record not found"}, status_code=404)

    @app.exception_handler(RevisionConflict)
    async def revision_conflict(request, error):
        return JSONResponse({'detail':str(error)}, status_code=409)

    @app.exception_handler(OSError)
    async def filesystem_error(request, error):
        logger.exception('Filesystem operation failed', exc_info=error)
        if error.errno == errno.ENOSPC:
            return JSONResponse({'detail':'The disk is full. Open Settings → Storage & performance to clear regenerable cache, then retry.'}, status_code=507)
        return JSONResponse({'detail':'The app could not access a local file. Check that the file still exists and its folder is writable, then retry.'}, status_code=500)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, error):
        logger.exception('Database operation failed', exc_info=error)
        if 'locked' in str(error).lower() or 'busy' in str(error).lower():
            return JSONResponse({'detail':'The database is busy finishing another operation. Wait a moment and retry.'}, status_code=503)
        return JSONResponse({'detail':'The database operation could not finish. Your saved work is retained; restart the app and retry.'}, status_code=500)

    def storage_busy():
        production = app.state.production
        return bool(production.tasks or getattr(production, 'starting', False) or app.state.orchestrator.tasks or
                    any(j['status'] in ('queued', 'running') for j in app.state.alignment.jobs.values()) or
                    app.state.collector.inflight or app.state.visuals.pending)

    @app.get('/api/storage')
    def storage_status():
        from .maintenance import summary
        from .production import render_workers, final_encoder
        return {**summary(store), 'busy': storage_busy() or getattr(app.state.production, 'maintenance', False),
                'render_workers': render_workers(), 'video_encoder': final_encoder(0)[1]}

    @app.post('/api/storage/cleanup/{kind}')
    async def storage_cleanup(kind: str):
        from .maintenance import cleanup
        production = app.state.production
        if getattr(production, 'maintenance', False) or storage_busy():
            raise HTTPException(409, 'Wait for production or collection to finish before clearing storage.')
        production.maintenance = True
        try:
            return await asyncio.to_thread(cleanup, store, kind)
        finally:
            production.maintenance = False

    def desk():
        return IntelligenceDesk(store.advisories(), store.feeds(), store.memberships())

    def describe(item):
        return desk().describe(item)

    def describe_script(document, intelligence=None):
        intelligence = intelligence or desk()
        advisory = store.advisory(document["advisory_id"])
        evidence = [store.advisory(identity) for identity in document.get("source_advisory_ids", [advisory.id])]
        document = legacy_document(document, evidence)
        reviews = store.reviews(document['id'])
        review = next((row for row in reviews if row['revision'] == document['revision']), None)
        result = evaluate(document, intelligence, evidence, review)
        if document.get('polished_narration') or result.get('claims'):
            from .preview_audit import audit
            result['preview_audit'] = audit({**document, 'claims': document.get('claims') or result['claims']}, evidence)
        result['is_latest'] = document['revision'] == store.script(document['id']).get('revision', 1)
        if not result['is_latest']:
            result['editorial']['can_review'] = False
        result['versions'] = store.versions(document['id'])
        result['reviews'] = reviews
        return result

    def describe_scripts(identities):
        intelligence = desk()
        return {identity:describe_script(store.script(identity), intelligence) for identity in identities}

    @app.get("/api/health")
    def health():
        store.channel()  # Read persisted state; a live process alone is not readiness.
        return {"status":"ok", "version":"0.5.0", "database":"connected", "capabilities":{
            "ffmpeg":bool(shutil.which("ffmpeg")), "ffprobe":bool(shutil.which("ffprobe")),
            "newsroom":True, "script_revisions":True, "visual_director":True, "media_library":True, "tts":False, "obs":False,
            "rendering":bool(shutil.which('ffmpeg') and shutil.which('ffprobe')), "native_backend_bundle":False}}

    @app.get("/api/dashboard")
    def dashboard(compact: bool = False):
        scripts = store.scripts()
        intelligence = desk()
        advisories = intelligence.items
        described = intelligence.descriptions()
        current = [a for a in described if a['freshness'] == 'current']
        latest = next((a for a in advisories if a.provenance == "official_fetch"), None)
        runs = store.runs()
        last_steps = {step['agent']:step for step in store.run(runs[0]['id'])['steps']} if runs else {}
        if compact:
            # Lists need names/status, not every alert's polygon, long text and duplicated changes.
            described = [{**{k:a[k] for k in ('id','provider','event_key','title','issued_at','expires_at','source_url',
                'provenance','severity','area','freshness','previous_id','event_id','superseded_by','priority','comparison')},
                'text':'','facts':{},'changes':[],'warnings':[],'forecast_excerpt':None,'detail_available':False,
                'verification':{'status':a['verification']['status'],'checks':[], 'manual_review_required':True,'confidence_note':''}}
                for a in described]
        return {"channel":store.channel(), "advisories":described, "scripts":[describe_script(s, intelligence) for s in scripts], "jobs":store.jobs(),
            "intelligence":{"feeds":store.feeds(), "events":intelligence.events(), "quarantine":store.quarantine()},
            "stats":{"stored_advisories":len(advisories), "current_alerts":len(current), "scripts":len(scripts),
                     "programs":store.production_count('renders','succeeded')},
            "latest_official_issue":latest.issued_at.isoformat() if latest else None,
            "newsroom":{"runs":runs, "engines":model_status()},
            "broadcast":{"status":"not_configured", "obs_connected":False, "queue":[], "fallback_ready":False},
            "agents":[{'name':name, 'status':last_steps.get(name, {}).get('status', 'ready')} for name in (
                'Data collector', 'Change detector', 'News prioritizer', 'Fact verifier', 'Scriptwriter', 'Editorial controller')]}

    @app.get("/api/advisories")
    def advisory_list():
        return desk().descriptions()

    @app.get('/api/intelligence')
    def intelligence_state():
        return {'feeds':store.feeds(), 'events':desk().events(), 'quarantine':store.quarantine()}

    @app.get('/api/events/{identity}')
    def evidence_timeline(identity: str):
        intelligence = desk()
        event = next((event for event in intelligence.events() if event['id'] == identity), None)
        if event is None:
            raise KeyError(identity)
        return {'event':event, 'timeline':[intelligence.describe(intelligence.by_id[item]) for item in event['advisory_ids']]}

    @app.get('/api/advisories/{identity:path}/evidence')
    def original_evidence(identity: str):
        item = store.advisory(identity)
        return {'advisory':describe(item), 'source_payload':item.source_payload, 'checksum':item.checksum}

    @app.post('/api/feeds/{identity}/polling')
    async def configure_polling(identity: str, body: PollingRequest):
        return app.state.collector.configure(identity, body.enabled, body.interval_seconds)

    @app.post('/api/sources/refresh')
    async def refresh_sources():
        import asyncio
        results = await asyncio.gather(*(app.state.collector.refresh(identity) for identity in ('nws', 'nhc')), return_exceptions=True)
        return {'feeds':[result if isinstance(result, dict) else {'feed':identity, 'error':next(feed['last_error'] for feed in store.feeds() if feed['id'] == identity)} for identity, result in zip(('nws', 'nhc'), results)]}

    async def collect(identity):
        try:
            return await app.state.collector.refresh(identity)
        except Exception as error:
            raise HTTPException(502, f'{identity.upper()} refresh failed. Inspect source status and network access; stored evidence was preserved.') from error

    @app.post('/api/providers/nhc/refresh')
    async def refresh_nhc():
        return await collect('nhc')

    @app.post("/api/advisories/import")
    def import_advisory(body: ImportRequest):
        item = parse_nhc(body.text, body.source_url)
        inserted = store.save_advisory(item)
        app.state.collector.rebuild_events()
        return {"inserted":inserted, "advisory":describe(item)}

    @app.post("/api/advisories/fetch")
    async def fetch_advisory(body: FetchRequest):
        url = nhc_url(body.source_url)
        job = store.start_job("nhc_archive_fetch")
        try:
            item = parse_nhc(await fetch_official(url), url, "official_fetch")
            inserted = store.save_advisory(item)
            app.state.collector.rebuild_events()
            store.finish_job(job, "succeeded", "Stored official NHC advisory" if inserted else "Advisory already cached")
            return {"inserted":inserted, "advisory":describe(item)}
        except Exception as error:
            store.finish_job(job, "failed", type(error).__name__ + ": official source could not be collected")
            if isinstance(error, ValueError):
                raise
            raise HTTPException(502, "NHC fetch failed. Check network access to www.nhc.noaa.gov and the archive URL.") from error

    @app.post("/api/providers/nws/refresh")
    async def refresh_nws():
        return await collect('nws')

    @app.post("/api/training/load")
    def training():
        count = sum(store.save_advisory(item) for item in training_advisories())
        app.state.collector.rebuild_events()
        return {"inserted":count, "notice":"Synthetic training data; not real weather observations or broadcast material."}

    @app.post("/api/scripts")
    @app.post('/api/newsroom/runs')
    async def generate_script(body: ScriptRequest):
        document = await app.state.newsroom.run(body)
        return describe_script(document)

    @app.get('/api/newsroom')
    def newsroom_state():
        return {'runs':store.runs(), 'engines':model_status()}

    @app.get('/api/newsroom/runs/{identity}')
    def newsroom_run(identity: str):
        return store.run(identity)

    @app.get('/api/scripts/{identity}')
    def script_detail(identity: str, revision: int | None = None):
        return describe_script(store.script(identity, revision))

    def script_evidence(document):
        return [store.advisory(identity) for identity in document.get('source_advisory_ids', [document['advisory_id']])]

    @app.get('/api/scripts/{identity}/source-pack')
    def copy_source_pack(identity: str):
        document = store.script(identity)
        return polished.source_pack(document, script_evidence(document))

    @app.post('/api/scripts/{identity}/source-map')
    def suggest_source_map(identity: str, body: SourceMapRequest):
        document = store.script(identity)
        selected = document.get('selected_advisory_ids', [document['advisory_id']])
        return polished.suggest(body.text, [a for a in script_evidence(document) if a.id in selected])

    @app.post('/api/scripts/{identity}/polished')
    def save_polished(identity: str, body: PolishedRequest):
        def build(document):
            return polished.save(document, body, script_evidence(document))
        return describe_script(store.revise(identity, body.expected_revision, body.editor, body.note, build))

    @app.post('/api/production/alignment')
    def start_alignment(body: AlignmentRequest):
        return app.state.alignment.start(body.plan_id, body.narration_id)

    @app.get('/api/production/alignment/{identity}')
    def alignment_status(identity: str):
        return app.state.alignment.get(identity)

    @app.post('/api/production/footage-review')
    async def footage_review(body: dict):
        from .footage_review import run
        return await run(app.state.discovery, str(body.get('plan_id', '')))

    @app.post('/api/production/footage-reviews/{identity}/import')
    async def footage_review_import(identity: str, body: dict):
        from .footage_review import import_auto
        if body.get('confirm') is not True:
            raise ValueError('Confirm the batch import of high-confidence clips.')
        return await import_auto(app.state.discovery, identity, int(body.get('max_clips', 8)))

    @app.get('/api/production/footage-reviews/{identity}/sheet')
    def footage_review_sheet(identity: str):
        from uuid import UUID
        path = app.state.production.root / 'footage-reviews' / str(UUID(identity)) / 'footage-review.jpg'
        if not path.is_file():
            raise KeyError(identity)
        return FileResponse(path, media_type='image/jpeg')

    @app.get('/api/settings/footage-keys')
    def footage_key_status():
        return app.state.discovery.credentials.status()

    @app.put('/api/settings/footage-keys')
    def save_footage_keys(body: dict):
        values = {k: v for k, v in body.items() if k in ('pexels', 'pixabay') and isinstance(v, str)}
        status = app.state.discovery.credentials.update(values)
        app.state.discovery.stock_cache.clear()  # New keys must not be served stale or empty cached results.
        return status

    @app.post('/api/settings/footage-keys/test')
    async def test_footage_keys():
        """One small search per configured provider. Reports success or the failure reason, never the key."""
        discovery = app.state.discovery;results = {}
        for provider, search in (('pexels', discovery.pexels), ('pixabay', discovery.pixabay)):
            key = discovery.credentials.get(provider)
            if not key:
                results[provider] = {'ok': False, 'message': 'No key saved.'};continue
            discovery.stock_cache.pop((provider, 'storm clouds'), None)
            rows, problems = await search('storm clouds', key)
            results[provider] = {'ok': not problems, 'results': len(rows), 'message': problems[0] if problems else f'Connected · {len(rows)} sample results'}
        return results

    @app.post('/api/visuals/spc-outlook')
    async def collect_spc_outlook(day: int = 1):
        from . import spc
        if day not in spc.URLS:
            raise ValueError('SPC categorical outlooks are available for days 1-3.')
        identity = await spc.collect(store, app.state.visuals.client, day)
        return {'id': identity, **next(a['metadata'] for a in store.visual_assets('spc_outlook') if a['id'] == identity)}

    @app.post('/api/production/storyboard')
    async def production_storyboard(body: TimelineRequest):
        timeline = app.state.production.create_timeline(body, persist=False)
        result = await asyncio.to_thread(app.state.production.storyboard, timeline)
        return {'id': result['id'], 'metrics': result['metrics'], 'shots': result['shots']}

    @app.get('/api/production/storyboards/{identity}/{kind}')
    def production_storyboard_file(identity: str, kind: str):
        types = {'sheet': 'image/jpeg', 'preview': 'video/mp4', 'json': 'application/json'}
        if kind not in types:
            raise KeyError(kind)
        return FileResponse(app.state.production.storyboard_path(identity, kind), media_type=types[kind])

    @app.post('/api/production/auto')
    async def start_auto_production(body: AutoProductionRequest):
        return app.state.orchestrator.start(body)

    @app.get('/api/production/auto')
    def list_auto_productions():
        return app.state.orchestrator.list()

    @app.get('/api/production/auto/{identity}')
    def auto_production_status(identity: str):
        return app.state.orchestrator.get(identity)

    @app.post('/api/production/auto/{identity}/resume')
    async def resume_auto_production(identity: str):
        return app.state.orchestrator.resume(identity)

    @app.post('/api/production/auto/{identity}/cancel')
    async def cancel_auto_production(identity: str):
        return await app.state.orchestrator.cancel(identity)

    @app.get('/api/production/footage-coverage')
    def footage_coverage(plan_id: str | None = None):
        from .footage_library import coverage
        plan=store.visual_plan(plan_id) if plan_id else None
        return coverage(store.production_list('media'),plan,store.advisory)

    @app.post('/api/production/media/{identity}/quarantine')
    def quarantine_production_media(identity: str, body: dict):
        reason = str(body.get('reason', '')).strip()[:300]
        if len(reason) < 3:
            raise ValueError('Give a reason for quarantining this clip.')
        return app.state.production.quarantine_media(identity, reason)

    @app.post('/api/production/media/{identity}/restore')
    def restore_production_media(identity: str):
        return app.state.production.restore_media(identity)

    @app.post('/api/production/media/analyze-shots')
    async def analyze_footage_shots():
        return await asyncio.to_thread(app.state.production.analyze_shots)

    @app.post('/api/production/find-footage')
    async def find_new_footage(body: FootageExpansionRequest):
        return app.state.footage_expansion.start(body)

    @app.get('/api/production/find-footage/{identity}')
    def footage_search_status(identity: str):
        return app.state.footage_expansion.get(identity)

    @app.post('/api/scripts/{identity}/revisions')
    def revise_script(identity: str, body: EditRequest):
        def build(document):
            evidence = script_evidence(document)
            return edited(legacy_document(document, evidence), body.text, evidence)
        return describe_script(store.revise(identity, body.expected_revision, body.editor, body.note, build))

    @app.post('/api/scripts/{identity}/claims/support')
    def support_claim(identity: str, body: ClaimSupportRequest):
        def build(document):
            evidence = script_evidence(document)
            return attest(legacy_document(document, evidence), body, evidence)
        return describe_script(store.revise(identity, body.expected_revision, body.reviewer, 'Source attestation for ' + body.claim_id, build))

    @app.post("/api/scripts/{identity}/review")
    def review_script(identity: str, body: ReviewRequest):
        def validate(document):
            evaluated = describe_script(document)
            if not evaluated['editorial']['can_review']:
                raise HTTPException(409, 'Only current, officially fetched operational advisories with supported claims can pass review. Training, unverified, stale and unsupported reports remain blocked.')
            # Save the canonical document; presentation-only history is fetched on demand.
            return legacy_document(document, script_evidence(document))
        result = store.review_script(identity, body.reviewer, body.expected_revision, body.note, validate)
        # Editorial review alone is insufficient for broadcast admission.
        return describe_script(result)

    @app.get("/api/scripts/{identity}/scenes.csv")
    def export_scenes(identity: str, revision: int | None = None):
        document = store.script(identity, revision)
        buffer = io.StringIO()
        fields = list(document["scenes"][0])
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for scene in document["scenes"]:
            values = {key:json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in scene.items()}
            # Escape spreadsheet formula prefixes for imported source text.
            writer.writerow({key:("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value) for key, value in values.items()})
        return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition":'attachment; filename="scene-plan.csv"'})

    def evaluate_plan(document):
        script = describe_script(store.script(document['script_id']))
        document['current_source_label'] = script['label']
        document['superseded_script_revision'] = script['revision'] != document['script_revision']
        document['review_valid_now'] = script['review_valid'] and not document['superseded_script_revision']
        return document

    @app.get('/api/visuals')
    def visual_state():
        result = app.state.visuals.state()
        scripts = describe_scripts({p['script_id'] for p in result['plans']}) if result['plans'] else {}
        for plan in result['plans']:
            script = scripts[plan['script_id']]
            plan['current_source_label'] = script['label']
            plan['superseded_script_revision'] = script['revision'] != plan['script_revision']
            plan['review_valid_now'] = script['review_valid'] and not plan['superseded_script_revision']
        return result

    @app.get('/api/visuals/scene-schema')
    def scene_schema():
        return SceneDirection.model_json_schema()

    @app.get('/api/visuals/basemap')
    def basemap():
        file = Path(__file__).parent / 'data/countries.geojson'
        return Response(file.read_bytes(), media_type='application/geo+json')

    @app.get('/api/visuals/geography/{identity:path}')
    def visual_geography(identity: str):
        return app.state.visuals.geography(identity)

    @app.get('/api/visuals/assets/{identity}')
    def visual_asset(identity: str):
        row = app.state.visuals.asset(identity)
        return Response(row['body'], media_type=row['content_type'], headers={'ETag':'"' + row['checksum'] + '"','Cache-Control':'private, max-age=31536000, immutable','X-Content-Type-Options':'nosniff'})

    @app.post('/api/visuals/sources/{identity}/refresh')
    async def collect_visuals(identity: str):
        if identity not in ('goes','radar'):
            raise KeyError(identity)
        return await app.state.visuals.collect(identity)

    @app.post('/api/visuals/forecast-cone')
    async def collect_forecast(body: ScriptRequest):
        return await app.state.visuals.collect('forecast_cone', body.advisory_id)

    @app.post('/api/visuals/plans')
    def visual_plan(body: VisualPlanRequest):
        # Plans retain this immutable version; a later edit marks the plan superseded.
        script = describe_script(store.script(body.script_id))
        if script['revision'] != body.expected_revision:
            raise RevisionConflict('The script changed. Reload its latest revision before directing scenes.')
        return evaluate_plan(app.state.visuals.plan(script, body.style))

    @app.get('/api/visuals/plans/{identity}')
    def plan_detail(identity: str):
        return evaluate_plan(store.visual_plan(identity))

    @app.get('/api/visuals/plans/{identity}/scenes.csv')
    def plan_csv(identity: str):
        document = store.visual_plan(identity)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(document['scenes'][0]))
        writer.writeheader()
        for scene in document['scenes']:
            values = {key:json.dumps(value) if isinstance(value,(dict,list)) else '' if value is None else value for key,value in scene.items()}
            writer.writerow({key:("'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value) for key,value in values.items()})
        return Response(buffer.getvalue(), media_type='text/csv', headers={'Content-Disposition':'attachment; filename="visual-scenes.csv"'})

    @app.post('/api/visuals/plans/{identity}/import')
    def import_scene_plan(identity: str, body: SceneImportRequest):
        return evaluate_plan(app.state.visuals.import_scenes(store.visual_plan(identity),body.csv_text))

    @app.get('/api/production')
    def production_state():
        return app.state.production.state()

    @app.get('/api/production/progress')
    def production_progress():
        # Polling an encoder must not repeatedly rebuild weather intelligence or plans.
        return {'renders':store.render_progress()}

    @app.get('/api/production/benchmark/{kind}')
    def historical_benchmark(kind: str):
        if kind not in ('video', 'manifest'):
            raise HTTPException(status_code=404, detail='Unknown benchmark artifact.')
        path = app.state.production.benchmark_path(kind)
        return FileResponse(path, media_type='video/mp4' if kind == 'video' else 'application/json')

    @app.get('/api/production/episode/{kind}')
    def complete_historical_episode(kind: str):
        if kind not in ('video', 'manifest') or not app.state.production.episode_info()['available']:
            raise HTTPException(status_code=404, detail='Episode artifact unavailable.')
        path = app.state.production.episode_path(kind)
        return FileResponse(path, media_type='video/mp4' if kind == 'video' else 'application/json')

    @app.get('/api/production/user-report/{kind}')
    def narrated_user_report(kind: str, download: bool = False):
        if kind not in ('video','manifest','subtitles') or not app.state.production.user_report_info()['available']:
            raise HTTPException(status_code=404,detail='Narrated report unavailable.')
        path=app.state.production.user_report_path(kind)
        return FileResponse(path,media_type={'video':'video/mp4','manifest':'application/json','subtitles':'application/x-subrip'}[kind],filename=path.name if download else None)

    @app.get('/api/production/forecast-news/{kind}')
    def recorded_forecast_news(kind: str):
        if kind not in ('video', 'manifest', 'subtitles', 'narration') or not app.state.production.forecast_news_info()['available']:
            raise HTTPException(status_code=404, detail='Forecast bulletin artifact unavailable.')
        media = {'video': 'video/mp4', 'manifest': 'application/json',
                 'subtitles': 'application/x-subrip', 'narration': 'audio/wav'}
        return FileResponse(app.state.production.forecast_news_path(kind), media_type=media[kind])

    @app.get('/api/production/regional-chapter/{kind}')
    def historical_regional_chapter(kind: str):
        if kind not in ('video', 'manifest', 'subtitles', 'narration') or not app.state.production.regional_chapter_info()['available']:
            raise HTTPException(status_code=404, detail='Regional chapter artifact unavailable.')
        media = {'video': 'video/mp4', 'manifest': 'application/json',
                 'subtitles': 'application/x-subrip', 'narration': 'audio/wav'}
        return FileResponse(app.state.production.regional_chapter_path(kind), media_type=media[kind])

    @app.get('/api/production/documentary/{kind}')
    def historical_documentary(kind: str):
        if kind not in ('video', 'manifest', 'subtitles') or not app.state.production.documentary_info()['available']:
            raise HTTPException(status_code=404, detail='Documentary artifact unavailable.')
        media = {'video': 'video/mp4', 'manifest': 'application/json', 'subtitles': 'application/x-subrip'}
        return FileResponse(app.state.production.documentary_path(kind), media_type=media[kind])

    @app.get('/api/production/hour-graphics/{kind}')
    def hour_graphics_proof(kind: str):
        if kind not in ('video','manifest') or not app.state.production.hour_graphics_info()['available']:
            raise HTTPException(status_code=404,detail='Graphics proof unavailable.')
        return FileResponse(app.state.production.hour_graphics_path(kind),media_type='video/mp4' if kind=='video' else 'application/json')

    @app.post('/api/production/media')
    async def import_production_media(request: Request):
        header = request.headers.get('x-media-metadata', '')
        if not header or len(header) > 16000:
            raise ValueError('Supply a filename, media type, license, attribution and source record.')
        metadata = MediaImportMetadata.model_validate_json(unquote(header))
        return await app.state.production.import_media(metadata, request.stream())

    @app.post('/api/production/media/folder-import')
    async def import_footage_folder(body: dict):
        if body.get('rights_confirmed') is not True:
            raise ValueError('Confirm you have the right to use the videos in the footage folder.')
        return await app.state.production.import_folder()

    @app.get('/api/production/media/{identity}/file')
    def production_media_file(identity: str):
        media = store.production_get('media', identity)
        return FileResponse(app.state.production.media_path(media), media_type=media['content_type'],
                            headers={'X-Content-Type-Options': 'nosniff'})

    @app.post('/api/production/timelines')
    def create_production_timeline(body: TimelineRequest):
        return app.state.production.create_timeline(body)

    @app.put('/api/production/media/{identity}/catalog')
    def catalog_production_media(identity: str, body: MediaCatalogRequest):
        return app.state.production.catalog_media(identity, body)

    @app.post('/api/production/story')
    def story_production(body: ProductionAssistRequest):
        return app.state.production.story(body)

    @app.get('/api/production/longform')
    def longform_structure():
        from .longform import blueprint
        return blueprint(store.production_list('media'))

    @app.post('/api/production/longform/check')
    def longform_content_check(body: LongformCheckRequest):
        from .longform import audit
        def lookup(identity):
            timeline=app.state.production.describe_timeline(store.production_get('timelines',identity))
            app.state.production.validate_timeline(timeline)
            timeline['event_id']=store.advisory(store.script(timeline['script_id'])['advisory_id']).event_key
            return timeline
        return audit([c.model_dump() for c in body.chapters],lookup)

    @app.post('/api/production/assist')
    def assist_production(body: ProductionAssistRequest):
        return app.state.production.assist(body)

    @app.post('/api/production/check')
    def check_production(body: TimelineRequest):
        return app.state.production.check_timeline(body)

    @app.post('/api/production/prepare')
    def prepare_production(body: TimelineRequest, use_alignment: bool = True):
        """One local preparation step; source audit and alignment are revision bound.

        use_alignment=False keeps the supplied scene timing (the estimated timing fallback); the
        timeline still requires it to match the measured voiceover duration."""
        import copy
        from .bulletin_edit import draft
        production=app.state.production
        plan=store.visual_plan(body.plan_id)
        production.validate_plan(plan)
        payload=body.model_dump()
        job=None
        if body.narration_id and use_alignment:
            jobs=list(app.state.alignment.jobs.values())
            for path in app.state.alignment.directory.glob('*.json'):
                try:jobs.append(app.state.alignment.get(path.stem))
                except (ValueError,KeyError):continue
            audio=store.production_get('media',body.narration_id)
            matching=[j for j in jobs if j['status']=='completed' and j['plan_id']==body.plan_id and j['narration_id']==body.narration_id and j['script_text_checksum']==plan['script_text_checksum'] and j['audio_checksum']==audio['checksum']]
            if not matching:
                return {'status':'aligning','alignment':app.state.alignment.start(body.plan_id,body.narration_id)}
            job=matching[-1]
            if job['result']['coverage']<.95 and not body.narration_verified:
                raise ValueError('Audio match is below 95%. Listen and confirm the recording, or upload the matching voiceover.')
            timed={s['id']:s for s in job['result']['scenes']}
            payload['scenes']=[{**s,'seconds':timed[s['id']]['seconds']} for s in payload['scenes']]
            payload.update(alignment_id=job['id'],narration_verified=True,music=False,template=None)
        if job and payload['presentation']=='broadcast' and not plan.get('automatic_shots') and not any(s.get('media_id') or s.get('cuts') for s in payload['scenes']):
            from .automatic_edit import subdivide
            plan,derived,edits=subdivide(plan,job)
            from .contracts import MAX_VISUAL_SCENES
            if len(edits)>MAX_VISUAL_SCENES:raise ValueError(f'This narration needs more than {MAX_VISUAL_SCENES} visual shots. Split the program into chapters.')
            store.save_visual_plan(plan)
            with app.state.alignment.lock:
                app.state.alignment.jobs[derived['id']]=derived
                (app.state.alignment.directory/(derived['id']+'.json')).write_text(json.dumps(derived))
            payload.update(plan_id=plan['id'],alignment_id=derived['id'],scenes=edits)
        prepared=TimelineRequest(**payload)
        timeline=production.create_timeline(prepared,persist=False)
        media=store.production_list('media');unavailable=[]
        for asset in media:
            if asset['kind']=='audio':continue
            try:production.media_path(asset)
            except (ValueError,OSError):unavailable.append(asset['id'])
        mixed=draft(timeline,media,store.advisory,unavailable) if prepared.presentation=='broadcast' else None
        if mixed:payload['scenes']=mixed['scenes']
        check=production.check_timeline(TimelineRequest(**payload))
        return {'status':'ready' if check['ready'] else 'needs_attention','body':payload,'check':check,'mixed_edit':mixed,'plan':evaluate_plan(plan),'alignment':app.state.alignment.get(payload['alignment_id']) if payload.get('alignment_id') else None,
                'note':'Prepared automatically for local preview. Human broadcast approval is unchanged.'}

    @app.post('/api/production/bulletin-edit')
    def mixed_bulletin_edit(body: TimelineRequest):
        from .bulletin_edit import draft
        production=app.state.production
        timeline=production.create_timeline(body,persist=False)
        media=store.production_list('media')
        unavailable=[]
        for asset in media:
            if asset['kind']=='audio':continue
            try:production.media_path(asset)
            except (ValueError,OSError):unavailable.append(asset['id'])
        return draft(timeline,media,store.advisory,unavailable)

    @app.get('/api/production/discovery')
    async def reviewed_media_discovery():
        return await app.state.discovery.search(MediaDiscoveryRequest(query='storm rain waves', live=False))

    @app.post('/api/production/discovery/search')
    async def search_production_media(body: MediaDiscoveryRequest):
        return await app.state.discovery.search(body)

    @app.post('/api/production/discovery/import')
    async def import_discovered_media(body: DiscoveryImportRequest):
        return await app.state.discovery.import_candidate(body)

    @app.post('/api/production/renders')
    async def start_render(body: RenderRequest):
        return await app.state.production.start_async(body.timeline_id)

    @app.post('/api/production/renders/{identity}/retry')
    async def retry_render(identity: str):
        job = store.production_get('renders', identity)
        return await app.state.production.start_async(job['timeline_id'], identity)

    @app.post('/api/production/renders/{identity}/cancel')
    async def cancel_render(identity: str):
        return await app.state.production.cancel(identity)

    @app.get('/api/production/renders/{identity}/{kind}')
    def export_production(identity: str, kind: str, download: bool = False):
        types = {'video': 'video/mp4', 'subtitles': 'application/x-subrip', 'manifest': 'application/json', 'report': 'application/json',
                 'report_md': 'text/markdown; charset=utf-8', 'thumbnail': 'image/jpeg', 'metadata': 'application/json'}
        if kind not in types:
            raise KeyError(kind)
        path = app.state.production.output_path(identity, kind)
        return FileResponse(path, media_type=types[kind], filename=path.name if download else None,
                            headers={'X-Content-Type-Options': 'nosniff'})

    static = Path(os.environ.get("WETHA_UI_DIR", Path(__file__).resolve().parents[2] / "dist"))
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app


app = create_app()
