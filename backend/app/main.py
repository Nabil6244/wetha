import csv
import io
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from platformdirs import user_data_dir
from .contracts import ImportRequest, FetchRequest, ScriptRequest, ReviewRequest
from .storage import Store
from .weather import parse_nhc, nhc_url, fetch_official, NWSProvider, changes, freshness
from .newsroom import GroundedScriptWriter
from .fixtures import training_advisories

logger = logging.getLogger("wetha")


def create_app(data_dir: Path | None = None) -> FastAPI:
    directory = data_dir or Path(os.environ.get("WETHA_DATA_DIR", user_data_dir("WeatherIntelligenceStudio")))
    store = Store(directory / "studio.sqlite3")

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        logger.info(json.dumps({"event":"backend_ready", "database":str(store.path)}))
        yield

    app = FastAPI(title="Weather Intelligence Studio", version="0.1.0", lifespan=lifespan)
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

    def describe(item):
        previous = store.previous(item)
        return {**item.model_dump(mode="json"), "freshness":freshness(item), "previous_id":previous.id if previous else None,
            "changes":[c.model_dump() for c in changes(previous, item)]}

    def describe_script(document):
        advisory = store.advisory(document["advisory_id"])
        evidence = [store.advisory(identity) for identity in document.get("source_advisory_ids", [advisory.id])]
        label = freshness(advisory)
        official = all(item.provenance == "official_fetch" for item in evidence)
        superseded = any(item.event_key == advisory.event_key and item.issued_at > advisory.issued_at for item in store.advisories())
        if label == "current" and not official:
            label = "unverified"
        if label == "current" and superseded:
            label = "superseded"
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
        return {"status":"ok", "version":"0.1.0", "database":"connected", "capabilities":{
            "ffmpeg":bool(shutil.which("ffmpeg")), "ffprobe":bool(shutil.which("ffprobe")),
            "tts":False, "obs":False, "rendering":False, "native_backend_bundle":False}}

    @app.get("/api/dashboard")
    def dashboard():
        advisories = store.advisories()
        current = [a for a in advisories if freshness(a) == "current"]
        latest = next((a for a in advisories if a.provenance == "official_fetch"), None)
        return {"channel":store.channel(), "advisories":[describe(a) for a in advisories], "scripts":[describe_script(s) for s in store.scripts()], "jobs":store.jobs(),
            "stats":{"stored_advisories":len(advisories), "current_alerts":len(current), "scripts":len(store.scripts()), "programs":0},
            "latest_official_issue":latest.issued_at.isoformat() if latest else None,
            "broadcast":{"status":"not_configured", "obs_connected":False, "queue":[], "fallback_ready":False},
            "agents":[{"name":name, "status":status} for name, status in [
                ("Data collector", "ready"), ("Change detector", "ready"), ("News prioritizer", "planned"),
                ("Fact verifier", "ready"), ("Scriptwriter", "ready"), ("Editorial controller", "manual")]]}

    @app.get("/api/advisories")
    def advisory_list():
        return [describe(a) for a in store.advisories()]

    @app.post("/api/advisories/import")
    def import_advisory(body: ImportRequest):
        item = parse_nhc(body.text, body.source_url)
        inserted = store.save_advisory(item)
        return {"inserted":inserted, "advisory":describe(item)}

    @app.post("/api/advisories/fetch")
    async def fetch_advisory(body: FetchRequest):
        url = nhc_url(body.source_url)
        job = store.start_job("nhc_archive_fetch")
        try:
            item = parse_nhc(await fetch_official(url), url, "official_fetch")
            inserted = store.save_advisory(item)
            store.finish_job(job, "succeeded", "Stored official NHC advisory" if inserted else "Advisory already cached")
            return {"inserted":inserted, "advisory":describe(item)}
        except Exception as error:
            store.finish_job(job, "failed", type(error).__name__ + ": official source could not be collected")
            if isinstance(error, ValueError):
                raise
            raise HTTPException(502, "NHC fetch failed. Check network access to www.nhc.noaa.gov and the archive URL.") from error

    @app.post("/api/providers/nws/refresh")
    async def refresh_nws():
        job = store.start_job("nws_alert_refresh")
        try:
            items = await NWSProvider().collect()
            inserted = sum(store.save_advisory(item) for item in items)
            store.finish_job(job, "succeeded", f"Collected {len(items)} alerts; {inserted} new")
            return {"collected":len(items), "inserted":inserted}
        except Exception as error:
            store.finish_job(job, "failed", type(error).__name__ + ": official source could not be collected")
            raise HTTPException(502, "NWS refresh failed. Check network access to api.weather.gov. Stored evidence has been preserved.") from error

    @app.post("/api/training/load")
    def training():
        count = sum(store.save_advisory(item) for item in training_advisories())
        return {"inserted":count, "notice":"Synthetic training data; not real weather observations or broadcast material."}

    @app.post("/api/scripts")
    def generate_script(body: ScriptRequest):
        advisory = store.advisory(body.advisory_id)
        document = GroundedScriptWriter().generate(advisory, store.previous(advisory))
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
