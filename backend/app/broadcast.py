"""Deterministic, source-bound broadcast scenes. No generative weather or speech.

Native loops retain their source timestamp/legend strip. Geographic layers are
projected separately; a native image is never assumed to be a georeferenced tile.
"""
import asyncio
import hashlib
import io
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator

SIZE = (1920, 1080)
CAMERAS = ('smooth_zoom_in', 'smooth_zoom_out', 'geographic_pan', 'storm_follow',
           'camera_drift', 'region_focus', 'satellite_to_map', 'map_to_footage')


class Camera(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    movement: Literal['smooth_zoom_in', 'smooth_zoom_out', 'geographic_pan', 'storm_follow', 'camera_drift', 'region_focus', 'satellite_to_map', 'map_to_footage'] = 'camera_drift'
    easing: Literal['linear', 'smoothstep', 'cubic'] = 'smoothstep'
    start_zoom: float = Field(default=1, ge=1, le=3)
    end_zoom: float = Field(default=1.12, ge=1, le=3)
    start_center: tuple[float, float] = (.5, .5)
    end_center: tuple[float, float] = (.5, .5)
    geographic_target: tuple[float, float] | None = None

    @model_validator(mode='after')
    def ranges(self):
        if any(not 0 <= n <= 1 for point in (self.start_center, self.end_center) for n in point):
            raise ValueError('Native camera centers must be normalized source coordinates.')
        if self.geographic_target and not (-180 <= self.geographic_target[0] <= 180 and -85 <= self.geographic_target[1] <= 85):
            raise ValueError('Camera target must be a valid longitude/latitude.')
        if self.movement == 'storm_follow' and not self.geographic_target:
            raise ValueError('Storm follow requires a verified geographic target.')
        return self


class VisualSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_url: str
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    event_id: str
    data_type: Literal['satellite_observation', 'radar_reflectivity', 'reported_center', 'forecast', 'archival_footage', 'historical_analysis']
    historical: bool
    observation_start: datetime
    observation_end: datetime
    advisory_issue_time: datetime | None = None
    forecast_valid_time: datetime | None = None
    coverage: str
    projection: str
    attribution: str
    license: str
    catalogue_url: str
    time_precision: Literal['exact', 'source_embedded', 'day'] = 'exact'
    observation_times: list[datetime] = Field(default_factory=list)

    @model_validator(mode='after')
    def chronological(self):
        dates = [self.observation_start, self.observation_end, self.advisory_issue_time, self.forecast_valid_time]
        if any(d is not None and (d.tzinfo is None or d.utcoffset() is None) for d in dates):
            raise ValueError('Visual timestamps require a timezone.')
        if any(d.tzinfo is None or d.utcoffset() is None for d in self.observation_times):
            raise ValueError('Sequence timestamps require a timezone.')
        if any(a>b for a,b in zip(self.observation_times,self.observation_times[1:])):
            raise ValueError('Observation frame chronology is reversed.')
        if any(not self.observation_start<=d<=self.observation_end for d in self.observation_times):
            raise ValueError('Sequence timestamp is outside the source observation window.')
        if self.observation_end < self.observation_start:
            raise ValueError('Source observation chronology is reversed.')
        if self.event_id.startswith(('AL', 'EP')) and self.event_id[-4:].isdigit():
            if any(d.year != int(self.event_id[-4:]) for d in dates if d):
                raise ValueError('Event year and visual timestamp do not match.')
        if self.data_type == 'forecast' and (not self.advisory_issue_time or not self.forecast_valid_time):
            raise ValueError('Forecast layers require issue and valid times.')
        if self.data_type == 'forecast' and self.forecast_valid_time < self.advisory_issue_time:
            raise ValueError('Forecast valid time predates issue time.')
        return self


class SceneDirection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    scene_type: Literal['satellite_wide', 'satellite_timelapse', 'storm_track', 'statistics', 'ground_footage', 'radar_animation', 'region_focus']
    event_id: str
    duration: float = Field(ge=1, le=120)
    headline: str = Field(max_length=100)
    camera: Camera = Field(default_factory=Camera)
    layers: list[Literal['satellite', 'radar', 'reported_track', 'forecast_cone', 'statistics', 'ground']] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    sources: list[VisualSource] = Field(default_factory=list)
    transition_out: Literal['dissolve', 'satellite_to_map', 'map_to_footage', 'radar_to_satellite', 'track_to_stats', 'region_closeup', 'stats_to_footage'] = 'dissolve'
    fallback: str | None = None
    max_words: int = Field(default=8, ge=1, le=12)

    @model_validator(mode='after')
    def integrity(self):
        if len(self.headline.split()) > self.max_words:
            raise ValueError('Broadcast headlines exceed the on-screen word budget.')
        if any(s.event_id != self.event_id for s in self.sources):
            raise ValueError('Unrelated event imagery cannot accompany storm claims.')
        if len({s.historical for s in self.sources}) > 1:
            raise ValueError('Historical and current observations cannot be merged.')
        observations=[s for s in self.sources if s.data_type in ('satellite_observation','radar_reflectivity')]
        if any(a.observation_start>b.observation_start for a,b in zip(observations,observations[1:])):
            raise ValueError('Observation sources must be ordered chronologically.')
        if len({(s.projection,s.coverage) for s in observations})>1:
            raise ValueError('Observation sequence viewports are not aligned.')
        if 'forecast_cone' in self.layers and not any(s.data_type=='forecast' for s in self.sources):
            raise ValueError('Forecast cone requires source issue/valid times and geometry.')
        required = {'satellite_wide': 'satellite_observation', 'satellite_timelapse': 'satellite_observation',
                    'radar_animation': 'radar_reflectivity', 'ground_footage': 'archival_footage'}
        if self.scene_type in required and not any(s.data_type == required[self.scene_type] for s in self.sources) and not self.fallback:
            raise ValueError('Missing verified source: choose a labeled fallback.')
        if self.camera.movement == 'storm_follow' and self.scene_type.startswith('satellite') and any(s.projection == 'native_viewport' for s in self.sources):
            raise ValueError('Native satellite imagery lacks geolocation for a geographic tracking camera.')
        return self


def easing(t, mode='smoothstep'):
    t = min(1, max(0, t))
    return t if mode == 'linear' else 1 - (1-t)**3 if mode == 'cubic' else t*t*(3-2*t)


def camera_pose(camera, t):
    camera = camera if isinstance(camera, Camera) else Camera.model_validate(camera)
    u = easing(t, camera.easing)
    z = camera.start_zoom + (camera.end_zoom-camera.start_zoom)*u
    x, y = [a+(b-a)*u for a,b in zip(camera.start_center, camera.end_center)]
    if camera.movement == 'camera_drift':
        x += .012*math.sin(math.pi*t)
        y -= .008*math.sin(math.pi*t)
    return z, x, y


def project(lon, lat):
    """Web Mercator world coordinates; all map overlays use the same projection."""
    lat = max(-85, min(85, lat))
    return (lon+180)/360, (1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2


def fit_bounds(bounds):
    west,south,east,north=bounds
    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        raise ValueError('Invalid geographic viewport bounds.')
    x0,y0=project(west,north);x1,y1=project(east,south)
    width=max(x1-x0,(y1-y0)*1920/1080)
    height=max(y1-y0,width*1080/1920)
    cx=(x0+x1)/2;cy=(y0+y1)/2
    def latitude(y):return math.degrees(math.atan(math.sinh(math.pi*(1-2*y))))
    return (max(-180,(cx-width/2)*360-180),latitude(cy+height/2),
            min(180,(cx+width/2)*360-180),latitude(cy-height/2))


def register_raster(image, source_extent, viewport):
    """Crop a Web-Mercator WMS raster using the same projected map coordinates."""
    west,south,east,north=source_extent
    x0,y0=project(west,north);x1,y1=project(east,south)
    vx0,vy0=project(viewport[0],viewport[3]);vx1,vy1=project(viewport[2],viewport[1])
    box=((vx0-x0)/(x1-x0)*image.width,(vy0-y0)/(y1-y0)*image.height,
         (vx1-x0)/(x1-x0)*image.width,(vy1-y0)/(y1-y0)*image.height)
    return image.convert('RGBA').transform(SIZE,Image.Transform.EXTENT,box,Image.Resampling.BILINEAR)


def map_point(coord, bounds, size=SIZE):
    west, south, east, north = bounds
    x0,y0 = project(west,north); x1,y1 = project(east,south)
    x,y = project(*coord)
    return (x-x0)/(x1-x0)*size[0], (y-y0)/(y1-y0)*size[1]


@lru_cache(maxsize=16)
def map_base(bounds):
    image = Image.new('RGB', SIZE, '#081d2c'); d = ImageDraw.Draw(image)
    data = json.loads((Path(__file__).parent/'data/countries.geojson').read_text())
    for f in data['features']:
        g = f['geometry']; polygons = g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]
        for poly in polygons:
            pts = [map_point(c,bounds) for c in poly[0]]
            d.polygon(pts, fill='#193b47', outline='#57808a')
            for hole in poly[1:]:d.polygon([map_point(c,bounds) for c in hole],fill='#081d2c')
    for lon in range(-180,181,2):
        x,_ = map_point((lon,0),bounds);d.line((x,0,x,1080),fill='#14313e',width=1)
    for lat in range(-80,81,2):
        _,y = map_point((0,lat),bounds);d.line((0,y,1920,y),fill='#14313e',width=1)
    return image


@lru_cache(maxsize=24)
def font(size):
    # macOS font is optional; bundled Pillow default is portable and deterministic.
    p=Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    return ImageFont.truetype(str(p),size) if p.exists() else ImageFont.load_default(size=size)


def label(draw, xy, text, size=26, color='#ecf6fa'):
    draw.text(xy,text,font=font(size),fill=color)


def statistics(draw, changes, t):
    """Only supplied measured endpoints appear; animation reveals bars, not fake readings."""
    label(draw,(105,235),'WHAT CHANGED?',42,'#65e1d1')
    templates = {'wind_mph':('SUSTAINED WIND','mph'), 'pressure_mb':('CENTRAL PRESSURE','mb'),
                 'rainfall_inches':('MEASURED RAINFALL','in'), 'temperature_c':('TEMPERATURE','°C'),
                 'category':('REPORTED CATEGORY',''), 'warnings':('SOURCE WARNING','')}
    for index,c in enumerate(changes[:2]):
        if c['field'] not in templates:continue
        x = 105+index*910; title,unit = templates[c['field']]
        draw.rounded_rectangle((x,340,x+805,780),radius=20,fill='#0d2937',outline='#365666',width=2)
        label(draw,(x+40,380),title,28,'#9dbbc6')
        label(draw,(x+40,460),' '.join(str(c['previous']).split()[:6]),96 if isinstance(c['previous'],(int,float)) else 30,'#9dbbc6')
        label(draw,(x+355,490),'→',60,'#65e1d1')
        label(draw,(x+465,460),' '.join(str(c['current']).split()[:6]),96 if isinstance(c['current'],(int,float)) else 30)
        label(draw,(x+630,565),unit,28,'#65e1d1')
        for row,value in enumerate((c['previous'],c['current'])):
            if isinstance(value,(int,float)):
                scale=max(abs(c['previous']),abs(c['current']),1)
                width=abs(value)/scale*705*easing(min(1,t*2))
                y=665+row*43;draw.rounded_rectangle((x+40,y,x+40+max(1,width),y+16),radius=7,fill='#67818d' if row==0 else '#65e1d1')
        label(draw,(x+40,735),c.get('time_label','Two source measurements'),20,'#9dbbc6')


def director(scene, event_id, seconds, facts=None, source=None):
    """Local semantic director. Forecast paragraphs become geographic source layers."""
    p=scene.get('parameters',{}); typ=scene['type']
    features=p.get('geojson',{}).get('features',[])
    has_track=any(f.get('properties',{}).get('kind')=='reported_center' for f in features)
    has_warning=any(f.get('properties',{}).get('kind')=='alert_area' for f in features)
    kind='statistics' if typ=='what_changed' else 'storm_track' if has_track else 'region_focus'
    title=scene.get('story_headline') or ('WHAT CHANGED?' if kind=='statistics' else 'REPORTED STORM TRACK' if kind=='storm_track' else 'SOURCE WARNING AREA' if has_warning else 'SOURCE REGION')
    fallback = None if kind!='region_focus' or has_warning else 'No event-linked observation asset; reported geography only.'
    if kind=='statistics' and not p.get('changes'):
        fallback='No previous source measurement; current values only.'
    return SceneDirection(scene_type=kind,event_id=event_id,duration=seconds,headline=title,
                          layers=['statistics'] if kind=='statistics' else ['reported_track'],
                          camera=Camera(movement='region_focus',end_zoom=1.06),sources=[source] if source else [],fallback=fallback,
                          transition_out='track_to_stats' if kind=='storm_track' else 'dissolve').model_dump(mode='json')


class Composer:
    def __init__(self,direction,parameters,load_asset=None):
        self.direction=SceneDirection.model_validate(direction)
        self.parameters=parameters
        self.sources=[]
        self.legend=None
        self.load_asset=load_asset
        bounds=parameters.get('bounds')
        if bounds is None:
            coords=[]
            def collect(value):
                if len(value)>=2 and isinstance(value[0],(int,float)):
                    coords.append(value[:2])
                else:
                    for child in value: collect(child)
            for f in parameters.get('geojson',{}).get('features',[]): collect(f['geometry']['coordinates'])
            bounds=[max(-179,min(c[0] for c in coords)-8),max(-80,min(c[1] for c in coords)-6),min(179,max(c[0] for c in coords)+8),min(80,max(c[1] for c in coords)+6)] if coords else [-85,27,-72,38]
        self.bounds=fit_bounds(tuple(bounds))
        self.records=parameters.get('records',[])
        if not self.records:
            for f in parameters.get('geojson',{}).get('features',[]):
                if f['geometry']['type']=='Point':
                    self.records.append({**f['properties'],'coordinates':f['geometry']['coordinates']})
        self.records.sort(key=lambda r:r.get('issued_at',''))
        if self.direction.camera.geographic_target and not any(tuple(r['coordinates'])==self.direction.camera.geographic_target for r in self.records):
            raise ValueError('Tracking camera target is not a source-reported position.')
        for identity in self.direction.asset_ids:
            raw=load_asset(identity)
            source=next((s for s in self.direction.sources if s.checksum==hashlib.sha256(raw).hexdigest()),None)
            if source is None:raise ValueError('Asset checksum does not match the scene source manifest.')
            im=Image.open(io.BytesIO(raw))
            if im.width*im.height*getattr(im,'n_frames',1)>90_000_000 or getattr(im,'n_frames',1)>600:raise ValueError('Observation animation exceeds decoded limits.')
            if source.observation_times and len(source.observation_times)!=getattr(im,'n_frames',1):
                raise ValueError('Source timestamp count does not match decoded observation frames.')
            # Keep source frame order, including original timestamp and color legend.
            frames=[]
            for n in range(getattr(im,'n_frames',1)):
                im.seek(n);frames.append(im.convert('RGB').copy())
            self.sources.extend(frames)
        if parameters.get('map_legend'):
            legend=parameters['map_legend'];raw=load_asset(legend['id'])
            if hashlib.sha256(raw).hexdigest()!=legend['checksum']:raise ValueError('Radar legend checksum mismatch.')
            self.legend=Image.open(io.BytesIO(raw)).convert('RGB')
        if self.direction.scene_type in ('satellite_timelapse','radar_animation') and not self.direction.fallback and len(self.sources)<2:
            raise ValueError('A time-lapse requires at least two genuine source frames.')

    def frame(self,t):
        sd=self.direction; p=self.parameters
        z,x,y=camera_pose(sd.camera,t)
        if self.sources:
            i=0 if sd.scene_type=='satellite_wide' else min(len(self.sources)-1,int(t*len(self.sources)))
            src=self.sources[i]
            # Native images are presentation viewports. No pixel-to-lat/lon assumption.
            if p.get('radar_extent'):
                if any(s.projection != 'EPSG:3857' for s in sd.sources if s.data_type == 'radar_reflectivity'):
                    raise ValueError('Map-registered radar requires Web Mercator source metadata.')
                raster=register_raster(src,p['radar_extent'],self.bounds)
                src=Image.alpha_composite(map_base(self.bounds).convert('RGBA'),raster).convert('RGB')
            crop=p.get('native_crop');main=src.crop(tuple(crop)) if crop else src
            main=ImageOps.fit(main,SIZE,centering=(x,y))
            w,h=1920/z,1080/z;cx=max(w/2,min(1920-w/2,x*1920));cy=max(h/2,min(1080-h/2,y*1080))
            image=main.crop((int(cx-w/2),int(cy-h/2),int(cx+w/2),int(cy+h/2))).resize(SIZE,Image.Resampling.BILINEAR)
            if p.get('source_strip'):
                strip=src.crop(tuple(p['source_strip']));strip=ImageOps.contain(strip,tuple(p.get('strip_size',[830,150])))
                image.paste(strip,(1920-strip.width-45,1080-strip.height-128))
        else:
            image=map_base(self.bounds).copy(); d=ImageDraw.Draw(image)
            for region in p.get('regional_boundaries',[]):
                for ring in region['rings']:
                    d.line([map_point(c,self.bounds) for c in ring],fill='#7ab8bd',width=3)
            if p.get('regional_title'):
                label(d,(60,220),p['regional_title'].upper()+' / REGIONAL CONTEXT',30,'#82efdc')
            for feature in p.get('geojson',{}).get('features',[]):
                geometry=feature['geometry'];kind=feature.get('properties',{}).get('kind')
                if geometry['type'] not in ('Polygon','MultiPolygon') or kind not in ('alert_area','forecast_cone'):continue
                if kind=='forecast_cone' and 'forecast_cone' not in sd.layers:continue
                polygons=geometry['coordinates'] if geometry['type']=='MultiPolygon' else [geometry['coordinates']]
                for polygon in polygons:
                    points=[map_point(c,self.bounds) for c in polygon[0]]
                    d.line(points,fill='#cab7e4' if kind=='forecast_cone' else '#ffc887',width=4)
            if p.get('map_mode'):
                from .map_graphics import geometry
                geometry(image,p,self.bounds,t)
                d=ImageDraw.Draw(image)
            if self.records and p.get('map_mode') not in ('warnings','radar'):
                count=max(1,min(len(self.records),1+int(t*len(self.records))))
                pts=[map_point(r['coordinates'],self.bounds) for r in self.records[:count]]
                if len(pts)>1:d.line(pts,fill='#65e1d1',width=7)
                for j,(px,py) in enumerate(pts):
                    d.ellipse((px-10,py-10,px+10,py+10),fill='#f2f8fa',outline='#071d29',width=3)
                px,py=pts[-1];r=18+5*math.sin(t*math.pi*4);d.ellipse((px-r,py-r,px+r,py+r),outline='#65e1d1',width=3)
                label(d,(px+25,py+20),self.records[count-1].get('issued_at','')[:16].replace('T',' ')+' UTC',24)
            for name,coord in p.get('places',[]):
                px,py=map_point(coord,self.bounds);label(d,(px,py),name,26,'#bdd3dc')
        if not self.sources and sd.scene_type != 'statistics':
            if sd.camera.geographic_target:
                tx,ty=map_point(sd.camera.geographic_target,self.bounds)
                u=easing(t,sd.camera.easing);x=.5+(tx/1920-.5)*u;y=.5+(ty/1080-.5)*u
            w,h=1920/z,1080/z;cx=max(w/2,min(1920-w/2,x*1920));cy=max(h/2,min(1080-h/2,y*1080))
            image=image.crop((int(cx-w/2),int(cy-h/2),int(cx+w/2),int(cy+h/2))).resize(SIZE,Image.Resampling.BILINEAR)
        d=ImageDraw.Draw(image)
        if sd.scene_type=='statistics' and not p.get('report_graphs'):
            d.rectangle((0,0,1920,1080),fill='#081d2c')
            changes=p.get('changes',[])
            if not changes:
                changes=[{'field':k,'previous':v,'current':v,'time_label':'Current source only; no comparison'} for k,v in p.get('facts',{}).items() if k in ('wind_mph','pressure_mb')]
            statistics(d,changes,t)
        if p.get('graphic_style'):
            from .graphic_styles import draw as draw_graphic
            draw_graphic(image,p['graphic_style'],p['graphic_data'],t)
            d=ImageDraw.Draw(image)
        if p.get('report_graphs'):
            from .report_graphs import draw as draw_report_graphs
            draw_report_graphs(image,p['report_graphs'],t)
            d=ImageDraw.Draw(image)
        d.rectangle((0,0,1920,82),fill='#061724')
        label(d,(52,27),'WEATHER INTELLIGENCE',25)
        label(d,(1370,29),('ARCHIVED WARNING' if all(s.historical for s in sd.sources) else 'SOURCE WARNING') if sd.event_id.startswith('urn:') else sd.event_id[:28]+' / SOURCE RECORD',23,'#65e1d1')
        if p.get('location_label') and not p.get('report_graphs'):
            label(d,(55,890),p['location_label'][:95],26,'#82efdc')
        # A narrow lower third leaves imagery dominant; full prose remains in the SRT.
        d.rectangle((0,970,1920,1080),fill='#061724')
        label(d,(55,988),sd.headline,34)
        source=p.get('credit','NOAA / NHC · Natural Earth cartography')
        label(d,(55,1040),source[:140],21,'#a8c4d0')
        if self.sources and p.get('map_observations') and sd.scene_type=='satellite_timelapse':
            stamp=p['map_observations'][i]['observed_at']
            d.rectangle((1170,95,1880,164),fill='#061724')
            label(d,(1190,115),'OBSERVED '+datetime.fromisoformat(stamp).strftime('%d %b %Y / %H:%M UTC'),26,'#65e1d1')
        if sd.fallback:
            d.rounded_rectangle((55,123,1025,215),radius=10,fill='#0c2431')
            label(d,(80,143),'LABELED FALLBACK',23,'#ffc887')
            label(d,(80,180),p.get('fallback_label','Verified source imagery unavailable'),22)
        if p.get('map_mode'):
            from .map_graphics import hud
            hud(d,p,t)
            if self.legend:
                legend=ImageOps.contain(self.legend,(680,270));image.paste(legend,(1170,510))
        if p.get('story'):
            story_caption(d,p['story'],t)
        return image


def story_caption(draw, story, t=1, footage=False):
    import textwrap
    # Editorial progress indicates scene playback, never a weather measurement.
    y=135 if footage else 820
    lines=textwrap.wrap(story['text'],width=82)[:4]
    height=48+len(lines)*34
    draw.rectangle((45,y,1875,y+height),fill='#061724')
    label(draw,(65,y+10),story['beat'].upper()+' · '+story.get('source_label','source record').upper(),22,'#65e1d1')
    for i,line in enumerate(lines): label(draw,(65,y+43+i*34),line,30)
    draw.rectangle((45,y+height,45+max(1,1830*min(1,max(0,t))),y+height+4),fill='#65e1d1')


@lru_cache(maxsize=2)
def encoder_args(preference='software'):
    if preference=='auto':
        try:
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=320x180:r=30:d=0.04',
                            '-frames:v','1','-c:v','h264_videotoolbox','-allow_sw','0','-f','null','-'],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,check=True)
            return ['-c:v','h264_videotoolbox','-b:v','8M']
        except (OSError,subprocess.SubprocessError):pass
    return ['-c:v','libx264','-preset','veryfast','-crf','20']


