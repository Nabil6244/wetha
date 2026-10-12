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


MIN_VIEW = (8.0, 4.5)  # Smallest default story view in degrees (longitude, latitude): about one state.


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


@lru_cache(maxsize=16)
def state_lines(bounds):
    """Transparent overlay of the bundled Census state outlines inside a viewport."""
    from .regional import catalogue
    image=Image.new('RGBA',SIZE,(0,0,0,0));d=ImageDraw.Draw(image)
    for region in catalogue()['regions']:
        b=region['bounds']
        if b[2]<bounds[0] or b[0]>bounds[2] or b[3]<bounds[1] or b[1]>bounds[3]:continue
        for ring in region['rings']:
            d.line([map_point(c,bounds) for c in ring],fill=(236,246,250,190),width=2)
    return image


@lru_cache(maxsize=16)
def map_context(bounds, names=True):
    """Base map with state outlines and names, so a small warning area is always seen inside its state. Views that label
    their own counties or places take the outlines without names, so no two labels are drawn over each other."""
    from .regional import catalogue
    image=map_base(bounds).copy();lines=state_lines(bounds);image.paste(lines,(0,0),lines);d=ImageDraw.Draw(image)
    if not names:
        return image
    width=bounds[2]-bounds[0]
    for region in catalogue()['regions']:
        b=region['bounds'];west,south,east,north=max(b[0],bounds[0]),max(b[1],bounds[1]),min(b[2],bounds[2]),min(b[3],bounds[3])
        if east-west<width*.12 or north<=south:continue  # Too little of the state in view to name it legibly.
        x,y=map_point(((west+east)/2,(south+north)/2),bounds)
        text=region['name'].upper();w=d.textlength(text,font=font(30))
        d.text((max(20,min(1900-w,x-w/2)),max(110,min(900,y-15))),text,font=font(30),fill=(150,196,204))
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
        self.chrome=None
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
            if not coords:
                # Zone-based alerts (winter, wind, marine) carry no polygon; frame the story's own zone or county outlines.
                for shape in parameters.get('county_shapes') or []: collect(shape['geometry']['coordinates'])
            if coords:
                # Margin proportional to the story's size, but never narrower than a state: a county or burn-scar
                # warning stays readable inside its state's outline instead of filling the frame with blank land.
                west,east=min(c[0] for c in coords),max(c[0] for c in coords);south,north=min(c[1] for c in coords),max(c[1] for c in coords)
                dx=max(1.6,(east-west)*.6,(MIN_VIEW[0]-(east-west))/2);dy=max(1.0,(north-south)*.6,(MIN_VIEW[1]-(north-south))/2)
                bounds=[max(-179,west-dx),max(-80,south-dy),min(179,east+dx),min(80,north+dy)]
            else:
                bounds=[-85,27,-72,38]
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
            # Map-registered radar keeps its transparency so the basemap shows where there is no echo.
            frames=[];mode='RGBA' if parameters.get('radar_extent') else 'RGB'
            for n in range(getattr(im,'n_frames',1)):
                im.seek(n);frames.append(im.convert(mode).copy())
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
        if p.get('visual_state') in FULL_CARDS or p.get('graphic_style'):
            # The card covers the whole picture between header and lower third; no map is drawn beneath it.
            image=Image.new('RGB',SIZE,'#081d2c')
        elif self.sources:
            i=0 if sd.scene_type=='satellite_wide' else min(len(self.sources)-1,int(t*len(self.sources)))
            src=self.sources[i]
            # Native images are presentation viewports. No pixel-to-lat/lon assumption.
            if p.get('radar_extent'):
                if any(s.projection != 'EPSG:3857' for s in sd.sources if s.data_type == 'radar_reflectivity'):
                    raise ValueError('Map-registered radar requires Web Mercator source metadata.')
                raster=register_raster(src,p['radar_extent'],self.bounds)
                # State lines go over the echo so the place stays readable under widespread rain.
                src=Image.alpha_composite(Image.alpha_composite(map_base(self.bounds).convert('RGBA'),raster),state_lines(self.bounds)).convert('RGB')
            crop=p.get('native_crop');main=src.crop(tuple(crop)) if crop else src
            main=ImageOps.fit(main,SIZE,centering=(x,y))
            w,h=1920/z,1080/z;cx=max(w/2,min(1920-w/2,x*1920));cy=max(h/2,min(1080-h/2,y*1080))
            image=main.crop((int(cx-w/2),int(cy-h/2),int(cx+w/2),int(cy+h/2))).resize(SIZE,Image.Resampling.BILINEAR)
            if p.get('source_strip'):
                strip=src.crop(tuple(p['source_strip']));strip=ImageOps.contain(strip,tuple(p.get('strip_size',[830,150])))
                image.paste(strip,(1920-strip.width-45,1080-strip.height-128))
        else:
            image=map_context(self.bounds,p.get('visual_state') not in ('county_focus','place_focus')).copy(); d=ImageDraw.Draw(image)
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
            if p.get('visual_state')!='county_focus' and not any(f['geometry']['type'] in ('Polygon','MultiPolygon') for f in p.get('geojson',{}).get('features',[])):
                # Without an alert polygon, the warned area is the story's own zone/county outlines.
                for shape in p.get('county_shapes') or []:
                    g=shape['geometry'];polygons=g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']] if g['type']=='Polygon' else []
                    for polygon in polygons:
                        d.line([map_point(c,self.bounds) for c in polygon[0]],fill='#ffc887',width=4)
            if p.get('map_mode'):
                from .map_graphics import geometry
                geometry(image,p,self.bounds,t)
                d=ImageDraw.Draw(image)
            if p.get('visual_state')=='place_focus' and p.get('state_places'):
                from .geography import draw_places
                draw_places(image,p['state_places'],self.bounds,t,p.get('place_warning'))
                d=ImageDraw.Draw(image)
            if p.get('visual_state')=='county_focus' and p.get('county_shapes'):
                from .geography import draw_counties
                draw_counties(image,p['county_shapes'],self.bounds,t,p.get('place_warning'),p.get('spoken_counties'))
                d=ImageDraw.Draw(image)
            if p.get('visual_state')=='severe_outlook' and p.get('outlook'):
                from .spc import draw as draw_outlook
                draw_outlook(image,p['outlook'],self.bounds,t)
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
                if name==p.get('focus_label'):
                    r=16+10*abs(math.sin(t*math.pi*2));d.ellipse((px-r,py-r,px+r,py+r),outline='#82efdc',width=4)
        if not self.sources and sd.scene_type != 'statistics' and not (p.get('visual_state') in FULL_CARDS or p.get('graphic_style')):
            if sd.camera.geographic_target:
                tx,ty=map_point(sd.camera.geographic_target,self.bounds)
                u=easing(t,sd.camera.easing);x=.5+(tx/1920-.5)*u;y=.5+(ty/1080-.5)*u
            elif p.get('focus_coord'):
                # Move toward the focus as the zoom deepens, so push-ins and pull-outs share one path.
                tx,ty=map_point(p['focus_coord'],self.bounds)
                peak=max(sd.camera.start_zoom,sd.camera.end_zoom);k=(z-1)/(peak-1) if peak>1 else 0
                x=.5+(tx/1920-.5)*k;y=.5+(ty/1080-.5)*k
            if z>1.0005:
                w,h=1920/z,1080/z;cx=max(w/2,min(1920-w/2,x*1920));cy=max(h/2,min(1080-h/2,y*1080))
                # Sub-pixel crop box keeps slow moves smooth instead of stepping a whole pixel at a time.
                image=image.resize(SIZE,Image.Resampling.BILINEAR,box=(cx-w/2,cy-h/2,cx+w/2,cy+h/2))
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
        if p.get('visual_state'):
            from .visual_states import draw as draw_state
            draw_state(image,p,t)
            d=ImageDraw.Draw(image)
        if p.get('report_graphs'):
            from .report_graphs import draw as draw_report_graphs
            draw_report_graphs(image,p['report_graphs'],t)
            d=ImageDraw.Draw(image)
        # Header, location and lower third do not change within a shot: drawn once, then pasted.
        if self.chrome is None:
            top=Image.new('RGB',(1920,82),'#061724');td=ImageDraw.Draw(top)
            label(td,(52,27),'WEATHER INTELLIGENCE',25)
            label(td,(1370,29),('ARCHIVED WARNING' if all(s.historical for s in sd.sources) else 'SOURCE WARNING') if sd.event_id.startswith('urn:') else sd.event_id[:28]+' / SOURCE RECORD',23,'#65e1d1')
            # A narrow lower third leaves imagery dominant; full prose remains in the SRT.
            bottom=Image.new('RGB',(1920,110),'#061724');bd=ImageDraw.Draw(bottom)
            label(bd,(55,18),sd.headline,34)
            label(bd,(55,70),p.get('credit','NOAA / NHC · Natural Earth cartography')[:140],21,'#a8c4d0')
            place=None
            if p.get('location_label') and not p.get('report_graphs'):
                place=Image.new('RGBA',(1500,40),(0,0,0,0));label(ImageDraw.Draw(place),(0,0),p['location_label'][:95],26,'#82efdc')
            self.chrome=(top,bottom,place)
        top,bottom,place=self.chrome
        image.paste(top,(0,0))
        if place is not None:image.paste(place,(55,890),place)
        image.paste(bottom,(0,970))
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


