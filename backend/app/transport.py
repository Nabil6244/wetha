"""Official-source HTTP transport with bounded verified reads and durable validators."""
import asyncio
import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit
import httpx
from .storage import Store


def feed_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.port is not None or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Only canonical HTTPS official feed URLs are allowed.')
    if parsed.hostname == 'www.nhc.noaa.gov' and parsed.path == '/index-at.xml' and not parsed.query:
        return url
    if parsed.hostname == 'api.weather.gov' and parsed.path == '/alerts/active':
        values = parse_qs(parsed.query, keep_blank_values=True)
        if set(values) <= {'cursor', 'limit'} and all(len(v) == 1 for v in values.values()):
            return url
    raise ValueError('Feed or pagination URL is outside the official source allowlist.')


@dataclass
class SourceResponse:
    body: str
    revalidated: bool


class SourceHTTP:
    def __init__(self, store: Store, transport=None):
        self.store = store
        self.client = httpx.AsyncClient(transport=transport, timeout=25, follow_redirects=False,
            headers={'User-Agent':'WeatherIntelligenceStudio/0.2 (official weather research)', 'Accept':'application/geo+json,application/json,application/rss+xml'})

    async def close(self):
        await self.client.aclose()

    async def get(self, url: str) -> SourceResponse:
        feed_url(url)
        cached = self.store.cache(url)
        if cached and hashlib.sha256(cached['body'].encode()).hexdigest() != cached['checksum']:
            raise ValueError('Cached source checksum mismatch; refusing unverified cached content.')
        headers = {}
        if cached:
            if cached['etag']:
                headers['If-None-Match'] = cached['etag']
            if cached['last_modified']:
                headers['If-Modified-Since'] = cached['last_modified']
        for attempt in range(3):
            try:
                async with self.client.stream('GET', url, headers=headers) as response:
                    if response.status_code == 304:
                        if not cached:
                            raise ValueError('Source returned 304 without previously validated content.')
                        self.store.recheck_cache(url)
                        return SourceResponse(cached['body'], True)
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError('Official feed did not return a complete response.')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 8_000_000:
                            raise ValueError('Official source exceeds the 8 MB response limit.')
                    text = body.decode(response.encoding or 'utf-8', errors='strict')
                    self.store.cache_response(url, text, response.headers.get('etag'), response.headers.get('last-modified'))
                    return SourceResponse(text, False)
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == 2:
                    raise
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            await asyncio.sleep(0.5 * 2**attempt)
        raise RuntimeError('Official source retries exhausted.')
