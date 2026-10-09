#!/usr/bin/env python3
"""Render the verified Isaias AL092020 visual benchmark using local tools.

No paid API, local voiceover, optical flow or invented observation frames.
Downloads are limited to fixed official URLs; subsequent runs reuse pinned bytes.
"""
import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import httpx
import app.broadcast as engine
from app.broadcast import Camera, SceneDirection, VisualSource, render_clip, dissolve_filter
from app.cinematic import score_filter
from app.production import probe, checksum
from app.weather import parse_nhc

PAGE='https://www.weather.gov/ilm/HurricaneIsaias2020'
URLS={'nws.html':PAGE,'satellite.gif':'https://www.weather.gov/images/ilm/climate/events/HurricaneIsaiasSatelliteLoop.gif',
      'radar.gif':'https://www.weather.gov/images/ilm/climate/events/HurricaneIsaiasRadarLoop.gif'}
for number in range(26,29):URLS[f'nhc{number}.html']=f'https://www.nhc.noaa.gov/archive/2020/al09/al092020.public.{number:03}.shtml'


def acquire(folder):
    folder.mkdir(parents=True,exist_ok=True)
    lock=folder/'checksums.json';saved=json.loads(lock.read_text()) if lock.exists() else {}
    for name,url in URLS.items():
        path=folder/name
        if not path.exists():
            with httpx.stream('GET',url,timeout=30,follow_redirects=False) as r:
                r.raise_for_status();raw=bytearray()
                for chunk in r.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>64*1024*1024:raise ValueError('Historical source exceeds 64 MiB limit.')
            path.write_bytes(raw)
        digest=checksum(path)
        if name in saved and saved[name]!=digest:raise ValueError('Cached official source changed: '+name)
        saved[name]=digest
    lock.write_text(json.dumps(saved,indent=2))
    if 'Color-enhanced Infrared satellite loop' not in (folder/'nws.html').read_text() or 'Radar loop of Hurricane Isaias making landfall' not in (folder/'nws.html').read_text():
        raise ValueError('NWS catalogue no longer identifies the supplied historical loops.')
    return saved


