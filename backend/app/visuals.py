"""Official visual evidence, bounded local caches, geographic validation and scene plans."""
import asyncio
import csv
import hashlib
import io
import json
import math
import re
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs
from uuid import uuid4
from xml.etree import ElementTree as ET
import httpx
from .intelligence import IntelligenceDesk
from .storage import now, RevisionConflict

GOES_PAGE='https://www.star.nesdis.noaa.gov/GOES/sector_band.php?sat=G19&sector=ga&band=GEOCOLOR&length=12'
GOES_BASE='https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/ga/GEOCOLOR/'
RADAR_BASE='https://nowcoast.noaa.gov/geoserver/observations/weather_radar/ows'
RADAR_EXTENT=[-126,23,-65,51]


def source_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.port is not None or p.username or p.password or p.fragment:
        raise ValueError('Visual sources require canonical official HTTPS URLs.')
    if url==GOES_PAGE:
        return url
    if p.hostname=='cdn.star.nesdis.noaa.gov' and re.fullmatch(r'/GOES19/ABI/SECTOR/ga/GEOCOLOR/\d{11}_GOES19-ABI-ga-GEOCOLOR-1000x1000.jpg',p.path) and not p.query:
        return url
    if p.hostname=='www.nhc.noaa.gov' and re.fullmatch(r'/gis/forecast/archive/[a-z]{2}\d{6}_5day_\d{3}.kmz',p.path) and not p.query:
        return url
    if p.hostname=='nowcoast.noaa.gov' and p.path==urlsplit(RADAR_BASE).path:
        params=parse_qs(p.query,keep_blank_values=True)
        keys={'service','request','version','layers','styles','format','transparent','crs','bbox','width','height','time','layer'}
        if set(params)<=keys and all(len(v)==1 for v in params.values()) and params.get('service')==['WMS']:
            return url
    raise ValueError('Visual URL is outside the official product allowlist.')


def utc_stamp(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Observation timestamps must include a timezone.')
    stamp=stamp.astimezone(timezone.utc)
    if stamp>datetime.now(timezone.utc)+timedelta(minutes=10):
        raise ValueError('Visual timestamp is in the future.')
    return stamp.isoformat()


def goes_catalogue(html):
    files=set(re.findall(r'\d{11}_GOES19-ABI-ga-GEOCOLOR-1000x1000\.jpg',html))
    result=[]
    for filename in sorted(files):
        digits=filename[:11]
        stamp=datetime.strptime(digits,'%Y%j%H%M').replace(tzinfo=timezone.utc)
        if stamp.strftime('%Y%j%H%M')!=digits:
            raise ValueError('Invalid Julian observation date in GOES product.')
        result.append({'url':GOES_BASE+filename,'observed_at':utc_stamp(stamp.isoformat())})
    if not result:
        raise ValueError('GOES page contains no recognized dated GeoColor observations.')
    return result[-12:]


def xml_document(body):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('External entities are not allowed in visual XML.')
    return ET.fromstring(body)


def valid_geometry(geometry):
    if not isinstance(geometry,dict) or geometry.get('type') not in ('Polygon','MultiPolygon'):
        raise ValueError('A polygon or multipolygon is required.')
    polygons=[geometry['coordinates']] if geometry['type']=='Polygon' else geometry['coordinates']
    if not polygons or len(polygons)>500:
        raise ValueError('Invalid geographic polygon count.')
    count=0
    for polygon in polygons:
        if not polygon:
            raise ValueError('Empty geographic polygon.')
        for ring in polygon:
            if len(ring)<4 or ring[0]!=ring[-1]:
                raise ValueError('Geographic rings must be closed and have at least four points.')
            for coordinate in ring:
                count+=1
                if len(coordinate)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in coordinate) or not -180<=coordinate[0]<=180 or not -90<=coordinate[1]<=90 or count>100_000:
                    raise ValueError('Invalid geographic coordinate or excessive geometry.')
    return geometry


