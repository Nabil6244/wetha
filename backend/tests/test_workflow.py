"""Synthetic data tests. These are not historical official hurricane fixtures."""
import asyncio
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.weather import parse_nhc, nhc_url, freshness, NWSProvider
from app.contracts import Advisory
from app.fixtures import training_advisories
from app.newsroom import GroundedScriptWriter

URL = "https://www.nhc.noaa.gov/archive/2024/al14/al142024.public.013.shtml"
# NHC-format parser test only: invented training storm and values.
RAW = """Hurricane Training Advisory Number 13
NWS National Hurricane Center Miami FL AL142024
500 AM EDT Mon Oct 07 2024

THIS IS SYNTHETIC TEST TEXT. NOT AN OFFICIAL WEATHER OBSERVATION.
SUMMARY OF 500 AM EDT...0900 UTC...INFORMATION
LOCATION...24.1N 82.5W
MAXIMUM SUSTAINED WINDS...85 MPH...140 KM/H
MINIMUM CENTRAL PRESSURE...975 MB
"""


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as instance:
        yield instance


def test_offline_vertical_slice_and_deduplication(client):
    assert client.get("/api/health").json()["database"] == "connected"
    assert client.post("/api/training/load").json()["inserted"] == 2
    assert client.post("/api/training/load").json()["inserted"] == 0
    items = client.get("/api/advisories").json()
    assert len(items) == 2
    assert items[0]["freshness"] == "training"
    diff = {change["field"]: change for change in items[0]["changes"]}
    assert diff["wind_mph"]["delta"] == 15
    assert diff["pressure_mb"]["delta"] == -10
    script = client.post("/api/scripts", json={"advisory_id":items[0]["id"]}).json()
    assert "synthetic scenario is not a weather observation" in script["text"]
    assert "85 to 100 mph" in script["text"]
    assert len(script["source_refs"]) == 2
    assert script["broadcast_eligible"] is False
    assert client.post(f"/api/scripts/{script['id']}/review", json={"reviewer":"Test editor"}).status_code == 409
    csv = client.get(f"/api/scripts/{script['id']}/scenes.csv")
    assert csv.status_code == 200
    assert "advisory_timestamp" in csv.text
    assert "fixture://training" in csv.text
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stats"]["current_alerts"] == 0
    assert dashboard["stats"]["scripts"] == 1