def plan(folder):
    advisories=[parse_nhc((folder/f'nhc{n}.html').read_text(),URLS[f'nhc{n}.html'],'official_fetch') for n in range(26,29)]
    if any(a.event_key!='AL092020' for a in advisories):raise ValueError('Historical advisory event mismatch.')
    records=[{'coordinates':[a.facts['longitude'],a.facts['latitude']],'issued_at':a.issued_at.isoformat(),'source_url':a.source_url,'checksum':a.checksum,**a.facts} for a in advisories]
    timestamp_records=json.loads((ROOT/'backend/app/data/isaias2020-frame-times.json').read_text())
    def source(kind,name,start,end):
        verified=timestamp_records[name.removesuffix('.gif')]
        if verified['source_checksum'] != checksum(folder/name):
            raise ValueError('Source loop differs from the frame timestamp verification record.')
        return VisualSource(source_url=URLS[name],checksum=checksum(folder/name),event_id='AL092020',data_type=kind,historical=True,
                            observation_start=datetime.fromisoformat(start),observation_end=datetime.fromisoformat(end),
                            coverage='US Southeast / Carolinas; source-native labeled viewport',projection='native_viewport',
                            attribution='NOAA / National Weather Service Wilmington',license='US federal government weather product; public domain',
                            catalogue_url=PAGE,time_precision='source_embedded', observation_times=verified['observation_times'], advisory_issue_time=advisories[-1].issued_at)
    # Bounds were read from the original loop's embedded UTC labels; intermediate
    # times remain the original pixels, never inferred from GIF playback delay.
    satellite=source('satellite_observation','satellite.gif','2020-08-03T12:00:28+00:00','2020-08-04T09:00:28+00:00')
    radar=source('radar_reflectivity','radar.gif','2020-08-03T16:01:38+00:00','2020-08-04T07:28:48+00:00')
    evidence=[VisualSource(source_url=a.source_url,checksum=a.checksum,event_id=a.event_key,data_type='reported_center',historical=True,
                          observation_start=a.issued_at,observation_end=a.issued_at,advisory_issue_time=a.issued_at,coverage='NHC reported storm center',
                          projection='EPSG:4326',attribution='NOAA / NHC',license='US federal government advisory; public domain',catalogue_url=a.source_url) for a in advisories]
    def scene(kind,headline,camera=None,sources=None,assets=None,transition='dissolve',fallback=None):
        return SceneDirection(scene_type=kind,event_id='AL092020',duration=5,headline=headline,camera=camera or Camera(),sources=sources or evidence,
                              asset_ids=assets or [],transition_out=transition,fallback=fallback).model_dump(mode='json')
    satparams={'native_crop':[0,0,600,485],'source_strip':[122,485,598,543],'strip_size':[1050,125],
               'credit':'NOAA / NWS Wilmington · GOES-16 infrared · 03–04 AUG 2020 · native timestamps preserved'}
    mapparams={'bounds':[-84,28,-73,37],'records':records,'places':[['FLORIDA',[-81.7,29]],['CAROLINAS',[-81.8,34.9]],['ATLANTIC OCEAN',[-76.8,30.2]]],
               'credit':'NOAA / NHC · 03 AUG 2020, 15 / 21 UTC; 04 AUG 03 UTC · connectors are presentation guides'}
    before,after=advisories[0],advisories[-1]
    changes=[{'field':k,'previous':before.facts[k],'current':after.facts[k],'time_label':'03 AUG 15 UTC → 04 AUG 03 UTC'} for k in ('wind_mph','pressure_mb')]
    scenes=[
        {'direction':scene('satellite_wide','ISAIAS / APPROACH TO LANDFALL',Camera(movement='smooth_zoom_in',end_zoom=1.17),[satellite],['satellite.gif']), 'parameters':satparams},
        {'direction':scene('satellite_timelapse','ACTUAL CLOUD EVOLUTION',Camera(movement='camera_drift',start_zoom=1.08,end_zoom=1.1),[satellite],['satellite.gif'],'satellite_to_map'),'parameters':satparams},
        {'direction':scene('storm_track','OFFICIAL REPORTED POSITIONS',Camera(movement='storm_follow',geographic_target=tuple(records[-1]['coordinates']),end_zoom=1.08),transition='track_to_stats'),'parameters':mapparams},
        {'direction':scene('statistics','RE-INTENSIFICATION BEFORE LANDFALL',transition='stats_to_footage'),'parameters':{**mapparams,'changes':changes,'credit':'NOAA / NHC archived advisories 26 and 28 · two reported measurements; bars reveal actual endpoints'}},
        {'direction':scene('region_focus','THE CAROLINA COAST',Camera(movement='map_to_footage',end_zoom=1.14),fallback='No verified reusable ground footage was obtained. Official source map replaces footage.'),'parameters':{**mapparams,'records':records[-1:],'bounds':[-82.2,32,-76.7,36.4],'fallback_label':'Ground footage unavailable · source map shown instead'}},
        {'direction':scene('radar_animation','LANDFALL / RADAR REFLECTIVITY',Camera(movement='camera_drift',end_zoom=1.02),[radar],['radar.gif'],'radar_to_satellite'),'parameters':{'native_crop':[0,0,618,446],'source_strip':[629,0,794,446],'strip_size':[210,650],'credit':'NOAA / NWS Wilmington · KLTX reflectivity (dBZ), not rainfall totals · 03–04 AUG 2020'}},
    ]
    for row in scenes:
        typ=row['direction']['scene_type'];row['direction']['layers']=['satellite'] if typ.startswith('satellite') else ['radar'] if typ=='radar_animation' else ['statistics'] if typ=='statistics' else ['reported_track']
    return {'schema_version':1,'event_id':'AL092020','title':'Isaias / Carolina landfall','historical':True,'scenes':scenes,
            'evidence':[a.model_dump(mode='json') for a in advisories],
            'timestamp_verification':{'satellite_frames':136,'radar_frames':136,'record':'backend/app/data/isaias2020-frame-times.json','method':'Local OCR of each embedded timestamp, strict UTC parsing, zero chronological reversals; record bound to original GIF SHA256'},
            'scope':'Historical visual benchmark, no active warning or current forecast; native viewport crops are presentation only.',
            'limitations':['No verified ground footage; 20–25 second map fallback.', 'Native source imagery is 600×544 satellite / 794×446 radar, enlarged to 1080p.',
                           'Native satellite/radar images are not georeferenced to the rendered map; dissolve is editorial, not geographic registration.',
                           'No forecast cone available in this benchmark; official reported centers only.', 'Presentation camera drift does not claim a measured storm-following pixel path.']}


