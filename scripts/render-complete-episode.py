#!/usr/bin/env python3
"""Render one complete historical report from checksum-pinned local sources."""
import asyncio
import importlib.util
import json
import hashlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
import app.broadcast as engine
from app.broadcast import Camera, SceneDirection, VisualSource, label
from app.episode_graphics import EpisodeComposer, caption
from app.forecast_archive import parse
from app.production import checksum, probe
from app.cinematic import score_filter

spec=importlib.util.spec_from_file_location('benchmark',ROOT/'scripts/render-benchmark.py')
benchmark=importlib.util.module_from_spec(spec);spec.loader.exec_module(benchmark)
POOL=ROOT/'.local/media-pool'
SOURCES=ROOT/'.local/episode/sources'
OUT=ROOT/'.local/exports/complete-episode'
FORECAST_URL='https://www.nhc.noaa.gov/gis/forecast/archive/al092020_5day_028.zip'
RAIN_URL='https://www.weather.gov/images/ilm/climate/events/HurricaneIsaiasRainfallTotals.png'


def ffmpeg(args):
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error',*args],check=True)


def source_lock():
    lock=SOURCES/'checksums.json'
    current={n:checksum(SOURCES/n) for n in ('forecast-028.zip','rainfall.png')}
    if lock.exists() and json.loads(lock.read_text())!=current:
        raise ValueError('Official episode source differs from its pinned checksum.')
    lock.write_text(json.dumps(current,indent=2))
    return current


