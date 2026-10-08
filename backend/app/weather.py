import asyncio
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlsplit
import httpx
from .contracts import Advisory, Change


class WeatherProvider(Protocol):
    async def collect(self) -> list[Advisory]: ...


def nhc_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.nhc.noaa.gov" or parsed.port is not None
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r"/archive/\d{4}/[a-z]{2}\d{2}/[a-z]{2}\d{6}\.public\.\d{3}\.shtml", parsed.path)):
        raise ValueError("Use an HTTPS NHC archived public advisory URL, without query parameters.")
    return url


def parse_nhc(text: str, url: str, provenance="manual_import") -> Advisory:
    nhc_url(url)
    match = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.S | re.I)
    clean = html.unescape(re.sub(r"<[^>]+>", "", match.group(1) if match else text)).strip()
    title = re.search(r"^((?:Hurricane|Tropical Storm|Tropical Depression|Post-Tropical Cyclone|Potential Tropical Cyclone) .+?) Advisory Number (\d+[A-Z]?)\s*$", clean, re.M | re.I)
    stamp = re.search(r"^(\d{1,4}) (AM|PM) (AST|EDT|EST|CDT|CST|MDT|MST|PDT|PST) \w{3} (\w{3}) (\d{1,2}) (\d{4})\s*$", clean, re.M)
    identifier = re.search(r"\b([A-Z]{2}\d{6})\b", clean)
    wind = re.search(r"MAXIMUM SUSTAINED WINDS[. ]+(\d+) MPH[. ]+(\d+) KM/H", clean)
    pressure = re.search(r"MINIMUM CENTRAL PRESSURE[. ]+(\d+) MB", clean)
    location = re.search(r"LOCATION[. ]+([\d.]+)([NS]) ([\d.]+)([EW])", clean)
    if not all([title, stamp, identifier, wind, pressure, location]):
        raise ValueError("Advisory is missing a recognized NHC title, timestamp, storm ID, position, wind or pressure summary.")
    raw_time, period, zone, month, day, year = stamp.groups()
    digits = raw_time.zfill(4)
    hour, minute = int(digits[:-2]), int(digits[-2:])
    if not 1 <= hour <= 12 or not 0 <= minute < 60:
        raise ValueError("Invalid advisory clock time.")
    offset = {"AST": -4, "EDT": -4, "EST": -5, "CDT": -5, "CST": -6, "MDT": -6, "MST": -7, "PDT": -7, "PST": -8}[zone]
    local = datetime.strptime(f"{year} {month} {day}", "%Y %b %d").replace(hour=hour % 12 + (12 if period == "PM" else 0), minute=minute, tzinfo=timezone(timedelta(hours=offset)))
    issued = local.astimezone(timezone.utc)
    if issued > datetime.now(timezone.utc) + timedelta(minutes=10):
        raise ValueError("Advisory issue time is in the future.")
    path = urlsplit(url).path
    if identifier.group(1).lower() not in path or f"/{year}/" not in path:
        raise ValueError("Advisory storm ID or year does not match its source URL.")
    mph, kph = map(int, wind.groups())
    mb = int(pressure.group(1))
    lat = float(location.group(1)) * (1 if location.group(2) == "N" else -1)
    lon = float(location.group(3)) * (1 if location.group(4) == "E" else -1)
    if abs(kph - mph * 1.609344) > 8 or not (800 <= mb <= 1100) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid position, pressure or inconsistent wind units.")
    return Advisory(id=f"nhc:{identifier.group(1)}:{title.group(2)}", provider="NHC", event_key=identifier.group(1), title=title.group(1), issued_at=issued,
        source_url=url, provenance=provenance, severity="Extreme" if mph >= 111 else "Severe", text=clean,
        checksum=hashlib.sha256(clean.encode()).hexdigest(), facts={"advisory_number":title.group(2), "wind_mph":mph, "wind_kph":kph, "pressure_mb":mb, "latitude":lat, "longitude":lon})


async def fetch_official(url: str) -> str:
    async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers={"User-Agent": "WeatherIntelligenceStudio/0.1 (local weather research)", "Accept": "application/geo+json,application/json,text/html"}) as client:
        for attempt in range(3):
            try:
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > 8_000_000:
                    raise ValueError("Source response exceeds the 8 MB limit.")
                return response.text
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * 2**attempt)
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                await asyncio.sleep(0.5 * 2**attempt)
    raise RuntimeError("Source request exhausted retries.")


class NWSProvider:
    async def collect(self) -> list[Advisory]:
        import json
        payload = json.loads(await fetch_official("https://api.weather.gov/alerts/active"))
        result = []
        for feature in payload["features"]:
            p = feature["properties"]
            if not p.get("sent") or not p.get("expires") or not p.get("event"):
                raise ValueError("Official alert missing issue time, expiry or event type.")
            result.append(Advisory(id=p["id"], event_key=p["id"], provider="NWS", title=p["event"], issued_at=datetime.fromisoformat(p["sent"]),
                expires_at=datetime.fromisoformat(p["expires"]), source_url=feature["id"], provenance="official_fetch", severity=p["severity"], area=p["areaDesc"],
                text="\n\n".join(x for x in [p.get("headline"), p.get("description"), p.get("instruction")] if x), facts={"certainty":p.get("certainty"), "urgency":p.get("urgency"), "status":p.get("status"), "message_type":p.get("messageType")},
                checksum=hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()))
        return result


def changes(previous: Advisory | None, latest: Advisory) -> list[Change]:
    if not previous:
        return []
    result = []
    for key, value in latest.facts.items():
        if key in ("advisory_number", "wind_kph") or previous.facts.get(key) == value:
            continue
        before = previous.facts.get(key)
        delta = round(value - before, 2) if isinstance(value, (int, float)) and isinstance(before, (int, float)) else None
        result.append(Change(field=key, previous=before, current=value, delta=delta))
    return result


def freshness(item: Advisory) -> str:
    if item.provenance == "synthetic_fixture":
        return "training"
    current = datetime.now(timezone.utc)
    if item.expires_at and item.expires_at <= current:
        return "expired"
    if item.issued_at < current - timedelta(hours=6):
        return "historical"
    if item.provenance != "official_fetch":
        return "unverified"
    if item.provider == "NWS" and (item.facts.get("status") != "Actual" or item.facts.get("message_type") == "Cancel"):
        return "non-operational"
    return "current"
