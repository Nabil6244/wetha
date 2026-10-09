import csv
import io
import json
import logging
import os
import shutil
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
        app.state.production = Production(store, describe_script)
        app.state.discovery = MediaDiscovery(app.state.production, discovery_transport)
        collector.start()
        logger.info(json.dumps({"event":"backend_ready", "database":str(store.path)}))
        try:
            yield
        finally:
            await app.state.production.close()
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
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid_request(request, error):
        return JSONResponse({"detail":str(error)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_record(request, error):
        return JSONResponse({"detail":"Record not found"}, status_code=404)

    @app.exception_handler(RevisionConflict)
    async def revision_conflict(request, error):
        return JSONResponse({'detail':str(error)}, status_code=409)

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
        result['is_latest'] = document['revision'] == store.script(document['id']).get('revision', 1)
        if not result['is_latest']:
            result['editorial']['can_review'] = False
        result['versions'] = store.versions(document['id'])
        result['reviews'] = reviews
        return result

    @app.get("/api/health")
    def health():
        store.channel()  # Read persisted state; a live process alone is not readiness.
        return {"status":"ok", "version":"0.5.0", "database":"connected", "capabilities":{
            "ffmpeg":bool(shutil.which("ffmpeg")), "ffprobe":bool(shutil.which("ffprobe")),
            "newsroom":True, "script_revisions":True, "visual_director":True, "media_library":True, "tts":False, "obs":False,
            "rendering":bool(shutil.which('ffmpeg') and shutil.which('ffprobe')), "native_backend_bundle":False}}

    @app.get("/api/dashboard")
    def dashboard():
        scripts = store.scripts()
        intelligence = desk()
        advisories = intelligence.items
        described = intelligence.descriptions()
        current = [a for a in described if a['freshness'] == 'current']
        latest = next((a for a in advisories if a.provenance == "official_fetch"), None)
        runs = store.runs()
        last_steps = {step['agent']:step for step in store.run(runs[0]['id'])['steps']} if runs else {}
        return {"channel":store.channel(), "advisories":described, "scripts":[describe_script(s, intelligence) for s in scripts], "jobs":store.jobs(),
            "intelligence":{"feeds":store.feeds(), "events":intelligence.events(), "quarantine":store.quarantine()},
            "stats":{"stored_advisories":len(advisories), "current_alerts":len(current), "scripts":len(scripts),
                     "programs":sum(r['status'] == 'succeeded' for r in store.production_list('renders'))},
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
        result['plans'] = [evaluate_plan(plan) for plan in result['plans']]
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
        return app.state.production.start(body.timeline_id)

    @app.post('/api/production/renders/{identity}/retry')
    async def retry_render(identity: str):
        job = store.production_get('renders', identity)
        return app.state.production.start(job['timeline_id'], identity)

    @app.post('/api/production/renders/{identity}/cancel')
    async def cancel_render(identity: str):
        return await app.state.production.cancel(identity)

    @app.get('/api/production/renders/{identity}/{kind}')
    def export_production(identity: str, kind: str, download: bool = False):
        types = {'video': 'video/mp4', 'subtitles': 'application/x-subrip', 'manifest': 'application/json'}
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