def plan():
    historical=ROOT/'.local/phase7/sources'
    benchmark.acquire(historical)
    base=benchmark.plan(historical)
    a=benchmark.parse_nhc((historical/'nhc28.html').read_text(),benchmark.URLS['nhc28.html'],'official_fetch')
    geo=parse((SOURCES/'forecast-028.zip').read_bytes(),a)
    (SOURCES/'forecast.geojson').write_text(json.dumps(geo,indent=2))
    pins=source_lock()
    nws=(historical/'nws.html').read_text()
    gauge_rows=[r for r in re.findall(r'<tr\b[^>]*>(.*?)</tr>',nws,re.S) if 'SC-GT-42' in r]
    if len(gauge_rows)!=1 or not re.search(r'>\s*6\.80\s*</td>',gauge_rows[0]):
        raise ValueError('NWS gauge observation does not support the rainfall caption.')
    forecast=VisualSource(source_url=FORECAST_URL,checksum=pins['forecast-028.zip'],event_id='AL092020',data_type='forecast',historical=True,
        observation_start=a.issued_at,observation_end=a.issued_at,advisory_issue_time=a.issued_at,forecast_valid_time=datetime.fromisoformat(geo['valid_until']),
        coverage='NHC advisory 28 cone, future center points and coastal warnings',projection='GCS_Sphere geographic degrees; Web Mercator presentation',
        attribution='NOAA / NHC',license='US federal government product; public domain',catalogue_url=FORECAST_URL)
    rainfall=VisualSource(source_url=RAIN_URL,checksum=pins['rainfall.png'],event_id='AL092020',data_type='historical_analysis',historical=True,
        observation_start=datetime.fromisoformat('2020-08-03T00:00:00+00:00'),observation_end=datetime.fromisoformat('2020-08-04T23:59:59+00:00'),
        coverage='NWS Wilmington Isaias event rainfall analysis; exact accumulation interval not printed',projection='native_viewport',
        attribution='NOAA / NWS Wilmington',license='US federal government product; public domain',catalogue_url=benchmark.PAGE,time_precision='day')
    catalog=json.loads((POOL/'catalog.json').read_text())
    for m in catalog['assets']:
        if checksum(POOL/m['filename'])!=m['checksum']:raise ValueError('Reviewed media checksum mismatch.')
    shots=[]
    def graphic(index,seconds,text,beat,**params):
        row=json.loads(json.dumps(base['scenes'][index]));row['direction']['duration']=seconds
        row['direction']['camera']=Camera(movement='region_focus',end_zoom=1).model_dump(mode='json')
        row['direction']['fallback']=None
        row['parameters'].update(params,episode_caption=text,episode_beat=beat)
        shots.append(dict(kind='graphic',duration=seconds,text=text,beat=beat,**row))
    def footage(filename,start,text,beat):
        media=next(m for m in catalog['assets'] if m['filename']==filename)
        if start+3>float(probe(POOL/filename)['format']['duration']):raise ValueError('Footage trim exceeds actual duration.')
        shots.append(dict(kind='footage',filename=filename,trim_start=start,duration=3,text=text,beat=beat,media=media))
    graphic(0,3,'70 to 85 mph in 12 hours. What changed before landfall?','THE HOOK')
    footage('ocean-rainstorm-34270425.mp4',5,'The coast was next. First, look at the storm itself.','ILLUSTRATIVE WEATHER')
    graphic(2,5,'Three reported positions brought Isaias closer to the Carolina coast.','THE APPROACH',bounds=[-83,29,-74,37])
    graphic(3,5,'Winds rose by 15 mph. Central pressure fell by 10 mb.','THE CHANGE')
    graphic(2,5,'Official warning lines marked the exposed coastline.','WARNINGS AS ISSUED',
        episode_map='warnings',geojson=geo,records=[],bounds=[-82,30,-72,42],places=[],
        credit='NOAA / NHC advisory 28 · 04 AUG 2020, 03 UTC · source coastal lines; no invented hazard areas')
    shots[-1]['direction']['sources']=[forecast.model_dump(mode='json')]
    graphic(5,4,'Now watch the real radar: the circulation moves toward the coast.','OBSERVED RADAR',observation_frame_range=[0,68])
    footage('storm-sea-1879456.mp4',6,'Wind is only one part of a coastal storm.','ILLUSTRATIVE ROUGH SEAS')
    graphic(2,6,'The forecast pointed north. These were future center positions.','FORECAST THEN',
        episode_map='forecast',geojson=geo,records=[],bounds=[-84,29,-62,57],places=[],
        credit='NOAA / NHC advisory 28 · issued 04 AUG 2020, 03 UTC · official future points and cone')
    shots[-1]['direction']['sources']=[forecast.model_dump(mode='json')];shots[-1]['direction']['layers']=['forecast_cone']
    graphic(0,5,'Afterward: one gauge near Pawley’s Island recorded 6.80 inches.','OBSERVATIONS AFTER',
        episode_map='rainfall',episode_caption='Afterward: one gauge near Pawley’s Island recorded 6.80 inches.',
        credit='NWS Wilmington · map: radar-estimated totals (inches) · 6.80 inches: separate gauge, 2.4 miles NW of Pawley’s Island')
    shots[-1]['direction'].update(scene_type='region_focus',sources=[rainfall.model_dump(mode='json')],asset_ids=['rainfall.png'],layers=[])
    footage('rain-wind-4436187.mp4',2,'Rain, wind, and coastal conditions all needed attention.','ILLUSTRATIVE RAIN AND WIND')
    graphic(1,4,'The satellite sequence shows the cloud system crossing the coast.','OBSERVED SATELLITE',observation_frame_range=[1,136])
    footage('st-lucia-irma-waves.webm',5,'A different storm shows why coastal footage matters.','IRMA / ST. LUCIA / 2017 ARCHIVE')
    graphic(2,4,'The cone tracked the center. Impacts could extend beyond it.','READING THE FORECAST',
        episode_map='forecast',geojson=geo,records=[],bounds=[-84,29,-62,57],places=[],
        credit='NOAA / NHC advisory 28 · historical forecast, not a current warning · cone is not an impact boundary')
    shots[-1]['direction']['sources']=[forecast.model_dump(mode='json')];shots[-1]['direction']['layers']=['forecast_cone']
    graphic(5,4,'The later radar frames show the storm moving inland.','OBSERVED RADAR / LATER',observation_frame_range=[68,136])
    graphic(2,3,'Stronger winds. Falling pressure. A coast in the storm’s path.','THE PAYOFF',bounds=[-83,29,-74,37])
    cursor=0
    for row in shots:row['start_seconds']=cursor;cursor+=row['duration']
    for row in shots:
        if row['kind']!='graphic':continue
        mode=row['parameters'].get('episode_map')
        titles={'warnings':'OFFICIAL COASTAL WARNINGS','forecast':'OFFICIAL FORECAST / AS ISSUED','rainfall':'POST-EVENT RAINFALL ANALYSIS'}
        if mode in titles:row['direction']['headline']=titles[mode]
        elif row['direction']['scene_type']=='storm_track':
            row['parameters']['places']=[['WILMINGTON',[-77.95,34.23]],['CHARLESTON',[-79.93,32.78]],['RALEIGH',[-78.64,35.78]]]
    assert cursor==60
    return dict(title='Isaias: the 12 hours before landfall',event_id='AL092020',historical=True,shots=shots,
        evidence=base['evidence'],media=catalog,official_layers={'forecast':forecast.model_dump(mode='json'),'rainfall':rainfall.model_dump(mode='json')},
        timestamp_verification=base['timestamp_verification'],source_pins=pins,
        rainfall_gauge={'station_id':'SC-GT-42','inches':6.80,'location':'2.4 miles northwest of Pawley’s Island',
            'source_url':benchmark.PAGE,'source_checksum':checksum(historical/'nws.html'),'method':'NWS event table; separate from radar estimate'},
        limitations=['Historical August 2020 case study; no current warning or forecast.',
          'Stock footage is illustrative; the licensed YouTube-origin clip shows Irma in St. Lucia in 2017, labeled on screen.',
          'Native radar/satellite/rainfall imagery is enlarged; source legends and timestamps are preserved.',
          'Rainfall map is a post-event radar estimate; the 6.80-inch gauge is a separate NWS table observation. Exact map accumulation interval is not printed.',
          'Map center connectors are presentation guides. Forecast points and warning lines come from the official GIS archive.',
          'No narration. Original locally synthesized music.'],paid_generation_calls=0)