def radar_catalogue(body):
    root=xml_document(body)
    for layer in root.iter():
        if layer.tag.split('}')[-1]!='Layer':
            continue
        names=[child.text for child in layer if child.tag.split('}')[-1]=='Name']
        if not names or 'reflectivity' not in names[0].lower() or not re.fullmatch(r'[A-Za-z0-9_:.-]+',names[0]):
            continue
        dimensions=[child for child in layer if child.tag.split('}')[-1] in ('Dimension','Extent') and child.attrib.get('name')=='time']
        if not dimensions or not dimensions[0].text:
            continue
        text=dimensions[0].text.strip()
        if '/' in text:
            start,end,period=text.split('/')
            match=re.fullmatch(r'PT(\d+)M',period)
            if not match:
                raise ValueError('Radar time interval is not a supported minute sequence.')
            step=int(match.group(1))
            if not 1<=step<=60:
                raise ValueError('Invalid radar observation interval.')
            first=datetime.fromisoformat(utc_stamp(start));last=datetime.fromisoformat(utc_stamp(end))
            stamps=[last-timedelta(minutes=step*n) for n in range(6) if last-timedelta(minutes=step*n)>=first]
            times=[utc_stamp(t.isoformat()) for t in reversed(stamps)]
        else:
            times=sorted({utc_stamp(t.strip()) for t in text.split(',')})[-6:]
        if not times:
            continue
        return names[0],times
    raise ValueError('Radar capabilities do not expose a timestamped reflectivity layer.')


def mercator(lon,lat):
    return [6378137*math.radians(lon),6378137*math.log(math.tan(math.pi/4+math.radians(lat)/2))]


def radar_url(layer,stamp,legend=False):
    base={'service':'WMS','version':'1.3.0'}
    if legend:
        return RADAR_BASE+'?'+urlencode({**base,'request':'GetLegendGraphic','layer':layer,'format':'image/png'})
    # nowCOAST accepts UTC Z timestamps; equivalent +00:00 offsets are rejected.
    stamp=utc_stamp(stamp).replace('+00:00','Z')
    west,south=mercator(*RADAR_EXTENT[:2]);east,north=mercator(*RADAR_EXTENT[2:])
    return RADAR_BASE+'?'+urlencode({**base,'request':'GetMap','layers':layer,'styles':'','format':'image/png','transparent':'true','crs':'EPSG:3857','bbox':','.join(str(v) for v in (west,south,east,north)),'width':'1200','height':'720','time':stamp})


def image_size(body,content_type):
    if content_type=='image/png' and body[:8]==b'\x89PNG\r\n\x1a\n' and len(body)>32:
        width,height=struct.unpack('>II',body[16:24])
    elif content_type=='image/jpeg' and body.startswith(b'\xff\xd8') and body.endswith(b'\xff\xd9'):
        offset=2; width=height=0
        while offset<len(body)-9:
            if body[offset]!=255: break
            marker=body[offset+1];offset+=2
            if marker in (0xD8,0xD9):continue
            length=int.from_bytes(body[offset:offset+2],'big')
            if marker in (0xC0,0xC1,0xC2):
                height,width=struct.unpack('>HH',body[offset+3:offset+7]);break
            if length<2:break
            offset+=length
    else:
        raise ValueError('Official image response has an unexpected format or incomplete signature.')
    if not 1<=width<=5000 or not 1<=height<=5000:
        raise ValueError('Invalid or excessive image dimensions.')
    return width,height


