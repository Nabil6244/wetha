"""Owned background feed workers with persistent schedules and coalesced refreshes."""
import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import httpx
from .weather import normalize_nws, parse_nhc
from .transport import SourceHTTP, feed_url
from .intelligence import IntelligenceDesk
from .storage import Store

logger = logging.getLogger('wetha.collector')


def parse_nhc_feed(body: str) -> tuple[list, list[dict]]:
    if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():
        raise ValueError('RSS declarations and entities are not accepted.')
    root = ET.fromstring(body)
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None or channel.findtext('title') != 'NHC Atlantic':
        raise ValueError('Response is not the official NHC Atlantic RSS feed.')
    items, rejected = [], []
    for entry in channel.findall('item'):
        if 'Public Advisory Number' not in (entry.findtext('title') or ''):
            continue
        source = entry.findtext('link') or ''
        text = entry.findtext('description') or ''
        try:
            item = parse_nhc(text, source, 'official_fetch')
            stamp = parsedate_to_datetime(entry.findtext('pubDate') or '')
            if stamp.tzinfo is None or abs((stamp - item.issued_at).total_seconds()) > 1800:
                raise ValueError('RSS publication and advisory issue times disagree by more than 30 minutes.')
            item.source_feed_url = 'https://www.nhc.noaa.gov/index-at.xml'
            item.source_payload = {'title':entry.findtext('title'), 'link':source, 'description':text, 'pubDate':entry.findtext('pubDate')}
            items.append(item)
        except (ValueError, TypeError, KeyError) as error:
            rejected.append({'identifier':source, 'reason':str(error), 'payload':{'description':text, 'title':entry.findtext('title')}})
    return items, rejected


class Collector:
    def __init__(self, store: Store, transport=None):
        self.store = store
        self.http = SourceHTTP(store, transport)
        self.wake = {feed['id']:asyncio.Event() for feed in store.feeds()}
        self.pollers = []
        self.inflight = {}

    def start(self):
        self.pollers = [asyncio.create_task(self._poll(identity), name='weather-poller-' + identity) for identity in self.wake]

    async def close(self):
        for task in [*self.pollers, *self.inflight.values()]:
            task.cancel()
        await asyncio.gather(*self.pollers, *self.inflight.values(), return_exceptions=True)
        await self.http.close()

    def feed(self, identity):
        try:
            return next(feed for feed in self.store.feeds() if feed['id'] == identity)
        except StopIteration:
            raise KeyError(identity) from None

    def configure(self, identity, enabled, interval):
        self.store.configure_feed(identity, enabled, interval)
        self.wake[identity].set()
        return self.feed(identity)

    async def refresh(self, identity: str) -> dict:
        self.feed(identity)
        task = self.inflight.get(identity)
        if task is None or task.done():
            task = asyncio.create_task(self._collect(identity), name='weather-collection-' + identity)
            self.inflight[identity] = task
        return await asyncio.shield(task)

    async def _collect(self, identity):
        feed = self.feed(identity)
        job = self.store.start_job(identity + '_alert_refresh')
        self.store.attempt_feed(identity)
        try:
            cached_pages = 0
            if identity == 'nhc':
                response = await self.http.get(feed['url'])
                cached_pages += int(response.revalidated)
                items, rejected = parse_nhc_feed(response.body)
            else:
                items, rejected, seen_urls = [], [], set()
                url = feed['url']
                while url:
                    if url in seen_urls or len(seen_urls) >= 20:
                        raise ValueError('NWS pagination is cyclic or exceeds 20 pages; refusing an incomplete refresh.')
                    seen_urls.add(url)
                    response = await self.http.get(url)
                    cached_pages += int(response.revalidated)
                    payload = json.loads(response.body)
                    if payload.get('type') != 'FeatureCollection' or not isinstance(payload.get('features'), list):
                        raise ValueError('NWS response is not an alert FeatureCollection.')
                    for feature in payload['features']:
                        try:
                            items.append(normalize_nws(feature))
                        except (ValueError, TypeError, KeyError) as error:
                            rejected.append({'identifier':str(feature.get('id', 'unknown')) if isinstance(feature, dict) else 'unknown', 'reason':str(error), 'payload':feature})
                    url = payload.get('pagination', {}).get('next')
                    if url:
                        feed_url(url)
            # A conflicting immutable ID is quarantined; other valid evidence can still be ingested.
            candidates, conflicting_ids = {}, set()
            for item in items:
                if item.id in conflicting_ids:
                    continue
                if item.id in candidates:
                    if candidates[item.id].checksum != item.checksum:
                        rejected.append({'identifier':item.id, 'reason':'Competing source payloads use the same advisory ID within one refresh', 'payload':{'versions':[candidates[item.id].model_dump(mode='json'), item.model_dump(mode='json')]}})
                        candidates.pop(item.id)
                        conflicting_ids.add(item.id)
                else:
                    candidates[item.id] = item
            valid = []
            for item in candidates.values():
                try:
                    previous = self.store.advisory(item.id)
                except KeyError:
                    previous = None
                if previous and previous.checksum != item.checksum:
                    rejected.append({'identifier':item.id, 'reason':'Stored advisory ID has conflicting immutable evidence', 'payload':item.model_dump(mode='json')})
                else:
                    valid.append(item)
            inserted = self.store.complete_feed(identity, valid, rejected)
            self.rebuild_events()
            result = {'feed':identity, 'collected':len(valid), 'inserted':inserted, 'rejected':len(rejected), 'revalidated_pages':cached_pages}
            self.store.finish_job(job, 'succeeded', f"{len(valid)} valid advisories; {inserted} new; {len(rejected)} quarantined; {cached_pages} revalidated pages")
            logger.info(json.dumps({'event':'feed_collected', **result}))
            return result
        except asyncio.CancelledError:
            self.store.fail_feed(identity, 'Collection interrupted by shutdown')
            self.store.finish_job(job, 'failed', 'Collection interrupted by shutdown')
            raise
        except Exception as error:
            if isinstance(error, httpx.HTTPStatusError):
                detail = f'Official source returned HTTP {error.response.status_code}'
            elif isinstance(error, httpx.RequestError):
                detail = 'Official source connection failed: ' + type(error).__name__
            else:
                detail = 'Source validation failed: ' + str(error)[:300]
            self.store.fail_feed(identity, detail)
            self.store.finish_job(job, 'failed', detail)
            self.rebuild_events()
            logger.warning(json.dumps({'event':'feed_failed', 'feed':identity, 'reason':detail}))
            raise
        finally:
            updated = self.feed(identity)
            interval = min(3600, updated['interval_seconds'] * 2**min(updated['consecutive_failures'], 5))
            self.store.schedule_feed(identity, (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat() if updated['enabled'] else None)

    def rebuild_events(self):
        desk = IntelligenceDesk(self.store.advisories(), self.store.feeds(), self.store.memberships())
        self.store.save_events(desk.events())

    async def _poll(self, identity):
        while True:
            feed = self.feed(identity)
            if feed['enabled']:
                due = datetime.fromisoformat(feed['next_poll_at']) if feed['next_poll_at'] else datetime.now(timezone.utc)
                delay = max(0, (due - datetime.now(timezone.utc)).total_seconds())
                if delay == 0:
                    try:
                        await self.refresh(identity)
                    except Exception:
                        pass  # The durable job and source status already record the failure.
                    continue
            else:
                delay = 3600
            try:
                await asyncio.wait_for(self.wake[identity].wait(), timeout=delay)
                self.wake[identity].clear()
            except asyncio.TimeoutError:
                pass
