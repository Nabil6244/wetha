#!/usr/bin/env python3
"""Interleave the approved recorded forecast with dated archival hazard examples."""
import argparse, asyncio, hashlib, importlib.util, json, math, subprocess, sys, textwrap
from pathlib import Path
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import documentary
from app.broadcast import font, encoder_args, map_base, map_point
from app.regional import catalogue
from app.production import checksum, probe, srt_time
from app.cinematic import score_filter
BASE=ROOT/'.local/exports/forecast-news';OUT=ROOT/'.local/exports/florida-mixed-report'
BLOCKS=[
 ('intro',-1,'Forecast numbers. Real scenes. Different dates.',
  'This is the recorded Florida forecast edition from October ninth, twenty twenty-six. We are combining its official maps and statistics with clearly dated historical footage. These opening rain scenes show Hurricane Ian in Bradenton in twenty twenty-two. They are examples of weather impacts, not observations of the forecast storm.',
  [('858954',0),('858954',2)],['RECORDED FORECAST','09 OCT 2026','Historical clips retain their own event and date.']),
 ('coast',3,'A forecast height is not a height measured in a video.',
  'For historical context, these coastal waves were filmed in Key West before Hurricane Irma in September twenty seventeen. The aerial damage view shows the Florida Keys after that storm. Neither recording measures the surge height. Keep the earlier forecast range separate from what these archival images can actually show.',
  [('549583',0),('550690',0)],['COASTAL ARCHIVE','IRMA / 2017','Key West waves · Florida Keys aerial damage']),
 ('rain',4,'The street view explains the impact, not the rain total.',
  'Now look at Bradenton during Hurricane Ian on September twenty eighth, twenty twenty-two. The recording shows rain, moving trees, street water, and roadside damage. It helps explain what local impacts can look like. It does not tell us a rainfall total, or prove what will happen during this recorded forecast.',
  [('858954',6),('858954',7),('858954',8),('858954',10)],['RAIN AND WIND ARCHIVE','IAN / 2022','Bradenton · no rainfall total inferred from footage']),
 ('recovery',10,'The storm ends. The recovery continues.',
  'The historical record also includes what happens afterward. These crews clear debris in Fort Myers Beach after Ian. Temporary roofs appear in Mexico Beach after Michael in twenty eighteen. Relief supplies are distributed in Florida after Milton in twenty twenty-four. Each scene belongs to its own storm. Together, they explain different stages of recovery without predicting damage from the current forecast.',
  [('859328',0),('859328',5),('642684',1),('940076',4)],['RECOVERY ARCHIVE','THREE SEPARATE STORMS','Ian 2022 · Michael 2018 · Milton 2024'])]
EVENTS={'AL092022':'IAN / 2022','AL112017':'IRMA / 2017','AL142018':'MICHAEL / 2018','AL142024':'MILTON / 2024'}
def ff(*args):subprocess.run(['ffmpeg','-y','-v','error',*map(str,args)],check=True)
def key_file(path,key):return path.exists() and path.with_suffix('.sha256').exists() and path.with_suffix('.sha256').read_text()==key+':'+checksum(path)
def mark(path,key):path.with_suffix('.sha256').write_text(key+':'+checksum(path))
def graphic(path,title,lines,seconds,credits=False):
 if path.stem=='credits':
  im=Image.new('RGB',(1920,1080),'#071722');d=ImageDraw.Draw(im)
  d.text((75,70),'FLORIDA / SOURCE CREDITS',font=font(30),fill='#82efdc')
  d.text((75,195),title,font=font(56),fill='white')
  for y,line in zip([440,555,710],lines):
   for n,part in enumerate(textwrap.wrap(line,80)):d.text((80,y+n*48),part,font=font(36),fill='white')
  png=path.with_suffix('.png');im.save(png)
  ff('-loop','1','-i',png,'-t',seconds,'-r',30,'-an',*encoder_args(),'-pix_fmt','yuv420p',path);return
 bounds=(-88.5,24,-79,32);background=map_base(bounds).copy();d=ImageDraw.Draw(background)
 for ring in next(r for r in catalogue()['regions'] if r['code']=='FL')['rings']:
  points=[map_point(point,bounds) for point in ring];d.polygon(points,fill='#245969');d.line(points,fill='#8ce4e3',width=3)
 bg=path.with_name(path.stem+'-map.png');background.save(bg)
 im=Image.new('RGBA',(1920,1080));d=ImageDraw.Draw(im)
 d.rectangle((0,84,900,1080),fill=(5,17,30,225));d.rectangle((0,0,1920,84),fill=(5,17,30,225))
 d.text((55,28),'FLORIDA / GEOGRAPHIC CONTEXT',font=font(28),fill='#82efdc')
 d.text((1110,35),'ARCHIVE + RECORDED EDITION',font=font(24),fill='white')
 y=445
 for i,line in enumerate(lines):
  for part in textwrap.wrap(line,36):d.text((55,y),part,font=font(35 if i!=1 else 43),fill='#81dce6' if i==1 else 'white');y+=54
  y+=28
 d.rectangle((935,920,1880,1055),fill=(5,17,30,220))
 d.text((960,935),'LOCATION CONTEXT · FLORIDA',font=font(29),fill='white')
 d.text((960,990),'Map outline is not a forecast or impact boundary.',font=font(26),fill='#bad6de')
 png=path.with_suffix('.png');im.save(png);frames=round(seconds*30)
 ff('-loop','1','-i',bg,'-loop','1','-i',png,'-filter_complex',f"[0:v]zoompan=z='1+0.035*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=30[b];[b][1:v]overlay=shortest=1[v]",'-map','[v]','-frames:v',frames,'-an',*encoder_args(),'-pix_fmt','yuv420p',path)