def forecast_geometry(body,advisory):
    if not zipfile.is_zipfile(io.BytesIO(body)):
        raise ValueError('Official forecast product is not a KMZ archive.')
    geometries=[];stamps=[]
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        if len(archive.infolist())>40 or sum(f.file_size for f in archive.infolist())>32_000_000:
            raise ValueError('KMZ exceeds archive limits.')
        for entry in archive.infolist():
            if not entry.filename.lower().endswith('.kml'):continue
            root=xml_document(archive.read(entry))
            if any(el.tag.split('}')[-1]=='NetworkLink' for el in root.iter()):
                raise ValueError('Linked KML is not supported; no external references are fetched.')
            for el in root.iter():
                if el.tag.split('}')[-1] in ('when','begin') and el.text:
                    try: stamps.append(datetime.fromisoformat(utc_stamp(el.text.strip())))
                    except ValueError: pass
            for place in root.iter():
                if place.tag.split('}')[-1]!='Placemark':continue
                text=' '.join((el.text or '') for el in place.iter() if el.tag.split('}')[-1] in ('name','description'))
                if 'cone' not in text.lower() and 'cone' not in entry.filename.lower():continue
                for polygon in place.iter():
                    if polygon.tag.split('}')[-1]!='Polygon':continue
                    rings=[]
                    for el in polygon.iter():
                        if el.tag.split('}')[-1]=='coordinates' and el.text:
                            rings.append([[float(value) for value in pair.split(',')[:2]] for pair in el.text.split()])
                    geometries.append(valid_geometry({'type':'Polygon','coordinates':rings}))
    if not geometries or not any(abs((stamp-advisory.issued_at).total_seconds())<=1800 for stamp in stamps):
        raise ValueError('Forecast cone lacks inline geometry and an issue timestamp matching the selected advisory.')
    return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{'data_class':'forecast','advisory_id':advisory.id,'issued_at':advisory.issued_at.isoformat()},'geometry':g} for g in geometries]}


