"""Deliberately synthetic data for an offline training workflow, never an official observation."""
import hashlib
from datetime import datetime, timezone
from .contracts import Advisory


def training_advisories() -> list[Advisory]:
    result = []
    for n, hour, wind, pressure, lat, lon in [(1, 12, 85, 975, 24.1, -82.5), (2, 18, 100, 965, 25.2, -81.9)]:
        text = f"SYNTHETIC TRAINING SCENARIO. Not an observed storm. Training Cyclone advisory {n}: {wind} mph, {pressure} mb."
        result.append(Advisory(id=f"training:cyclone:{n}", provider="TRAINING", event_key="training:cyclone", title="Training Cyclone", issued_at=datetime(2024, 1, 1, hour, tzinfo=timezone.utc), source_url=f"fixture://training/cyclone/{n}", provenance="synthetic_fixture", severity="Training", text=text, checksum=hashlib.sha256(text.encode()).hexdigest(), facts={"advisory_number":str(n), "wind_mph":wind,"pressure_mb":pressure, "latitude":lat,"longitude":lon}))
    return result
