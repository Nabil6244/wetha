#!/usr/bin/env python3
"""Revise a local narrated export with named NOAA coastal maps and cached GeoColor.
No live weather refresh, AI generation, transcription, or external paid service.
"""
import asyncio, hashlib, json, math, re, subprocess, sys, textwrap
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import broadcast, regional
from app.production import checksum, probe
from app.location_labels import catalogue
BASE=ROOT/'.local/exports/user-voiceover';OUT=ROOT/'.local/exports/user-voiceover-v2'
OBSROOT=Path.home()/'Library/Application Support/weather-intelligence-studio/data/production/observations'
SOURCE='https://mapservices.weather.noaa.gov/tropical/rest/services/tropical/NHC_Breakpoints/MapServer'

def ff(args):subprocess.run(['ffmpeg','-y','-v','error',*map(str,args)],check=True)
def text(d,xy,value,size=32,color='white'):d.text(xy,value,font=broadcast.font(size),fill=color,stroke_width=1,stroke_fill='#071721')

def map_image(row,t,index):
    warnings=row.get('treatment','').startswith('warning-record')
    coast=(-92,27.5,-81.2,33.3);gulf=(-98,17,-78,33.4)
    bounds=coast if warnings else gulf
    west,south,east,north=bounds;u=broadcast.easing(t);zoom=1+.055*u
    cx=(west+east)/2+.08*math.sin(t*math.pi);cy=(south+north)/2
    bounds=(cx-(east-west)/zoom/2,cy-(north-south)/zoom/2,cx+(east-west)/zoom/2,cy+(north-south)/zoom/2)
    # Markers remain in map coordinates while the camera moves.
    im=broadcast.map_base(tuple(round(x,3) for x in bounds)).copy();d=ImageDraw.Draw(im)
    for state in regional.catalogue()['regions']:
        if state['code'] not in ('LA','MS','AL','FL'):continue
        for ring in state['rings']:
            points=[broadcast.map_point(p,bounds) for p in ring]
            d.polygon(points,fill={'LA':'#2a6060','MS':'#356d64','AL':'#3d695c','FL':'#41776a'}[state['code']]);d.line(points,fill='#91c7bd',width=2)
    places={p['name']:p['coordinates'] for p in catalogue()['places']}
    pairs=[['Mouth of the Mississippi River','Steinhatchee River'],['Ocean Springs','Bay/Gulf County Line'],['Jefferson/Plaquemines Parish Line','Ocean Springs'],['Bay/Gulf County Line','Aucilla River'],['Steinhatchee River','Yankeetown']]
    if warnings:
        number=int(row['treatment'].split('-')[-1])%5;selected=pairs[number]
        headings=['STORM SURGE WARNING','HURRICANE WARNING','TROPICAL STORM WARNING / WEST','TROPICAL STORM WARNING / EAST','STORM SURGE WATCH']
        heading=headings[number]
    else:selected=['Ocean Springs','Bay/Gulf County Line','Steinhatchee River','Yankeetown','Progreso'];heading='GULF COAST / REPORTED POSITION'
    for i,name in enumerate(selected):
        x,y=broadcast.map_point(places[name],bounds)
        if not (0<x<1920 and 80<y<980):continue
        r=11+4*math.sin(t*math.pi*2);d.ellipse((x-r,y-r,x+r,y+r),fill='#ffcd6f',outline='white',width=3)
        # Separate label rails eliminate collisions in the Florida Big Bend.
        tx=90+(i%2)*930 if warnings else min(1560,max(90,x-80))
        ty=245+(i//2)*140 if warnings else y+55+(i%2)*50
        if not warnings and name=='Progreso':ty=y-70
        lines=textwrap.wrap(name.upper(),36)
        if warnings:
            d.line((x,y,tx+60,ty+80),fill='#ffcd6f',width=2)
            d.rounded_rectangle((tx-15,ty-15,tx+800,ty+95),radius=12,fill='#102b3a',outline='#73999b',width=2)
        for j,line in enumerate(lines):text(d,(tx,ty+j*42),line,34 if warnings else 27,'#ffe1a6')
    if not warnings:
        px,py=broadcast.map_point((-90.6,23.7),bounds);radius=22+6*math.sin(t*math.pi*3)
        d.ellipse((px-radius,py-radius,px+radius,py+radius),outline='#79ffea',width=5)
        d.ellipse((px-7,py-7,px+7,py+7),fill='white')
        text(d,(px+35,py-60),'REPORTED CENTER',30,'#79ffea');text(d,(px+35,py-15),'23.7°N / 90.6°W',37)
        x,y=broadcast.map_point((-91.2,23.3),bounds)
        d.ellipse((x-6,y-6,x+6,y+6),fill='#e9edf0')
        text(d,(x-165,y+40),'09 UTC / 23.3°N',24,'#bfd1d6')
        d.rounded_rectangle((1200,690,1850,890),radius=20,fill='#0d2734',outline='#4a7a82',width=2)
        text(d,(1230,715),'80 mph · 975 mb',62,'#79ffea');text(d,(1230,805),'Source-reported storm values',28)
    d.rectangle((0,0,1920,90),fill='#051721');text(d,(50,25),heading,35,'#79ffea')
    d.rectangle((0,970,1920,1080),fill='#051721')
    text(d,(50,989),'LOUISIANA  ·  MISSISSIPPI  ·  ALABAMA  ·  FLORIDA' if warnings else 'YUCATAN / MEXICO  ·  GULF OF MEXICO  ·  NORTHERN GULF COAST',29)
    text(d,(50,1034),'NHC coastal place coordinates · endpoint markers only; no inferred warning polygon' if warnings else '12 UTC source report · named places are geographic context, not a predicted storm path',23,'#b7ccd5')
    return im

async def encode_map(path,row,index):
    count=row['frames'];log=path.with_suffix('.log')
    with log.open('wb') as errors:
        proc=await asyncio.create_subprocess_exec('ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0','-frames:v',str(count),'-an',*broadcast.encoder_args(),'-threads','2','-pix_fmt','yuv420p',str(path),stdin=asyncio.subprocess.PIPE,stderr=errors)
        for i in range(count):proc.stdin.write(map_image(row,i/max(1,count-1),index).tobytes());await proc.stdin.drain()
        proc.stdin.close();await proc.wait()
        if proc.returncode:raise RuntimeError('Map render failed')

async def main():
    OUT.mkdir(parents=True,exist_ok=True);manifest=json.loads((BASE/'manifest.json').read_text())
    if checksum(Path(manifest['output']['path']))!=manifest['output']['checksum']:raise ValueError('Original export changed')
    cinematic=json.loads((ROOT/'.local/exports/weather-cinematic-five-minute.json').read_text());obs=cinematic['timeline']['scenes'][0]['observations']
    seconds=manifest['output']['seconds'];total=manifest['output']['frames'];listing=[]
    for i,o in enumerate(obs):
        source=OBSROOT/o['filename']
        if checksum(source)!=o['checksum']:raise ValueError('Satellite checksum mismatch')
        with Image.open(source) as raw:im=ImageOps.fit(raw.convert('RGB'),(1920,1080),centering=(.5,.48))
        shade=Image.new('RGBA',im.size);d=ImageDraw.Draw(shade)
        for x in range(0,1920,12):d.rectangle((x,0,x+11,1080),fill=(1,8,14,int(175*(1-x/2300))))
        im=Image.alpha_composite(im.convert('RGBA'),shade);d=ImageDraw.Draw(im)
        stamp=datetime.fromisoformat(o['observed_at'])
        d.rectangle((1160,92,1890,210),fill=(2,12,22,215));text(d,(1190,112),'GOES-19 / GEOCOLOR',29,'#8af1de');text(d,(1190,157),stamp.strftime('%d %b %Y / %H:%M UTC'),29)
        png=OUT/f'satellite-{i:02}.png';im.convert('RGB').save(png)
        n=total//len(obs)+(1 if i<total%len(obs) else 0)
        listing.extend([f"file '{png.name}'\n",f'duration {n/30:.9f}\n'])
    listing.append(f"file 'satellite-{len(obs)-1:02}.png'\n");satlist=OUT/'satellite-list.txt';satlist.write_text(''.join(listing));satvideo=OUT/'satellite-context.mp4'
    if not satvideo.exists():
        ff(['-f','concat','-safe','0','-i',satlist,'-vf',f"fps=30,scale=2048:1152,crop=1920:1080:x='64+20*sin(t/12)':y='36+12*sin(t/15)',setsar=1",'-frames:v',total,'-an',*broadcast.encoder_args(),'-threads','2','-pix_fmt','yuv420p',satvideo])
    footer=Image.new('RGBA',(1920,1080));d=ImageDraw.Draw(footer);text(d,(55,934),'REGIONAL SATELLITE CONTEXT / independent observation time / not verified event imagery',25,'#bfd4dc');footer.save(OUT/'context-footer.png')
    original_files=[BASE/name for name in re.findall(r"file '([^']+)'",(BASE/'final-concat.txt').read_text())];pieces=[];rows=[]
    for i,(old,row) in enumerate(zip(original_files,manifest['shots'])):
        row=dict(row);path=OUT/f'shot-{i:03}.mp4';treatment=row.get('treatment','')
        if row['type']=='footage':path=old
        elif treatment.startswith(('warning-record','reported-map')):
            if not path.exists():await encode_map(path,row,i)
            row['visual_revision']='Named geographic map with camera motion and NOAA coastal place coordinates'
        else:
            if not path.exists():
                ff(['-ss',row['start_seconds'],'-i',satvideo,'-i',old,'-filter_complex',"[1:v]colorkey=0x081d2c:0.035:0.015[fg];[0:v][fg]overlay=shortest=1,drawbox=x=0:y=920:w=1920:h=55:color=0x03121d@0.85:t=fill[v]",'-map','[v]','-frames:v',row['frames'],'-an',*broadcast.encoder_args(),'-threads','2','-pix_fmt','yuv420p',path])
            row['visual_revision']='Measured graphic over cached NOAA GeoColor; independent observation timestamps'
        pieces.append(path);rows.append(row);print(json.dumps({'shot':i+1,'total':len(original_files),'type':row['visual_revision'] if 'visual_revision' in row else 'footage'}),flush=True)
    concat=OUT/'concat.txt';concat.write_text(''.join(f"file '{p.resolve()}'\n" for p in pieces));final=OUT/'isaias-user-voiceover-v2.mp4'
    enable='+'.join(f"between(t,{row['start_seconds']:.6f},{row['start_seconds']+row['seconds']-1/30:.6f})" for row in rows if row.get('visual_revision','').startswith('Measured'))
    ff(['-f','concat','-safe','0','-i',concat,'-i',BASE/'isaias-user-voiceover.mp4','-loop','1','-i',OUT/'context-footer.png','-filter_complex',f"[0:v][2:v]overlay=shortest=1:enable='{enable}'[v]",'-map','[v]','-map','1:a:0','-frames:v',total,'-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',final])
    qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(final),'-vf','crop=1920:850:0:100,blackdetect=d=0.01:pix_th=0.02:pic_th=0.995','-f','null','-'],capture_output=True,check=True)
    (OUT/'qc.log').write_bytes(qc.stderr);assert b'black_start:' not in qc.stderr
    info=probe(final);v=next(s for s in info['streams'] if s['codec_type']=='video');assert int(v['nb_frames'])==total
    manifest.update(shots=rows,visual_revision=2,satellite_sources=obs,place_coordinate_source=catalogue(),output={'path':str(final),'checksum':checksum(final),'frames':total,'seconds':seconds,'full_decode':True,'picture_area_black_check':True})
    manifest['limitations'].append('Satellite imagery is regional context with independent observation times; it is not identified as imagery of the reported storm.')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for name in ('captions.srt','script.txt'):(OUT/name).write_bytes((BASE/name).read_bytes())
    print('COMPLETE '+str(final),flush=True)
if __name__=='__main__':asyncio.run(main())