async def run(output,source_folder):
    acquire(source_folder);p=plan(source_folder)
    output.mkdir(parents=True,exist_ok=True)
    (output/'scene-schema.json').write_text(json.dumps(SceneDirection.model_json_schema(),indent=2))
    def load(identity):return (source_folder/identity).read_bytes()
    durations=[]
    for i,row in enumerate(p['scenes']):
        seconds=5 if i==0 else 5.3;durations.append(seconds)
        cache_key=hashlib.sha256(json.dumps(row,sort_keys=True).encode()+Path(engine.__file__).read_bytes()).hexdigest()
        segment=output/f'scene-{i}.mp4';marker=segment.with_suffix('.sha256')
        valid=segment.exists() and marker.exists() and marker.read_text()==cache_key+':'+checksum(segment)
        print(f'Scene {i+1}/6: '+('cached' if valid else row['direction']['scene_type']),flush=True)
        if not valid:
            await render_clip(row['direction'],row['parameters'],segment,load,seconds)
            marker.write_text(cache_key+':'+checksum(segment))
    filters,mapped,total=dissolve_filter(durations)
    filters+=f';{mapped}format=yuv420p[out]'
    args=['ffmpeg','-y','-hide_banner','-loglevel','warning','-filter_complex_threads','2']
    for i in range(6):args+=['-i',str(output/f'scene-{i}.mp4')]
    args+=['-f','lavfi','-i',score_filter(30),'-filter_complex',filters,'-map','[out]','-map','6:a:0',
           '-af','loudnorm=I=-22:TP=-2:LRA=9,afade=t=in:d=1,afade=t=out:st=28:d=2','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-c:a','aac','-ar','48000','-t','30','-movflags','+faststart',str(output/'phase7-isaias-30s.mp4')]
    print('Assembling dissolves + original instrumental',flush=True)
    subprocess.run(args,check=True)
    video=output/'phase7-isaias-30s.mp4';info=probe(video);v=next(s for s in info['streams'] if s['codec_type']=='video')
    assert (v['codec_name'],v['width'],v['height'],v['r_frame_rate'])==('h264',1920,1080,'30/1')
    assert abs(float(info['format']['duration'])-30)<.05
    qc=subprocess.run(['ffmpeg','-hide_banner','-v','info','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-f','null','-'],capture_output=True,check=True)
    (output/'qc.log').write_bytes(qc.stderr)
    assert b'black_start:' not in qc.stderr
    p.update(output={'path':str(video.resolve()),'seconds':30,'width':1920,'height':1080,'fps':30,'codec':'h264','checksum':checksum(video),'full_decode':True,'black_check':True},
             transitions={'type':'dissolve','overlap_seconds':.3,'total_seconds':total},music={'creator':'Weather Intelligence Studio','method':'Original local FFmpeg synthesis; no paid service, samples, or voice'})
    (output/'manifest.json').write_text(json.dumps(p,indent=2))
    print(str(video.resolve()),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'.local/exports/phase7');parser.add_argument('--sources',type=Path,default=ROOT/'.local/phase7/sources');a=parser.parse_args()
    asyncio.run(run(a.output,a.sources))
