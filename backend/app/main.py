import csv
import io
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from platformdirs import user_data_dir
from .contracts import ImportRequest, FetchRequest, ScriptRequest, ReviewRequest, PollingRequest
from .storage import Store
from .weather import parse_nhc, nhc_url, fetch_official
from .newsroom import GroundedScriptWriter
from .fixtures import training_advisories
from .collector import Collector
from .intelligence import IntelligenceDesk

logger = logging.getLogger("wetha")


def create_app(data_dir: Path | None = None, source_transport=None) -> FastAPI:
    directory = data_dir or Path(os.environ.get("WETHA_DATA_DIR", user_data_dir("WeatherIntelligenceStudio")))
    store = Store(directory / "studio.sqlite3")

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        collector = Collector(store, source_transport)
        app.state.collector = collector
        collector.start()
        logger.info(json.dumps({"event":"backend_ready", "database":str(store.path)}))
        try:
            yield
        finally:
            await collector.close()

    app = FastAPI(title="Weather Intelligence Studio", version="0.2.0", lifespan=lifespan)
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

    def desk():
        return IntelligenceDesk(store.advisories(), store.feeds(), store.memberships())

    def describe(item):
        return desk().describe(item)

    def describe_script(document, intelligence=None):
        intelligence = intelligence or desk()
        advisory = store.advisory(document["advisory_id"])
        evidence = [store.advisory(identity) for identity in document.get("source_advisory_ids", [advisory.id])]
        label = intelligence.status(advisory)
        official = all(item.provenance == "official_fetch" for item in evidence)
        if label == "current" and not official:
            label = "unverified"
        document["label"] = label
        for check in document["qc"]:
            if check["check"] == "Source provenance":
                check["passed"] = official
            if check["check"] == "Source freshness":
                check["passed"] = label == "current"
        return document

    @app.get("/api/health")
    def health():
        store.channel()  # Read persisted state; a live process alone is not readiness.
        return {"status":"ok", "version":"0.2.0", "database":"connected", "capabilities":{
            "ffmpeg":bool(shutil.which("ffmpeg")), "ffprobe":bool(shutil.which("ffprobe")),
            "tts":False, "obs":False, "rendering":False, "native_backend_bundle":False}}

    @app.get("/api/dashboard")
    def dashboard():
        scripts = store.scripts()
        intelligence = desk()
        advisories = intelligence.items
        described = intelligence.descriptions()
        current = [a for a in described if a['freshness'] == 'current']
        latest = next((a for a in advisories if a.provenance == "official_fetch"), None)
        return {"channel":store.channel(), "advisories":described, "scripts":[describe_script(s, intelligence) for s in scripts], "jobs":store.jobs(),
            "intelligence":{"feeds":store.feeds(), "events":intelligence.events(), "quarantine":store.quarantine()},
            "stats":{"stored_advisories":len(advisories), "current_alerts":len(current), "scripts":len(scripts), "programs":0},
            "latest_official_issue":latest.issued_at.isoformat() if latest else None,
            "broadcast":{"status":"not_configured", "obs_connected":False, "queue":[], "fallback_ready":False},
            "agents":[{"name":name, "status":status} for name, status in [
                ("Data collector", "ready"), ("Change detector", "ready"), ("News prioritizer", "ready"),
                ("Fact verifier", "ready"), ("Scriptwriter", "ready"), ("Editorial controller", "manual")]]}

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

    @app.get('/api/advisories/{identity}/evidence')
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
    def generate_script(body: ScriptRequest):
        advisory = store.advisory(body.advisory_id)
        intelligence = desk()
        document = GroundedScriptWriter().generate(advisory, intelligence.previous(advisory), intelligence.status(advisory))
        store.save_script(document)
        return document

    @app.post("/api/scripts/{identity}/review")
    def review_script(identity: str, body: ReviewRequest):
        document = next((s for s in store.scripts() if s["id"] == identity), None)
        if not document:
            raise KeyError(identity)
        advisory = store.advisory(document["advisory_id"])
        evaluated = describe_script(document)
        if evaluated["label"] != "current":
            raise HTTPException(409, "Only current, officially fetched operational advisories can pass review. Training, unverified and stale reports remain blocked.")
        result = store.review_script(identity, body.reviewer)
        # Editorial review alone is insufficient for broadcast admission.
        return describe_script(result)

    @app.get("/api/scripts/{identity}/scenes.csv")
    def export_scenes(identity: str):
        document = next((s for s in store.scripts() if s["id"] == identity), None)
        if not document:
            raise KeyError(identity)
        buffer = io.StringIO()
        fields = list(document["scenes"][0])
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for scene in document["scenes"]:
            values = {key:json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in scene.items()}
            # Escape spreadsheet formula prefixes for imported source text.
            writer.writerow({key:("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value) for key, value in values.items()})
        return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition":'attachment; filename="scene-plan.csv"'})

    static = Path(os.environ.get("WETHA_UI_DIR", Path(__file__).resolve().parents[2] / "dist"))
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app


app = create_app()