def render_footage(path,row,source,shot):
 # Footage remains clean; full source and creator records move to end credits.
 base=Image.new('RGBA',(1920,1080));d=ImageDraw.Draw(base)
 for y in range(84):d.line((0,y,1920,y),fill=(3,14,23,round(185*(1-y/84))))
 for xy,text,size in [((55,35),row['header'],24),((1230,35),row['context'],24)]:d.text(xy,text,font=font(size),fill='white',stroke_width=1,stroke_fill='#081d2c')
 png=path.with_suffix('.png');base.save(png)
 ff('-ss',shot['start'],'-i',source,'-loop','1','-i',png,'-filter_complex','[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,setsar=1[b];[b][1:v]overlay=shortest=1[v]','-map','[v]','-frames:v',round(shot['seconds']*30),'-an',*encoder_args(),'-pix_fmt','yuv420p',path)
def footage(path,a,shot,title):
 row={'header':'HISTORICAL FLORIDA / '+EVENTS[a['catalog']['event_id']],'context':'ARCHIVE / '+(a['catalog']['captured_at'] or 'SEP–OCT 2022'),'text':shot['description']}
 render_footage(path,row,ROOT/a['path'],shot)
def footage_credits(path,bank,base,seconds):
 im=Image.new('RGB',(1920,1080),'#071722');d=ImageDraw.Draw(im)
 d.text((60,55),'FOOTAGE CREDITS',font=font(40),fill='#82efdc')
 selected={id for block in BLOCKS for id,_ in block[4]}
 groups=[('ARCHIVAL / DVIDS',[(a['title'],a['metadata']['attribution']) for a in bank['assets'] if a['id'] in selected]),('ILLUSTRATIVE / PEXELS',[(a['location'],a['author']+' / Pexels') for a in base['media']])]
 for column,(heading,entries) in enumerate(groups):
  x=60+column*940;y=150;d.text((x,y),heading,font=font(28),fill='#81dce6');y+=55
  for name,author in entries:
   d.text((x,y),name,font=font(26),fill='white');y+=37
   for line in textwrap.wrap(author,60):d.text((x,y),line,font=font(23),fill='#bad6de');y+=31
   y+=25
 for i,line in enumerate(textwrap.wrap(bank['non_endorsement_disclaimer'],110)):d.text((60,935+i*36),line,font=font(26),fill='white')
 d.text((60,1030),'Full source URLs and reuse terms are retained in the accompanying source manifest.',font=font(24),fill='#bad6de')
 png=path.with_suffix('.png');im.save(png);ff('-loop','1','-i',png,'-frames:v',round(seconds*30),'-r',30,'-an',*encoder_args(),'-pix_fmt','yuv420p',path)