FULL_CARDS = {'stat_card', 'quote_card', 'warning_card'}
TRANSITION_FRAMES = 10  # A third of a second; the shot keeps its exact duration.


def last_frame(direction, parameters, load_asset, seconds):
    """The outgoing shot's final picture, so the next shot can transition from it inside its own frames."""
    composer=Composer(direction,parameters,load_asset)
    count=max(1,round(seconds*30));span=parameters.get('camera_span')
    return composer.frame(span[0]+(span[1]-span[0])*(count-1)/count if span else 1)


def blend(kind, outgoing, incoming, u):
    """Presentation transitions between two rendered pictures; neither picture's data changes."""
    u=easing(u,'smoothstep')
    if kind=='dissolve':
        return Image.blend(outgoing,incoming,u)
    if kind in ('push','story'):
        shift=round(1920*u);image=Image.new('RGB',SIZE)
        image.paste(outgoing,(-shift,0));image.paste(incoming,(1920-shift,0))
        if kind=='story':
            # A brand-colored edge marks a change of story.
            ImageDraw.Draw(image).rectangle((1920-shift-14,0,1920-shift+14,1080),fill='#65e1d1')
        return image
    if kind=='wipe':
        edge=-160+round((1920+320)*u)
        mask=Image.linear_gradient('L').rotate(90,expand=True).resize((160,1080))
        full=Image.new('L',SIZE,0);full.paste(255,(0,0,max(0,edge),1080));full.paste(mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT),(edge,0))
        return Image.composite(incoming,outgoing,full)
    raise ValueError('Unknown transition.')