def test_migrations_persistence_and_interrupted_jobs(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/training/load")
        identity = app.state.store.start_job("interrupted-test")
    with TestClient(create_app(tmp_path)) as client:
        assert len(client.get("/api/advisories").json()) == 2
        job = client.get("/api/dashboard").json()["jobs"][0]
        assert job["id"] == identity and job["status"] == "failed"


def test_nhc_manual_import_keeps_unverified_provenance(client):
    result = client.post("/api/advisories/import", json={"text":RAW, "source_url":URL})
    assert result.status_code == 200
    item = result.json()["advisory"]
    assert item["provenance"] == "manual_import"
    assert item["freshness"] == "historical"
    assert item["issued_at"] == "2024-10-07T09:00:00Z"
    assert item["facts"]["longitude"] == -82.5
    assert client.post("/api/advisories/import", json={"text":RAW, "source_url":URL}).json()["inserted"] is False
    changed = client.post("/api/advisories/import", json={"text":RAW.replace("975 MB", "970 MB"), "source_url":URL})
    assert changed.status_code == 422
    assert "immutable" in changed.json()["detail"]


@pytest.mark.parametrize("url", ["http://www.nhc.noaa.gov/x", "https://www.nhc.noaa.gov.evil.test/archive/2024/al14/al142024.public.013.shtml", "https://127.0.0.1/x", URL + "?target=localhost", URL.replace("www.nhc.noaa.gov", "user@www.nhc.noaa.gov"), URL.replace("www.nhc.noaa.gov", "www.nhc.noaa.gov:443")])
def test_source_allowlist_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        nhc_url(url)


@pytest.mark.parametrize("text", [RAW.replace("975 MB", "700 MB"), RAW.replace("140 KM/H", "300 KM/H"), RAW.replace("24.1N", "99.1N"), RAW.replace("AL142024", "AL152024"), RAW.replace("500 AM EDT", "1300 AM EDT"), RAW.replace("2024", "2099")])
def test_rejects_missing_or_inconsistent_facts(text):
    with pytest.raises(ValueError):
        parse_nhc(text, URL)


def test_missing_records_and_origin_guard(client):
    assert client.post("/api/scripts", json={"advisory_id":"missing"}).status_code == 404
    assert client.get("/api/scripts/missing/scenes.csv").status_code == 404
    assert client.post("/api/training/load", headers={"Origin":"https://evil.test"}).status_code == 403
    assert client.get("/api/health", headers={"Host":"evil.test"}).status_code == 403


def test_network_failure_creates_job_and_preserves_data(client, monkeypatch):
    async def failed(url):
        raise httpx.ConnectError("proxy denied")
    monkeypatch.setattr("app.main.fetch_official", failed)
    client.post("/api/training/load")
    assert client.post("/api/advisories/fetch", json={"source_url":URL}).status_code == 502
    dashboard = client.get("/api/dashboard").json()
    assert len(dashboard["advisories"]) == 2
    assert dashboard["jobs"][0]["status"] == "failed"


def test_successful_fetch_provenance_promotion(client, monkeypatch):
    async def mocked(url):
        return RAW
    monkeypatch.setattr("app.main.fetch_official", mocked)
    client.post("/api/advisories/import", json={"text":RAW, "source_url":URL})
    result = client.post("/api/advisories/fetch", json={"source_url":URL})
    assert result.status_code == 200
    assert client.get("/api/advisories").json()[0]["provenance"] == "official_fetch"
    assert client.get("/api/dashboard").json()["jobs"][0]["status"] == "succeeded"


def test_nws_collection_normalizes_timezone_and_retains_expiry(monkeypatch):
    import json
    payload = {"features":[{"id":"https://api.weather.gov/alerts/test", "properties":{
        "id":"test-id", "sent":"2024-10-07T05:00:00-04:00", "expires":"2024-10-07T06:00:00-04:00", "event":"Training alert", "severity":"Severe", "areaDesc":"Training area", "description":"Synthetic test description", "status":"Actual", "messageType":"Alert"}}]}
    async def mocked(url):
        return json.dumps(payload)
    monkeypatch.setattr("app.weather.fetch_official", mocked)
    item = asyncio.run(NWSProvider().collect())[0]
    assert item.issued_at.hour == 9
    assert item.expires_at.hour == 10
    assert freshness(item) == "expired"


def test_review_checks_current_time_and_superseding_evidence(client):
    store = client.app.state.store
    current = training_advisories()[0].model_copy(update={"id":"current-test", "provider":"NHC", "provenance":"official_fetch", "issued_at":datetime.now(timezone.utc) - timedelta(minutes=5)})
    store.save_advisory(current)
    script = client.post("/api/scripts", json={"advisory_id":current.id}).json()
    reviewed = client.post(f"/api/scripts/{script['id']}/review", json={"reviewer":"Test editor"})
    assert reviewed.status_code == 200
    assert reviewed.json()["broadcast_eligible"] is False
    assert next(c for c in reviewed.json()["qc"] if c["check"] == "Human editorial review")["passed"]
    newer = current.model_copy(update={"id":"newer-test", "issued_at":datetime.now(timezone.utc)})
    store.save_advisory(newer)
    assert client.post(f"/api/scripts/{script['id']}/review", json={"reviewer":"Test editor"}).status_code == 409
    assert client.get("/api/dashboard").json()["scripts"][0]["label"] == "superseded"


def test_unverified_comparison_blocks_current_draft_review(client):
    store = client.app.state.store
    previous, latest = training_advisories()
    previous = previous.model_copy(update={"provenance":"manual_import", "issued_at":datetime.now(timezone.utc) - timedelta(hours=1)})
    latest = latest.model_copy(update={"provider":"NHC", "provenance":"official_fetch", "issued_at":datetime.now(timezone.utc)})
    store.save_advisory(previous); store.save_advisory(latest)
    script = client.post("/api/scripts", json={"advisory_id":latest.id}).json()
    assert script["label"] == "unverified"
    assert client.post(f"/api/scripts/{script['id']}/review", json={"reviewer":"Test editor"}).status_code == 409


def test_timezone_required():
    sample = training_advisories()[0].model_dump()
    sample["issued_at"] = datetime(2024, 1, 1)
    with pytest.raises(ValueError):
        Advisory.model_validate(sample)