async def render_clip(direction, parameters, output, load_asset=None, seconds=None, on_progress=None):
    """Stream RGB to FFmpeg; no unbounded PNG frame cache and no network at render time."""
    composer=await asyncio.to_thread(Composer,direction,parameters,load_asset)
    seconds=seconds or composer.direction.duration
    count=round(seconds*30)
    log=Path(output).with_suffix('.log')
    with log.open('wb') as errors:
        process=await asyncio.create_subprocess_exec('ffmpeg','-y','-hide_banner','-loglevel','warning','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0','-an','-frames:v',str(count),*encoder_args(os.environ.get('WETHA_VIDEO_ENCODER','software')),'-pix_fmt','yuv420p','-threads','2',str(output),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=errors)
        try:
            for i in range(count):
                frame=await asyncio.to_thread(composer.frame,i/max(1,count-1))
                process.stdin.write(frame.tobytes());await process.stdin.drain()
                if on_progress and ((i+1) % 30 == 0 or i+1 == count):
                    on_progress((i+1)/count)
            process.stdin.close();await asyncio.wait_for(process.wait(),120)
            if process.returncode:raise ValueError('Broadcast encoding failed; inspect scene log.')
        finally:
            if process.returncode is None:
                process.terminate()
                try:await asyncio.wait_for(process.wait(),5)
                except asyncio.TimeoutError:process.kill();await process.wait()


def dissolve_filter(durations, overlap=.3, overlaps=None):
    """Inputs after the first include an overlap handle; output retains nominal duration."""
    parts=[];last='0:v';cursor=durations[0]
    for i,duration in enumerate(durations[1:],1):
        handle=overlaps[i-1] if overlaps is not None else overlap
        out=f'transition{i}'
        if handle:
            parts.append(f'[{last}][{i}:v]xfade=transition=fade:duration={handle}:offset={cursor-handle:.6f}[{out}]')
        else:
            parts.append(f'[{last}][{i}:v]concat=n=2:v=1:a=0[{out}]')
        last=out;cursor+=duration-handle
    return ';'.join(parts),f'[{last}]',cursor
