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


def nhc_url(url: str, allow_live: bool = False) -> str:
    parsed = urlsplit(url)
    archived = re.fullmatch(r"/archive/\d{4}/[a-z]{2}\d{2}/[a-z]{2}\d{6}\.public(?:_a)?\.\d{3}\.shtml", parsed.path)
    live = allow_live and re.fullmatch(r"/text/refresh/(?:MIA|EP)?TCP(?:AT|EP)\d\+shtml/\d{6}\.shtml", parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != "www.nhc.noaa.gov" or parsed.port is not None
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not (archived or live)):
        raise ValueError("Use an HTTPS NHC archived public advisory URL, without query parameters.")
    return url


def parse_nhc(text: str, url: str, provenance="manual_import") -> Advisory:
    nhc_url(url, allow_live=True)
    match = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.S | re.I)
    content = html.unescape(match.group(1) if match else text)
    content = re.sub(r"<br\s*/?>|</p>", "\n", content, flags=re.I)
    clean = re.sub(r"<[^>]+>", "", content).strip()
    title = re.search(r"^((?:Hurricane|Tropical Storm|Tropical Depression|Post-Tropical Cyclone|Potential Tropical Cyclone) .+?)\s+(?:Intermediate\s+)?Advisory\s+Number\s+(\d+[A-Z]?)\s*$", clean, re.M | re.I)
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
    if path.startswith('/archive/') and (identifier.group(1).lower() not in path or f"/{year}/" not in path or int(title.group(2).rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')) != int(path.split('.')[-2])):
        raise ValueError("Advisory storm ID or year does not match its source URL.")
    mph, kph = map(int, wind.groups())
    mb = int(pressure.group(1))
    lat = float(location.group(1)) * (1 if location.group(2) == "N" else -1)
    lon = float(location.group(3)) * (1 if location.group(4) == "E" else -1)
    if abs(kph - mph * 1.609344) > 8 or not (800 <= mb <= 1100) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid position, pressure or inconsistent wind units.")
    facts = {"advisory_number":title.group(2).upper(), "wind_mph":mph, "wind_kph":kph, "pressure_mb":mb, "latitude":lat, "longitude":lon}
    movement = re.search(r"PRESENT MOVEMENT[. ]+\w+ OR (\d+) DEGREES AT (\d+) MPH", clean)
    if movement:
        facts.update(movement_degrees=int(movement.group(1)), movement_mph=int(movement.group(2)))
    warnings = []
    summary = re.search(r"SUMMARY OF WATCHES AND WARNINGS IN EFFECT:(.*?)(?=\nA [^\n]+? means|\nDISCUSSION AND OUTLOOK|\Z)", clean, re.S)
    if summary:
        heading = ""
        for line in summary.group(1).splitlines():
            if re.match(r"A .+? is in effect for", line):
                heading = line.strip().rstrip('.')
            elif line.strip().startswith('*') and heading:
                warnings.append(heading + ': ' + line.strip().lstrip('*').strip())
    if warnings:
        facts['warnings_summary'] = '\n'.join(warnings)
    forecast = re.search(r"DISCUSSION AND OUTLOOK\s*\n-+\s*\n(.*?)(?=\nHAZARDS AFFECTING LAND|\nNEXT ADVISORY|\Z)", clean, re.S)
    return Advisory(id=f"nhc:{identifier.group(1)}:{title.group(2).upper()}", provider="NHC", event_key=identifier.group(1), title=title.group(1), issued_at=issued,
        source_url=url, provenance=provenance, severity="Extreme" if mph >= 111 else "Severe" if mph >= 74 else "Moderate" if mph >= 39 else "Minor", text=clean,
        checksum=hashlib.sha256(clean.encode()).hexdigest(), facts=facts, warnings=warnings, forecast_excerpt=forecast.group(1).strip() if forecast else None)


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
        return [normalize_nws(feature) for feature in payload["features"]]


def normalize_nws(feature: dict) -> Advisory:
    import json
    p = feature["properties"]
    required = ("id", "sent", "expires", "event", "description", "status", "messageType", "areaDesc")
    missing = [key for key in required if not p.get(key)]
    if missing:
        raise ValueError("Official alert missing required fields: " + ', '.join(missing))
    issued, expires = datetime.fromisoformat(p["sent"]), datetime.fromisoformat(p["expires"])
    if issued.tzinfo is None or expires.tzinfo is None:
        raise ValueError("Alert timestamps must contain timezone offsets.")
    if expires <= issued or issued > datetime.now(timezone.utc) + timedelta(minutes=10):
        raise ValueError("Alert has an invalid validity period or future issue time.")
    url = urlsplit(feature["id"])
    if url.scheme != "https" or url.hostname != "api.weather.gov" or url.port is not None or url.username or url.password or not url.path.startswith('/alerts/') or url.query or url.fragment:
        raise ValueError("Alert source is not an official NWS alert URL.")
    if p['status'] not in ('Actual', 'Exercise', 'System', 'Test', 'Draft') or p['messageType'] not in ('Alert', 'Update', 'Cancel', 'Ack', 'Error'):
        raise ValueError("Unknown CAP alert status or message type.")
    references = [r['identifier'] for r in p.get('references', []) if r.get('identifier')]
    return Advisory(id=p["id"], event_key=p["id"], provider="NWS", title=p["event"], issued_at=issued,
        expires_at=expires, source_url=feature["id"], provenance="official_fetch", severity=p.get("severity", "Unknown"), area=p["areaDesc"],
        text="\n\n".join(x for x in [p.get("headline"), p.get("description"), p.get("instruction")] if x),
        references=references, source_feed_url="https://api.weather.gov/alerts/active", source_payload=feature,
        facts={"certainty":p.get("certainty"), "urgency":p.get("urgency"), "status":p.get("status"), "message_type":p.get("messageType"), "severity":p.get("severity", "Unknown"), "area":p['areaDesc'], "description":p.get('description'), "instruction":p.get('instruction')},
        checksum=hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest())


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
    if latest.forecast_excerpt != previous.forecast_excerpt:
        result.append(Change(field='forecast_guidance', previous=previous.forecast_excerpt, current=latest.forecast_excerpt))
    return result


def freshness(item: Advisory, current: datetime | None = None) -> str:
    if item.provenance == "synthetic_fixture":
        return "training"
    current = current or datetime.now(timezone.utc)
    if item.expires_at and item.expires_at <= current:
        return "expired"
    if item.provider == "NWS" and item.facts.get("message_type") == "Cancel":
        return "cancelled"
    if item.provider == "NWS" and (item.facts.get("status") != "Actual" or item.facts.get("message_type") not in ("Alert", "Update")):
        return "non-operational"
    if item.provenance != "official_fetch":
        return "historical" if item.issued_at < current - timedelta(hours=6) else "unverified"
    if item.provider != "NWS" and item.issued_at < current - timedelta(hours=6):
        return "historical"
    return "current"