class VisualEvidence:
    def __init__(self,store,transport=None):
        self.store=store
        self.client=httpx.AsyncClient(transport=transport,timeout=25,follow_redirects=False,headers={'User-Agent':'WeatherIntelligenceStudio/0.4 (official evidence)'})
        self.pending={}

    async def close(self):
        for task in self.pending.values():task.cancel()
        await asyncio.gather(*self.pending.values(),return_exceptions=True)
        await self.client.aclose()

    async def fetch(self,url):
        source_url(url)
        for attempt in range(3):
            try:
                async with self.client.stream('GET',url) as response:
                    response.raise_for_status()
                    if response.status_code!=200:raise ValueError('Visual source did not return complete content.')
                    body=bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body)>8_000_000:raise ValueError('Visual source exceeds the 8 MB response limit.')
                    return bytes(body),response.headers.get('content-type','').split(';')[0]
            except (httpx.TimeoutException,httpx.ConnectError):
                if attempt==2:raise
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in (429,500,502,503,504) or attempt==2:raise
            await asyncio.sleep(.5*2**attempt)

    async def collect(self,identity,advisory_id=None):
        key=identity+':'+(advisory_id or '')
        if key not in self.pending:
            self.pending[key]=asyncio.create_task(self._collect(identity,advisory_id))
        task=self.pending[key]
        try:return await asyncio.shield(task)
        finally:
            if task.done():self.pending.pop(key,None)

    async def _collect(self,identity,advisory_id):
        job=self.store.start_job('visual_'+identity)
        self.store.visual_source_status(identity,'collecting')
        try:
            ids=[]
            if identity=='goes':
                body,_=await self.fetch(GOES_PAGE)
                catalogue=goes_catalogue(body.decode())
                self.store.cache_response(GOES_PAGE,body.decode(),None,None)
                for frame in catalogue:
                    existing=next((asset for asset in self.store.visual_assets('goes') if asset['source_url']==frame['url']),None)
                    if existing:self.asset(existing['id']);ids.append(existing['id']);continue
                    body,mime=await self.fetch(frame['url']);size=image_size(body,mime)
                    ids.append(self.store.save_visual_asset({'kind':'goes','source_url':frame['url'],'observed_at':frame['observed_at'],'content_type':mime,'metadata':{'width':size[0],'height':size[1],'product':'GOES-19 GeoColor · Gulf/Atlantic','data_class':'observation_composite','projection':'Native NOAA image; standalone viewport, not a geographic map overlay','catalogue_url':GOES_PAGE,'attribution':'NOAA/NESDIS/STAR','note':'GeoColor includes nighttime infrared enhancement; colors are not rainfall measurements.'}},body))
            elif identity=='radar':
                body,_=await self.fetch(RADAR_BASE+'?service=WMS&request=GetCapabilities')
                layer,times=radar_catalogue(body)
                self.store.cache_response(RADAR_BASE+'?service=WMS&request=GetCapabilities',body.decode(),None,None)
                legend_url=radar_url(layer,times[-1],True)
                legend,mime=await self.fetch(legend_url);size=image_size(legend,mime)
                legend_id=self.store.save_visual_asset({'kind':'radar_legend','source_url':legend_url,'observed_at':times[-1],'content_type':mime,'metadata':{'width':size[0],'height':size[1],'attribution':'NOAA nowCOAST','label':'Source-provided reflectivity legend (dBZ)'}},legend)
                for stamp in times:
                    url=radar_url(layer,stamp)
                    existing=next((a for a in self.store.visual_assets('radar') if a['source_url']==url),None)
                    if existing:self.asset(existing['id']);ids.append(existing['id']);continue
                    body,mime=await self.fetch(url);size=image_size(body,mime)
                    ids.append(self.store.save_visual_asset({'kind':'radar','source_url':url,'observed_at':stamp,'content_type':mime,'metadata':{'width':size[0],'height':size[1],'product':layer,'data_class':'radar_observation','projection':'EPSG:3857','extent':RADAR_EXTENT,'legend_asset_id':legend_id,'attribution':'NOAA nowCOAST','note':'Reflectivity is measured in dBZ; it is not a rainfall accumulation estimate.'}},body))
            elif identity=='forecast_cone':
                advisory=self.store.advisory(advisory_id)
                number=str(advisory.facts.get('advisory_number',''))
                if advisory.provider!='NHC' or advisory.provenance!='official_fetch' or not number.isdigit() or not re.fullmatch(r'[A-Z]{2}\d{6}',advisory.event_key):
                    raise ValueError('Select an officially fetched regular NHC advisory for its forecast product.')
                url=f'https://www.nhc.noaa.gov/gis/forecast/archive/{advisory.event_key.lower()}_5day_{int(number):03}.kmz'
                body,_=await self.fetch(url);geometry=forecast_geometry(body,advisory)
                ids.append(self.store.save_visual_asset({'kind':'forecast_cone','source_url':url,'observed_at':advisory.issued_at.isoformat(),'content_type':'application/geo+json','metadata':{'geometry':geometry,'original_kmz_sha256':hashlib.sha256(body).hexdigest(),'advisory_id':advisory.id,'advisory_checksum':advisory.checksum,'data_class':'forecast','attribution':'NOAA/NHC','note':'Official forecast cone, not an observation or an impact boundary.'}},json.dumps(geometry).encode()))
            else:raise KeyError(identity)
            self.store.visual_source_status(identity,'healthy')
            self.store.finish_job(job,'succeeded',f'Cached {len(ids)} official visual records')
            return {'source':identity,'assets':ids,'collected':len(ids)}
        except (Exception,asyncio.CancelledError) as error:
            detail=str(error) if isinstance(error,ValueError) else type(error).__name__+': official visual source unavailable; cached evidence preserved'
            self.store.visual_source_status(identity,'failed',detail);self.store.finish_job(job,'failed',detail)
            raise ValueError(detail) from None

    def asset(self,identity):
        row=self.store.visual_asset(identity)
        if hashlib.sha256(row['body']).hexdigest()!=row['checksum']:
            raise ValueError('Visual asset checksum mismatch.')
        return row

    def state(self):
        assets=self.store.visual_assets()
        for asset in assets:
            asset.pop('document',None)
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(asset['observed_at'])).total_seconds()
            asset['temporal_label']='forecast' if asset['kind']=='forecast_cone' else 'source legend' if asset['kind']=='radar_legend' else 'recent observation' if age<=900 else 'archival observation'
        return {'assets':assets,'sources':self.store.visual_sources(),'plans':self.store.visual_plans(),'basemap':json.loads((Path(__file__).parent/'data/provenance.json').read_text())}

    def geography(self,advisory_id):
        desk=IntelligenceDesk(self.store.advisories(),self.store.feeds(),self.store.memberships())
        item=desk.by_id[advisory_id]
        features=[];timeline=[];omitted=[]
        for source in desk.related(item):
            if source.issued_at > item.issued_at:
                continue
            if item.provider=='NWS' and source.id!=item.id:
                continue
            if source.provider=='TRAINING' or source.provenance!='official_fetch':
                omitted.append({'id':source.id,'reason':'Only official geographic evidence is plotted.'});continue
            properties={'advisory_id':source.id,'issued_at':source.issued_at.isoformat(),'title':source.title,'source_url':source.source_url,'checksum':source.checksum,'status':desk.status(source),**source.facts}
            if source.provider=='NHC':
                point=[source.facts.get('longitude'),source.facts.get('latitude')]
                if not all(isinstance(value,(int,float)) and math.isfinite(value) for value in point) or not -180<=point[0]<=180 or not -90<=point[1]<=90:
                    omitted.append({'id':source.id,'reason':'No valid reported storm center.'});continue
                features.append({'type':'Feature','properties':{**properties,'kind':'reported_center'},'geometry':{'type':'Point','coordinates':point}})
                timeline.append({**properties,'coordinates':point})
            else:
                geometry=(source.source_payload or {}).get('geometry')
                try:valid_geometry(geometry)
                except (ValueError,KeyError,TypeError):
                    omitted.append({'id':source.id,'reason':'No valid official alert polygon; area names are not geocoded.'});continue
                features.append({'type':'Feature','properties':{**properties,'kind':'alert_area'},'geometry':geometry})
        # Connecting lines are advisory-to-advisory visual guides, not continuous measured tracks.
        for earlier,later in zip(timeline,timeline[1:]):
            if abs(earlier['coordinates'][0]-later['coordinates'][0])<=180:
                features.append({'type':'Feature','properties':{'kind':'reported_track','data_class':'advisory_connector'},'geometry':{'type':'LineString','coordinates':[earlier['coordinates'],later['coordinates']]}})
        for asset in self.store.visual_assets('forecast_cone'):
            metadata=asset['metadata']
            if metadata['advisory_id']==item.id and metadata['advisory_checksum']==item.checksum:
                validated=json.loads(self.asset(asset['id'])['body'])
                for feature in validated['features']:
                    features.append({**feature,'properties':{**feature['properties'],'kind':'forecast_cone','source_url':asset['source_url'],'status':desk.status(item)}})
        return {'advisory':desk.describe(item),'geojson':{'type':'FeatureCollection','features':features},'timeline':timeline,'omitted':omitted,'note':'Reported centers and original alert polygons. Lines connect advisories; no inferred track, cone, impact area or rainfall.'}

    def plan(self,script,style):
        geography=self.geography(script['advisory_id'])
        features=geography['geojson']['features'];kinds={f['properties']['kind'] for f in features}
        assets=self.state()['assets'];scenes=[];asset_ids=set()
        for index,claim in enumerate(script['claims']):
            kind='lower_third';parameters={};fallback='Source attribution card with advisory issue time'
            if index==0:kind='news_intro'
            elif 'Compared with' in claim['text']:kind='what_changed';parameters={'changes':geography['advisory']['changes'],'comparison':geography['advisory']['comparison']}
            elif 'reported_center' in kinds and ('latitude' in claim['text'] or 'location' in claim['text'].lower()):
                kind='storm_track';parameters={'geojson':geography['geojson'],'timeline':geography['timeline']}
            elif 'alert_area' in kinds and index==1:kind='cinematic_weather_map';parameters={'geojson':geography['geojson']}
            if style in ('satellite','radar') and index==1:
                selected=[a for a in reversed(assets) if a['kind']==('goes' if style=='satellite' else 'radar')]
                # Spatial observations are contextual only; require issue-time proximity and never claim attribution.
                selected=[a for a in selected if abs((datetime.fromisoformat(a['observed_at'])-datetime.fromisoformat(script['source_issued_at'])).total_seconds())<=3600]
                if style=='satellite':
                    point=next((f['geometry']['coordinates'] for f in features if f['properties']['kind']=='reported_center' and f['properties'].get('advisory_id')==script['advisory_id']),None)
                    if point is None or not (-100<=point[0]<=-65 and 5<=point[1]<=40):selected=[]
                elif not any(f['properties']['kind']=='alert_area' for f in features):
                    selected=[]
                if selected and script['label']=='current':
                    kind='satellite_timelapse' if style=='satellite' else 'radar_animation'
                    parameters={'asset_ids':[a['id'] for a in selected],'observation_times':[a['observed_at'] for a in selected],'note':'Regional observation context; not a claim of event attribution. Satellite scene selection uses an editorial Gulf/Atlantic region filter, not pixel geolocation.'}
                    asset_ids.update(parameters['asset_ids'])
                else:parameters={'unavailable_requested_layer':style,'reason':'No cached observations close to this script issue time; retain source card fallback.'}
            scenes.append({'id':f'scene-{index+1}','type':kind,'script_segment':claim['text'],'claim_id':claim['id'],'target_seconds':round(len(claim['text'].split())/145*60,1),'asset_type':kind,'visual_instructions':'Preserve source, timestamps, uncertainty and evidence label; restrained camera movement.','parameters':parameters,'source_refs':script['source_refs'],'advisory_timestamp':script['source_issued_at'],'camera_movement':'ease_to_region' if kind in ('storm_track','cinematic_weather_map') else 'slow_push' if kind=='satellite_timelapse' else 'none','transition':'dissolve','fallback_asset':fallback,'voiceover_alignment':None,'timing_basis':'145 words/minute estimate; audio not generated'})
        document={'id':str(uuid4()),'script_id':script['id'],'script_revision':script['revision'],'script_text_checksum':hashlib.sha256(script['text'].encode()).hexdigest(),'advisory_id':script['advisory_id'],'source_label':script['label'],'evidence_manifest':script['evidence_manifest'],'created_at':now(),'scenes':scenes,'asset_ids':sorted(asset_ids),'broadcast_eligible':False,'rendered':False,'review_valid_at_creation':script['review_valid'],'estimated_seconds':sum(s['target_seconds'] for s in scenes)}
        self.store.save_visual_plan(document)
        return document

    def import_scenes(self,plan,csv_text):
        allowed={'news_intro','lower_third','storm_track','cinematic_weather_map','what_changed','weather_stat','weather_timeline','satellite_timelapse','radar_animation','forecast_cone'}
        rows=list(csv.DictReader(io.StringIO(csv_text)))
        if len(rows)!=len(plan['scenes']):raise ValueError('Scene CSV must preserve every source-linked script segment.')
        result=json.loads(json.dumps(plan));by_id={s['id']:s for s in plan['scenes']}
        if len({row.get('id') for row in rows})!=len(rows):raise ValueError('Duplicate scene IDs.')
        for row in rows:
            source=by_id.get(row.get('id'))
            if not source or row.get('script_segment')!=source['script_segment'] or row.get('claim_id')!=source['claim_id'] or row.get('type') not in allowed:
                raise ValueError('CSV import cannot change narration, claims, or invent a scene type.')
            # Only presentation controls are editable; source, narration and timing stay intact.
            if set(row)!=set(source):raise ValueError('CSV columns must match the original plan contract.')
            for key in set(source)-{'camera_movement','transition'}:
                value=source[key]
                expected=json.dumps(value) if isinstance(value,(dict,list)) else '' if value is None else str(value)
                if expected.lstrip().startswith(('=','+','-','@')):expected="'"+expected
                if row.get(key)!=expected:raise ValueError('CSV import cannot replace source evidence or requested weather layers.')
            if row.get('camera_movement') not in ('none','ease_to_region','slow_push') or row.get('transition') not in ('cut','dissolve'):
                raise ValueError('Unsupported camera movement or transition.')
            source_copy=next(s for s in result['scenes'] if s['id']==source['id'])
            source_copy.update(camera_movement=row['camera_movement'],transition=row['transition'])
        result.update(id=str(uuid4()),parent_plan_id=plan['id'],created_at=now())
        self.store.save_visual_plan(result)
        return result