def run():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archived-review',action='store_true',required=True);args=parser.parse_args()
 OUT.mkdir(parents=True,exist_ok=True);p=json.load(open(BASE/'manifest.json'));bank=json.load(open(ROOT/'docs/FLORIDA_FOOTAGE_BANK.json'));assets={a['id']:a for a in bank['assets']}
 if checksum(Path(p['output']['path']))!=p['output']['checksum']:raise ValueError('Approved forecast output changed')
 for a in assets.values():
  if checksum(ROOT/a['path'])!=a['checksum']:raise ValueError('Footage checksum changed')
 spec=importlib.util.spec_from_file_location('approved_forecast',ROOT/'scripts/render-forecast-news.py');forecast=importlib.util.module_from_spec(spec);spec.loader.exec_module(forecast)
 video_parts=[];audio_parts=[];rows=[];captions=[];cursor=0;code=Path(__file__).read_bytes()
 def append(path,row):
  nonlocal cursor
  info=probe(path);v=next(s for s in info['streams'] if s['codec_type']=='video');frames=int(v['nb_frames']);length=frames/30
  if (v['width'],v['height'],v['r_frame_rate'])!=(1920,1080,'30/1'):raise ValueError('Mixed render requires matching video format')
  row.update(start_seconds=cursor,seconds=length,frames=frames);rows.append(row);video_parts.append(path);cursor+=length
 def block(b):
  name,after,title,text,selection,lines=b;start=cursor;txt=OUT/(name+'.txt');txt.write_text(text);aiff=OUT/(name+'.aiff');key=hashlib.sha256(('Samantha/150/'+text).encode()).hexdigest()
  if not key_file(aiff,key):subprocess.run(['/usr/bin/say','-v','Samantha','-r','150','-f',str(txt),'-o',str(aiff)],check=True);mark(aiff,key)
  speech=float(probe(aiff)['format']['duration']);total=math.ceil((speech+.5)*30)/30;cut_seconds=sum(assets[id]['shots'][index]['seconds'] for id,index in selection);hold=round(total-cut_seconds,6)
  if hold<3:raise ValueError('Archive narration needs room for context graphic')
  for n,(id,index) in enumerate(selection):
   a=assets[id];shot=a['shots'][index];path=OUT/f'{name}-foot-{n:02d}.mp4';key=hashlib.sha256(code+json.dumps([a,shot],sort_keys=True).encode()).hexdigest()
   if not key_file(path,key):footage(path,a,shot,title);mark(path,key)
   append(path,{'kind':'archive_footage','descriptive_headline_visible':False,'source_credit_on_footage':False,'source_id':id,'range_id':shot['id'],'event_id':a['catalog']['event_id'],'captured_at':a['catalog']['captured_at'],'location':a['catalog']['location'],'source':a['metadata']['source'],'checksum':a['checksum'],'trim_start':shot['start'],'block':name})
  path=OUT/(name+'-context.mp4');key=hashlib.sha256(code+json.dumps([title,lines,hold]).encode()).hexdigest()
  if not key_file(path,key):graphic(path,title,lines,hold);mark(path,key)
  append(path,{'kind':'archive_context_'+name,'descriptive_headline_visible':False,'block':name,'text':title})
  total=cursor-start;wav=OUT/(name+'.wav');ff('-i',aiff,'-af',f'apad=whole_dur={total}','-t',total,'-ar',48000,'-ac',1,wav);audio_parts.append(wav);captions.append((start,start+speech,text));print(name,round(total,2),'seconds',flush=True)
 block(BLOCKS[0])
 for beat in range(12):
  start=cursor;source_rows=[(i,r) for i,r in enumerate(p['shots']) if r['beat']==beat]
  for i,r in source_rows:
   clip=BASE/f'shot-{i:02d}.mp4';marker=clip.with_suffix('.sha256')
   if not marker.exists() or marker.read_text().rsplit(':',1)[-1]!=checksum(clip):raise ValueError('Approved source shot changed')
   if r['kind']=='foot':
    clean=OUT/f'base-foot-{i:02d}.mp4';clean_key=hashlib.sha256(code+json.dumps(r,sort_keys=True).encode()+checksum(Path(r['path'])).encode()).hexdigest()
    if not key_file(clean,clean_key):render_footage(clean,r,Path(r['path']),{'start':r['trim_start'],'seconds':r['seconds']});mark(clean,clean_key)
    clip=clean
   else:
    clean=OUT/f'base-graphic-{i:02d}.mp4';clean_row={**r,'text':''};clean_key=hashlib.sha256(code+json.dumps(clean_row,sort_keys=True).encode()).hexdigest()
    if not key_file(clean,clean_key):
     print(f'Rendering graphic {i+1} without descriptive headline',flush=True)
     asyncio.run(documentary.render(clean_row,clean,lambda name:(forecast.SOURCES/name).read_bytes(),composer=forecast.ForecastComposer(clean_row,p)));mark(clean,clean_key)
    clip=clean
   append(clip,{**r,'base_shot':i,'descriptive_headline_visible':False,**({'source_credit_on_footage':False} if r['kind']=='foot' else {})})
  audio_parts.append(BASE/f'voice-{beat:02d}.wav');text=(BASE/f'voice-{beat:02d}.txt').read_text();captions.append((start,cursor,text))
  for b in BLOCKS[1:]:
   if b[1]==beat:block(b)
 disclaimer=bank['non_endorsement_disclaimer'];path=OUT/'credits.mp4';footage_credits(path,bank,p,7);append(path,{'kind':'credits','text':disclaimer});silence=OUT/'silence.wav';ff('-f','lavfi','-i','anullsrc=r=48000:cl=mono','-t',7,silence);audio_parts.append(silence)
 for name,parts in [('video',video_parts),('audio',audio_parts)]: (OUT/(name+'-concat.txt')).write_text(''.join("file '"+str(path)+"'\n" for path in parts))
 ff('-f','concat','-safe',0,'-i',OUT/'audio-concat.txt','-af','loudnorm=I=-16:TP=-1.5:LRA=9','-ar',48000,'-ac',1,OUT/'narration.wav')
 final=OUT/'florida-clips-stats-maps-smooth.mp4';temp=OUT/'florida-clips-stats-maps.tmp.mp4'
 ff('-f','concat','-safe',0,'-i',OUT/'video-concat.txt','-i',OUT/'narration.wav','-f','lavfi','-i',score_filter(cursor),'-filter_complex',f'[2:a]loudnorm=I=-30:TP=-5:LRA=6,afade=t=in:d=2,afade=t=out:st={cursor-3}:d=3[bed];[1:a][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.84:level=0[a]','-map','0:v','-map','[a]','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-r',30,'-fps_mode','cfr','-c:a','aac','-ar',48000,'-t',cursor,'-movflags','+faststart',temp)
 qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(temp),'-vf','blackdetect=d=0.01:pix_th=0.02:pic_th=0.98','-f','null','-'],capture_output=True,check=True);(OUT/'qc.log').write_bytes(qc.stderr)
 if b'black_start:' in qc.stderr:raise ValueError('Unexpected black frame interval')
 v=next(s for s in probe(temp)['streams'] if s['codec_type']=='video');assert int(v['nb_frames'])==sum(r['frames'] for r in rows);assert abs(float(v['duration'])-cursor)<.05;temp.replace(final)
 manifest={'title':'Florida: clips, statistics and maps','recorded_forecast_collected_at':p['collected_at'],'archived_review':True,'shots':rows,'seconds':cursor,'voice':'Free macOS Samantha / 150 wpm','paid_generation_calls':0,'descriptive_headlines_visible':False,'footage_credit_placement':'End credits and source manifest; no source or creator text over footage','illustrative_footage_sources':p['media'],'footage_sources':[{'id':a['id'],'metadata':a['metadata'],'catalog':a['catalog']} for a in bank['assets'] if a['id'] in {id for block in BLOCKS for id,_ in block[4]}],'sources':p['sources'],'footage_bank':'docs/FLORIDA_FOOTAGE_BANK.json','limitations':['Historical clips explain hazards; they do not document the recorded forecast storm.','Rendering does not refresh the forecast.','Archive images do not establish measured rain or surge heights.','Lower-resolution originals are resized for the 1080p edit.'],'output':{'path':str(final),'checksum':checksum(final),'frames':int(v['nb_frames']),'seconds':float(v['duration']),'full_decode':True,'black_check':True}}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(OUT/'script.txt').write_text('\n\n'.join(text for _,_,text in captions));(OUT/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{srt_time(a)} --> {srt_time(b)}\n{text}' for i,(a,b,text) in enumerate(captions))+'\n');print(final,flush=True)
if __name__=='__main__':run()
