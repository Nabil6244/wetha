"""Free media discovery and bounded acquisition, without arbitrary URL downloads."""
import asyncio
import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit, unquote, parse_qs

import httpx

from .contracts import MediaCatalogRequest, MediaImportMetadata
from .media_selection import topics
from .regional import named_regions

API = 'https://commons.wikimedia.org/w/api.php'
MAX_RESPONSE = 2 * 1024 * 1024
MAX_DOWNLOAD = 250 * 1024 * 1024


def plain(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', str(value))).split())


def safe_url(value, hosts):
    try:
        parsed = urlsplit(value)
        return parsed.scheme == 'https' and parsed.hostname in hosts and not parsed.username and not parsed.password and parsed.port is None
    except ValueError:
        return False


def normalize(page):
    infos = page.get('videoinfo') or page.get('imageinfo') or []
    if not infos:
        return None
    info = infos[0]
    meta = info.get('extmetadata', {})
    def field(key):
        return plain(meta.get(key, {}).get('value', ''))
    license_name, license_url = field('LicenseShortName'), field('LicenseUrl')
    allowed = bool(re.fullmatch(r'CC BY (?:2\.0|2\.5|3\.0|4\.0)', license_name)) and bool(re.fullmatch(r'https://creativecommons.org/licenses/by/(?:2\.0|2\.5|3\.0|4\.0)/?', license_url))
    public = license_name in ('CC0', 'Public domain', 'PDM')
    if not (allowed or public):
        return None
    url = info.get('url', '')
    source = info.get('descriptionurl', '')
    if not safe_url(url, {'upload.wikimedia.org'}) or not safe_url(source, {'commons.wikimedia.org'}):
        return None
    mime = info.get('mime', '')
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    kind = 'video' if mime.startswith('video/') else 'image' if mime.startswith('image/') else None
    if not kind or suffix not in ({'.mp4', '.webm', '.mov', '.mkv'} if kind == 'video' else {'.png', '.jpg', '.jpeg', '.webp'}):
        return None
    if not 0 < info.get('size', 0) <= MAX_DOWNLOAD:
        return None
    artist = field('Artist')
    if not 2 <= len(artist) <= 500:
        return None
    raw_credit = str(meta.get('Credit', {}).get('value', ''))
    youtube_ids = set()
    for link in re.findall(r'https://[^\s<>"\']+', html.unescape(raw_credit)):
        if not safe_url(link, {'www.youtube.com', 'youtube.com', 'youtu.be'}):
            continue
        parsed = urlsplit(link)
        ids = [parsed.path.strip('/')] if parsed.hostname == 'youtu.be' else parse_qs(parsed.query).get('v', []) if parsed.path == '/watch' else []
        if len(ids) == 1 and re.fullmatch(r'[A-Za-z0-9_-]{11}', ids[0]):
            youtube_ids.add(ids[0])
    youtube = 'https://www.youtube.com/watch?v=' + next(iter(youtube_ids)) if len(youtube_ids) == 1 and kind == 'video' and allowed else None
    title = plain(page.get('title', 'Media')).removeprefix('File:')
    filename = re.sub(r'[^\w .-]', '_', Path(title).stem)[:120].strip(' .') or 'discovered'
    record = {'title': title, 'filename': filename + suffix,
              'kind': kind, 'download_url': url, 'catalogue_url': source,
              'source': youtube or source, 'source_provider': 'youtube' if youtube else 'stock',
              'provider': 'youtube' if youtube else 'commons', 'context': 'archival' if youtube else 'illustrative',
              'attribution': artist, 'license': license_name + (' ' + license_url if license_url else ''),
              'reuse_basis': 'cc_by' if allowed else 'public_domain',
              'reuse_evidence': source + ' · Wikimedia declared license: ' + license_name + '; review the file page before use.',
              'description': field('ImageDescription')[:1000], 'declared_date': field('DateTimeOriginal')[:100],
              'tags': sorted(topics(field('ImageDescription') + ' ' + page.get('title', ''))),
              'event_id': None, 'location': None, 'captured_at': None,
              'width': info.get('width'), 'height': info.get('height'), 'bytes': info['size'],
              'expected_sha1': info.get('sha1'), 'preferred_clip_seconds': 3.5}
    # A file upload timestamp is not a capture date, and a freeform description
    # does not establish an event ID or geolocation.
    thumb = info.get('thumburl', '')
    record['thumbnail_url'] = thumb if safe_url(thumb, {'upload.wikimedia.org', 'thumb.wikimedia.org'}) else None
    return record


class MediaDiscovery:
    def __init__(self, production, transport=None):
        self.production = production
        self.folder = production.root / 'discovery'
        self.folder.mkdir(exist_ok=True)
        self.client = httpx.AsyncClient(transport=transport, timeout=20, follow_redirects=False,
                                      headers={'User-Agent': 'WeatherIntelligenceStudio/0.5 (local media discovery)'})
        self.cache = {}
        self.stock_cache = {}
        self.lock = asyncio.Lock()
        self.seeds = json.loads((Path(__file__).parent / 'data/discovery-seeds.json').read_text())['assets']

    async def close(self):
        await self.client.aclose()

    def remember(self, candidate):
        candidate = dict(candidate)
        candidate['id'] = hashlib.sha256((candidate['source'] + candidate['download_url']).encode()).hexdigest()
        path = self.folder / (candidate['id'] + '.json')
        if path.exists() and not candidate.get('checksum'):
            recorded = json.loads(path.read_text())
            if (candidate.get('expected_sha1') and recorded.get('expected_sha1') == candidate['expected_sha1']) or (candidate.get('provider')=='nasa' and candidate['download_url']==recorded.get('download_url') and candidate.get('bytes')==recorded.get('bytes')):
                candidate['checksum'] = recorded.get('checksum')
        path.write_text(json.dumps(candidate))
        return candidate

    def reviewed(self):
        return [self.remember({**a, 'provider': a['source_provider'], 'catalogue_url': a.get('reuse_evidence', '').split(' documents')[0] if a['source_provider'] == 'youtube' else a['source'],
                              'description': 'Reviewed sample source; contextual footage, not evidence of the selected event.',
                              'declared_date': a.get('captured_at'), 'expected_sha1': a.get('reviewed_sha1'), 'thumbnail_url': None}) for a in self.seeds]

    async def commons(self, body):
        if body.provider == 'stock':
            return [], []
        query = body.query.strip()
        if body.kind != 'all':
            query += ' filetype:' + ('video' if body.kind == 'video' else 'bitmap')
        params = {'action': 'query', 'format': 'json', 'generator': 'search', 'gsrsearch': query,
                  'gsrnamespace': 6, 'gsrlimit': 24, 'prop': 'videoinfo' if body.kind == 'video' else 'imageinfo'}
        prefix = 'vi' if body.kind == 'video' else 'ii'
        params.update({prefix + 'prop': 'url|size|mime|sha1|extmetadata', prefix + 'urlwidth': 480})
        try:
            async with self.client.stream('GET', API, params=params) as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE:
                        raise ValueError('Discovery response exceeds the size limit.')
            data = json.loads(raw)
            if 'error' in data:
                raise ValueError('Wikimedia returned a search error.')
            rows = []
            for page in data.get('query', {}).get('pages', {}).values():
                candidate = normalize(page)
                if candidate and (body.provider != 'youtube' or candidate['provider'] == 'youtube'):
                    rows.append(self.remember(candidate))
            return rows, []
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            return [], ['Wikimedia search is unavailable. Reviewed sources and external search links remain available.']

    async def nasa(self, body):
        """Real ISS camera footage only; archive context, never current storm evidence."""
        if body.provider != 'all' or body.kind == 'image':return [], []
        try:
            response=await self.client.get('https://images-api.nasa.gov/search',params={'q':body.query,'media_type':'video','page_size':12})
            response.raise_for_status()
            if len(response.content)>MAX_RESPONSE:raise ValueError('NASA response exceeds size limit.')
            rows=[]
            for item in response.json().get('collection',{}).get('items',[]):
                data=(item.get('data') or [{}])[0];title=data.get('title','');description=data.get('description','')
                if not re.search(r'\bISS\b|space station',title,re.I) or re.search(r'animation|visualization|simulation|interview|explainer',title,re.I):continue
                if 'copyright' in description.lower() or '©' in description or data.get('center')!='JSC':continue
                collection=item.get('href','')
                if not safe_url(collection,{'images-assets.nasa.gov'}):continue
                assets=await self.client.get(collection);assets.raise_for_status()
                if len(assets.content)>MAX_RESPONSE:continue
                # NASA catalogs legacy HTTP URLs; request the same official asset over HTTPS.
                variants=[u.replace('http://images-assets.nasa.gov/','https://images-assets.nasa.gov/',1) for u in assets.json() if isinstance(u,str)]
                url=next((u for suffix in ('~medium.mp4','~large.mp4') for u in variants if u.endswith(suffix) and safe_url(u,{'images-assets.nasa.gov'})),None)
                if not url:continue
                header=await self.client.head(url);header.raise_for_status()
                size=int(header.headers.get('content-length',MAX_DOWNLOAD))
                if not 0<size<=MAX_DOWNLOAD:continue
                identity=data.get('nasa_id','')
                if not re.fullmatch(r'[\w.-]+',identity):continue
                page='https://images.nasa.gov/details/'+quote(identity,safe='')
                rows.append(self.remember({'title':title,'filename':identity[:120]+'.mp4','kind':'video',
                    'download_url':url,'catalogue_url':page,'source':page,'source_provider':'stock','provider':'nasa',
                    'context':'archival','attribution':'NASA / Johnson Space Center',
                    'license':'NASA informational editorial use; https://www.nasa.gov/nasa-brand-center/images-and-media/',
                    'reuse_basis':'public_domain','reuse_evidence':page+' · NASA/JSC ISS camera footage; NASA media guidelines apply. Retain source acknowledgement; no endorsement.',
                    'description':plain(description)[:1000],'declared_date':data.get('date_created'),'captured_at':None,
                    'event_id':None,'location':None,'tags':sorted(topics(title+' '+description)),
                    'bytes':size,'width':None,'height':None,'expected_sha1':None,'thumbnail_url':None,'preferred_clip_seconds':3.5}))
                if len(rows)>=4:break
            return rows, []
        except (httpx.HTTPError,ValueError,TypeError,KeyError):return [], ['NASA archive search is unavailable.']

    async def archive(self, body):
        """Internet Archive video items under CC BY or public-domain terms. No key. Dated material is archival.

        Only exact CC BY licence URLs and public-domain marks/dedications are accepted (no share-alike,
        non-commercial or no-derivatives terms). A weather word must appear in the subject or description,
        not only the title, which keeps out people and places that merely share a name."""
        if body.kind == 'image' or body.provider not in ('all', 'stock'):
            return [], []
        query = re.sub(r'[^\w\s-]', ' ', body.query).strip()
        if not query:
            return [], []
        licences = ['licenseurl:*publicdomain*'] + [f'licenseurl:"{scheme}://creativecommons.org/licenses/by/{v}/"' for scheme in ('http', 'https') for v in ('4.0', '3.0')]
        terms = ' '.join(query.split()[:4])
        rows, warnings = [], []
        try:
            docs = {}
            for licence in (licences[0], ' OR '.join(licences[1:])):
                response = await self.client.get('https://archive.org/advancedsearch.php', params={
                    'q': f'(title:({terms}) OR subject:({terms})) AND mediatype:movies AND ({licence})',
                    'fl[]': ['identifier', 'title', 'licenseurl', 'creator', 'date', 'subject', 'description'], 'rows': 12, 'output': 'json'})
                response.raise_for_status()
                for doc in response.json().get('response', {}).get('docs', []):
                    docs.setdefault(doc['identifier'], doc)
            for doc in list(docs.values())[:10]:
                licence = doc.get('licenseurl', '')
                if not re.search(r'creativecommons\.org/(licenses/by/[34]\.0/?$|publicdomain/(zero|mark)/|licenses/publicdomain)', licence):
                    continue
                subject = doc.get('subject', '');subject = ' '.join(subject) if isinstance(subject, list) else subject
                description = doc.get('description', '');description = ' '.join(description) if isinstance(description, list) else description
                if not topics(subject + ' ' + plain(description)[:2000]):
                    continue
                meta = await self.client.get(f"https://archive.org/metadata/{quote(doc['identifier'], safe='')}")
                meta.raise_for_status();data = meta.json()
                server, folder = data.get('d1', ''), data.get('dir', '')
                if not re.fullmatch(r'[a-z0-9]+\.us\.archive\.org', server or ''):
                    continue
                files = [f for f in data.get('files', []) if f.get('name', '').endswith('.mp4') and 0 < int(f.get('size') or 0) <= MAX_DOWNLOAD]
                if not files:
                    continue
                best = max(files, key=lambda f: (int(f.get('height') or 0), int(f.get('size') or 0)))
                page = f"https://archive.org/details/{doc['identifier']}"
                public = 'publicdomain' in licence
                creator = doc.get('creator', '');creator = ', '.join(creator) if isinstance(creator, list) else creator
                title = plain(doc.get('title', 'Internet Archive video'))[:150]
                rows.append(self.remember({'title': title, 'filename': re.sub(r'[^\w.-]', '_', doc['identifier'])[:110] + '.mp4', 'kind': 'video',
                    'download_url': f"https://{server}{folder}/{quote(best['name'])}", 'catalogue_url': page, 'source': page,
                    'source_provider': 'stock', 'provider': 'archive', 'context': 'archival',
                    'attribution': (creator or 'Internet Archive contributor') + ' / Internet Archive',
                    'license': ('Public domain ' if public else 'CC BY ') + licence, 'reuse_basis': 'public_domain' if public else 'cc_by',
                    'reuse_evidence': page + ' · Internet Archive item licence: ' + licence,
                    'description': plain(description)[:1000], 'declared_date': (doc.get('date') or '')[:10] or None,
                    'tags': sorted(topics(title + ' ' + subject + ' ' + plain(description)[:2000])), 'event_id': None, 'location': None,
                    'captured_at': None, 'width': int(best.get('width') or 0) or None, 'height': int(best.get('height') or 0) or None,
                    'bytes': int(best.get('size') or 0) or None, 'expected_sha1': best.get('sha1'), 'thumbnail_url': None, 'preferred_clip_seconds': 3.5}))
            return rows, warnings
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return rows, ['Internet Archive search is unavailable right now.']

    async def stock(self, body):
        """Pexels and Pixabay video APIs. Each needs its own free key; without one the provider is skipped.

        Both licences allow free use without required attribution, but forbid implying endorsement, reselling
        unaltered files, and showing identifiable people in a bad light. Results are illustrative only."""
        import os
        if body.kind == 'image' or body.provider not in ('all', 'stock'):
            return [], []
        jobs = []
        if os.environ.get('PEXELS_API_KEY'):
            jobs.append(self.pexels(body.query, os.environ['PEXELS_API_KEY']))
        if os.environ.get('PIXABAY_API_KEY'):
            jobs.append(self.pixabay(body.query, os.environ['PIXABAY_API_KEY']))
        rows, warnings = [], []
        for found, problems in await asyncio.gather(*jobs):
            rows += found;warnings += problems
        return rows, warnings

    def stock_cached(self, key):
        # Pixabay asks for 24-hour caching of API results; the same window keeps Pexels within its hourly limit.
        cached = self.stock_cache.get(key)
        return cached[1] if cached and time.monotonic() - cached[0] < 86400 else None

    async def pexels(self, query, key):
        cached = self.stock_cached(('pexels', query.casefold()))
        if cached is not None:
            return cached, []
        try:
            response = await self.client.get('https://api.pexels.com/videos/search', params={'query': query, 'per_page': 15, 'orientation': 'landscape'},
                                             headers={'Authorization': key})
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE:raise ValueError('Pexels response exceeds size limit.')
            rows = []
            for video in response.json().get('videos', []):
                files = [f for f in video.get('video_files', []) if f.get('file_type') == 'video/mp4' and (f.get('width') or 0) >= 1280]
                if not files:continue
                best = min(files, key=lambda f: abs((f.get('width') or 0) - 1920))
                if not safe_url(best.get('link', ''), {'videos.pexels.com'}):continue
                page = video.get('url', '');slug = urlsplit(page).path.strip('/').split('/')[-1]
                title = ' '.join(w for w in slug.split('-') if not w.isdigit()).capitalize() or 'Pexels video'
                author = (video.get('user') or {}).get('name') or 'Pexels contributor'
                rows.append(self.remember({'title': title, 'filename': f"pexels-{video['id']}.mp4", 'kind': 'video', 'download_url': best['link'],
                    'catalogue_url': page, 'source': page, 'source_provider': 'stock', 'provider': 'pexels', 'context': 'illustrative',
                    'attribution': author + ' / Pexels', 'license': 'Pexels License https://www.pexels.com/license/',
                    'reuse_basis': 'stock_license', 'reuse_evidence': page + ' · Pexels License: free to use, attribution appreciated; no endorsement, no resale of unaltered copies.',
                    'description': title, 'declared_date': None, 'tags': sorted(topics(title)), 'event_id': None, 'location': None, 'captured_at': None,
                    'width': best.get('width'), 'height': best.get('height'), 'bytes': None, 'seconds': video.get('duration'),
                    'expected_sha1': None, 'thumbnail_url': video.get('image'), 'preferred_clip_seconds': 3.5}))
            self.stock_cache[('pexels', query.casefold())] = (time.monotonic(), rows)
            return rows, []
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return [], ['Pexels search is unavailable; check PEXELS_API_KEY and the hourly request limit.']

    async def pixabay(self, query, key):
        cached = self.stock_cached(('pixabay', query.casefold()))
        if cached is not None:
            return cached, []
        try:
            response = await self.client.get('https://pixabay.com/api/videos/', params={'key': key, 'q': query[:100], 'per_page': 15, 'safesearch': 'true'})
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE:raise ValueError('Pixabay response exceeds size limit.')
            rows = []
            for hit in response.json().get('hits', []):
                sizes = hit.get('videos', {})
                best = next((sizes[k] for k in ('large', 'medium') if sizes.get(k, {}).get('url') and (sizes[k].get('width') or 0) >= 1280), None)
                if not best or not safe_url(best['url'], {'cdn.pixabay.com'}):continue
                page = hit.get('pageURL', '');tags = hit.get('tags', '')
                rows.append(self.remember({'title': tags.title() or 'Pixabay video', 'filename': f"pixabay-{hit['id']}.mp4", 'kind': 'video', 'download_url': best['url'],
                    'catalogue_url': page, 'source': page, 'source_provider': 'stock', 'provider': 'pixabay', 'context': 'illustrative',
                    'attribution': (hit.get('user') or 'Pixabay contributor') + ' / Pixabay', 'license': 'Pixabay Content License https://pixabay.com/service/license-summary/',
                    'reuse_basis': 'stock_license', 'reuse_evidence': page + ' · Pixabay Content License: free to use, no attribution required; no resale of unaltered copies, no endorsement.',
                    'description': tags, 'declared_date': None, 'tags': sorted(topics(tags)), 'event_id': None, 'location': None, 'captured_at': None,
                    'width': best.get('width'), 'height': best.get('height'), 'bytes': best.get('size'), 'seconds': hit.get('duration'),
                    'expected_sha1': None, 'thumbnail_url': best.get('thumbnail'), 'preferred_clip_seconds': 3.5}))
            self.stock_cache[('pixabay', query.casefold())] = (time.monotonic(), rows)
            return rows, []
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return [], ['Pixabay search is unavailable; check PIXABAY_API_KEY and the per-minute request limit.']

    async def search(self, body):
        key = (body.query.strip().casefold(), body.provider, body.kind)
        reviewed = self.reviewed()
        wanted = topics(body.query)
        words = set(re.findall(r'\w+', body.query.casefold()))
        rows = [r for r in reviewed if (body.provider == 'all' or r['provider'] == body.provider)
                and (body.kind == 'all' or r['kind'] == body.kind)
                and (wanted & topics(' '.join(r['tags']) + ' ' + r['title']) or words & set(re.findall(r'\w+', r['title'].casefold())))]
        requested_regions = named_regions(body.query)
        if requested_regions:
            rows = [r for r in rows if set(requested_regions) & set(named_regions(r.get('location') or ''))]
        warnings = []
        if body.live:
            async with self.lock:
                cached = self.cache.get(key)
                if cached and time.monotonic() - cached[0] < (30 if cached[2] else 600):
                    found, warnings = cached[1:]
                else:
                    (found, warnings), (stocked, stock_warnings), (archived, archive_warnings) = await asyncio.gather(self.commons(body), self.stock(body), self.archive(body))
                    found = found + stocked + archived;warnings = warnings + stock_warnings + archive_warnings
                    if not found and warnings and body.provider=='all':
                        alternate, alternate_warnings=await self.nasa(body)
                        found+=alternate;warnings+=alternate_warnings
                        if alternate:warnings.append('Using NASA ISS archive footage as an alternate source; it is dated context, not current storm imagery.')
                    if len(self.cache) >= 30:
                        self.cache.pop(next(iter(self.cache)))
                    self.cache[key] = (time.monotonic(), found, warnings)
            rows += [r for r in found if not requested_regions or set(requested_regions) & set(named_regions((r.get('location') or '')+' '+r.get('title','')+' '+r.get('description','')))]
        context = None
        if body.plan_id:
            plan = self.production.store.visual_plan(body.plan_id)
            advisory = self.production.store.advisory(plan['advisory_id'])
            context = {'event_id': advisory.event_key, 'issued_date': advisory.issued_at.date().isoformat()}
        local = {m['checksum']: m for m in self.production.store.production_list('media')}
        unique = {}
        for row in rows:
            candidate = dict(row)
            preserved = self.folder / (row['id'] + '.json')
            if preserved.exists():
                recorded = json.loads(preserved.read_text())
                if recorded.get('expected_sha1') == row.get('expected_sha1') and recorded.get('checksum'):
                    candidate['checksum'] = recorded['checksum']
            reasons = ['Weather topics: ' + ', '.join(sorted(wanted & topics(' '.join(row['tags']) + ' ' + row['title'])))]
            score = len(wanted & topics(' '.join(row['tags']) + ' ' + row['title'])) * 10
            if context and row.get('event_id'):
                if row['event_id'] == context['event_id']:
                    score += 30; reasons.append('Declared event ID matches; review source attribution')
                else:
                    reasons.append('Different event; archival context only')
            if context and row.get('captured_at'):
                reasons.append('Capture date ' + ('matches' if row['captured_at'] == context['issued_date'] else 'differs from') + ' advisory date')
            candidate.update(regional_status='capture_location_review_needed' if requested_regions else 'unscoped', required_regions=requested_regions, score=score, match_reasons=reasons, local_media_id=local.get(candidate.get('checksum'), {}).get('id'))
            unique[candidate['id']] = candidate
        return {'query': body.query, 'context': context, 'results': sorted(unique.values(), key=lambda r: (-r['score'], r['id'])),
                'warnings': warnings, 'live_requested': body.live,
                'links': {'pexels': 'https://www.pexels.com/search/videos/' + quote(body.query, safe='') + '/',
                          'youtube': 'https://www.youtube.com/results?' + urlencode({'search_query': body.query + ' Creative Commons'}),
                          'commons': 'https://commons.wikimedia.org/w/index.php?' + urlencode({'search': body.query, 'title': 'Special:MediaSearch', 'type': 'video' if body.kind == 'video' else 'image'})},
                'required_regions': requested_regions, 'note': 'Regional searches exclude unrelated sample footage. A place in a search title is a candidate, not verified capture location; review its source and save capture-region evidence in Media Library. Stock results are reviewed sample sources. Live results come from Wikimedia; YouTube-origin results are licensed archive copies. Direct YouTube/Pexels search links need manual source review.'}

    async def import_candidate(self, body):
        path = self.folder / (body.candidate_id + '.json')
        if not path.exists():
            raise ValueError('Search for this candidate again before importing.')
        candidate = json.loads(path.read_text())
        url = candidate['download_url']
        archive_host = re.fullmatch(r'https://[a-z0-9]+\.us\.archive\.org/.+', url) and safe_url(url, {urlsplit(url).hostname})
        if not (archive_host or safe_url(url, {'videos.pexels.com', 'cdn.pixabay.com', 'upload.wikimedia.org', 'images-assets.nasa.gov'})):
            raise ValueError('This source does not have an approved media download URL.')
        # Reviewed bytes already in the library never need another download.
        existing = next((m for m in self.production.store.production_list('media') if m['checksum'] == candidate.get('checksum')), None)
        if existing:
            self.production.media_path(existing)
            return {**existing, 'duplicate': True}
        metadata = MediaImportMetadata(name=candidate['filename'], kind=candidate['kind'], context=candidate['context'],
            license=candidate['license'], attribution=candidate['attribution'], source=candidate['source'], rights_confirmed=True,
            source_provider=candidate['source_provider'], reuse_basis=candidate['reuse_basis'], reuse_evidence=candidate['reuse_evidence'],
            preferred_clip_seconds=candidate.get('preferred_clip_seconds', 3.5))
        sha256, sha1 = hashlib.sha256(), hashlib.sha1()
        async def chunks(response):
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError('Media downloads are limited to 250 MiB.')
                sha256.update(chunk); sha1.update(chunk)
                yield chunk
            if candidate.get('checksum') and sha256.hexdigest() != candidate['checksum']:
                raise ValueError('The reviewed source file changed; import cancelled.')
            if candidate.get('expected_sha1') and sha1.hexdigest() != candidate['expected_sha1']:
                raise ValueError('The source checksum changed; search again before importing.')
        try:
            async with self.client.stream('GET', url, timeout=120) as response:
                response.raise_for_status()
                if response.headers.get('content-length', '').isdigit() and int(response.headers['content-length']) > MAX_DOWNLOAD:
                    raise ValueError('Media downloads are limited to 250 MiB.')
                imported = await self.production.import_media(metadata, chunks(response))
        except httpx.HTTPError as error:
            raise ValueError('The media download failed. Use the source page to obtain an authorized local file.') from error
        if not imported.get('duplicate'):
            imported = self.production.catalog_media(imported['id'], MediaCatalogRequest(tags=candidate.get('tags', []),
                event_id=candidate.get('event_id') or '', location=candidate.get('location') or '',
                captured_at=candidate.get('captured_at'), reference=candidate['catalogue_url']))
        candidate['checksum'] = imported['checksum']
        self.remember(candidate)
        return imported