async def run():
    OUT.mkdir(parents=True,exist_ok=True)
    p=plan()
    engine.Composer=EpisodeComposer
    def load(name):
        return ((SOURCES if name=='rainfall.png' else ROOT/'.local/phase7/sources')/name).read_bytes()
    code=Path(__file__).read_bytes()+Path(engine.__file__).read_bytes()+Path(sys.modules[EpisodeComposer.__module__].__file__).read_bytes()
    for i,row in enumerate(p['shots']):
        segment=OUT/f'shot-{i:02}.mp4';marker=segment.with_suffix('.sha256')
        key=hashlib.sha256(json.dumps(row,sort_keys=True).encode()+code).hexdigest()
        cached=segment.exists() and marker.exists() and marker.read_text()==key+':'+checksum(segment)
        print(f'Shot {i+1}/{len(p["shots"])}: '+('cached' if cached else row['beat']),flush=True)
        if cached:continue
        if row['kind']=='graphic':
            await engine.render_clip(row['direction'],row['parameters'],segment,load,row['duration'])
        else:
            overlay=Image.new('RGBA',(1920,1080));caption(overlay,row['text'],row['beat'])
            d=ImageDraw.Draw(overlay);d.rectangle((0,970,1920,1080),fill='#061724')
            m=row['media'];archival=m['context']=='archival'
            label(d,(55,987),'IRMA / ST. LUCIA / 05 SEP 2017' if archival else 'ILLUSTRATIVE STOCK / NOT ISAIAS FOOTAGE',32)
            label(d,(55,1037),m['attribution']+' · '+('CC BY 3.0 · trimmed, resized; audio removed' if archival else 'Pexels License'),23,'#a8c4d0')
            overlay_path=OUT/f'overlay-{i:02}.png';overlay.save(overlay_path)
            ffmpeg(['-ss',str(row['trim_start']),'-i',str(POOL/row['filename']),'-loop','1','-i',str(overlay_path),
              '-filter_complex','[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,setsar=1[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]',
              '-map','[v]','-t',str(row['duration']),'-an','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2',str(segment)])
        v=next(s for s in probe(segment)['streams'] if s['codec_type']=='video')
        if int(v['nb_frames'])!=row['duration']*30:raise ValueError('Incomplete segment frames.')
        marker.write_text(key+':'+checksum(segment))
    concat=OUT/'concat.txt';concat.write_text(''.join(f"file 'shot-{i:02}.mp4'\n" for i in range(len(p['shots']))))
    video=OUT/'episode-60.mp4'
    ffmpeg(['-f','concat','-safe','0','-i',str(concat),'-f','lavfi','-i',score_filter(60),'-map','0:v:0','-map','1:a:0',
       '-c:v','copy','-af','loudnorm=I=-22:TP=-2:LRA=9,afade=t=in:d=0.5,afade=t=out:st=58:d=2','-c:a','aac','-ar','48000','-t','60','-movflags','+faststart',str(video)])
    v=next(s for s in probe(video)['streams'] if s['codec_type']=='video')
    if (v['width'],v['height'],v['r_frame_rate'],int(v['nb_frames']))!=(1920,1080,'30/1',1800) or abs(float(v['duration'])-60)>.05:
        raise ValueError('Final video failed independent stream duration/frame validation.')
    qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-f','null','-'],capture_output=True,check=True)
    (OUT/'qc.log').write_bytes(qc.stderr)
    if b'black_start:' in qc.stderr:raise ValueError('Black frame interval in final episode.')
    p['output']=dict(path=str(video),checksum=checksum(video),seconds=60,frames=1800,width=1920,height=1080,fps=30,full_decode=True,black_check=True)
    (OUT/'manifest.json').write_text(json.dumps(p,indent=2))
    (OUT/'script.txt').write_text('\n\n'.join(f"{r['start_seconds']:02}–{r['start_seconds']+r['duration']:02}s / {r['beat']}\n{r['text']}" for r in p['shots']))
    contact=Image.new('RGB',(1280,900))
    for i,row in enumerate(p['shots']):
        frame=OUT/f'frame-{i:02}.jpg'
        ffmpeg(['-ss',str(row['start_seconds']+row['duration']*.7),'-i',str(video),'-frames:v','1','-vf','scale=320:180',str(frame)])
        contact.paste(Image.open(frame),((i%4)*320,(i//4)*180))
    contact.save(OUT/'contact.jpg')
    print(video,flush=True)


if __name__=='__main__':asyncio.run(run())