async def render_clip(direction, parameters, output, load_asset=None, seconds=None, on_progress=None, previous=None):
    """Stream RGB to FFmpeg; no unbounded PNG frame cache and no network at render time."""
    composer=await asyncio.to_thread(Composer,direction,parameters,load_asset)
    seconds=seconds or composer.direction.duration
    count=round(seconds*30)
    kind=parameters.get('transition_in')
    outgoing=await asyncio.to_thread(last_frame,*previous) if previous and kind else None
    log=Path(output).with_suffix('.log')
    with log.open('wb') as errors:
        process=await asyncio.create_subprocess_exec('ffmpeg','-y','-hide_banner','-loglevel','warning','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0','-an','-frames:v',str(count),*encoder_args(os.environ.get('WETHA_VIDEO_ENCODER','software')),'-pix_fmt','yuv420p','-threads','2',str(output),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=errors)
        try:
            span=parameters.get('camera_span')
            for i in range(count):
                # Shots split from one section continue its motion instead of restarting it.
                t=span[0]+(span[1]-span[0])*i/count if span else i/max(1,count-1)
                frame=await asyncio.to_thread(composer.frame,t)
                if outgoing is not None and i<TRANSITION_FRAMES:
                    frame=await asyncio.to_thread(blend,kind,outgoing,frame,(i+1)/(TRANSITION_FRAMES+1))
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


def render_clip_blocking(direction, parameters, output, assets, seconds, previous=None):
    """Process-pool form of render_clip: drawing runs outside the server process, so scenes render in parallel.

    `assets` and the previous shot's assets map asset ID to bytes; workers never read the database."""
    composer=Composer(direction,parameters,assets.__getitem__)
    count=round(seconds*30);kind=parameters.get('transition_in')
    outgoing=last_frame(previous[0],previous[1],previous[2].__getitem__,previous[3]) if previous and kind else None
    span=parameters.get('camera_span')
    with Path(output).with_suffix('.log').open('wb') as errors:
        process=subprocess.Popen(['ffmpeg','-y','-hide_banner','-loglevel','warning','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0',
                                  '-an','-frames:v',str(count),*encoder_args(os.environ.get('WETHA_VIDEO_ENCODER','software')),'-pix_fmt','yuv420p','-threads','2',str(output)],
                                 stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=errors)
        try:
            for i in range(count):
                t=span[0]+(span[1]-span[0])*i/count if span else i/max(1,count-1)
                frame=composer.frame(t)
                if outgoing is not None and i<TRANSITION_FRAMES:
                    frame=blend(kind,outgoing,frame,(i+1)/(TRANSITION_FRAMES+1))
                process.stdin.write(frame.tobytes())
            process.stdin.close()
            if process.wait(timeout=120):raise ValueError('Broadcast encoding failed; inspect scene log.')
        finally:
            if process.poll() is None:
                process.kill();process.wait()
    return str(output)


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
