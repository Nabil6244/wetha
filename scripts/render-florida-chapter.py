#!/usr/bin/env python3
"""Free, reproducible South Florida chapter; source-pinned facts and distinct clips."""
import asyncio,hashlib,json,math,subprocess,sys,wave
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import documentary
from app.broadcast import SIZE,label,font,map_base,map_point,easing
from app.production import probe,checksum,srt_time
from app.weather import parse_nhc
from app.forecast_archive import parse
from app.regional import catalogue
from app.cinematic import score_filter
SOURCES=ROOT/'.local/florida/sources';MEDIA=ROOT/'.local/florida/media';OUT=ROOT/'.local/exports/florida-chapter'
NWS='https://www.weather.gov/mfl/Isaias2020';NHC='https://www.nhc.noaa.gov/data/tcr/AL092020_Isaias.pdf'
ASSETS=[
 {'id':'15820691','location':'Miami Beach','author':'paashuu','published':'2023-03-05','page':'https://www.pexels.com/video/the-beach-and-city-skyline-from-an-aerial-view-15820691/','download':'https://videos.pexels.com/video-files/15820691/15820691-uhd_3840_2160_60fps.mp4'},
 {'id':'33840195','location':'West Palm Beach','author':'Chris TheIsland','published':'2025-09-09','page':'https://www.pexels.com/video/aerial-view-of-west-palm-beach-coastline-33840195/','download':'https://videos.pexels.com/video-files/33840195/14361052_3840_2160_30fps.mp4'},
 {'id':'9431769','location':'Miami coastline','author':'Mikhail Nilov','published':'2021-09-03','page':'https://www.pexels.com/video/drone-footage-of-a-beach-9431769/','download':'https://videos.pexels.com/video-files/9431769/9431769-uhd_2560_1440_24fps.mp4'},
 {'id':'15999293','location':'Miami Beach','author':'paashuu','published':'2023-03-19','page':'https://www.pexels.com/video/the-beach-and-city-of-miami-from-an-aerial-view-15999293/','download':'https://videos.pexels.com/video-files/15999293/15999293-uhd_3840_2160_30fps.mp4'}]
# Each spoken paragraph is timed from its generated audio, rather than an estimate.
BEATS=[
 ('The center stayed offshore. The coast still felt it.',
  'A storm can miss the shoreline and still leave its mark. In August twenty twenty, South Florida faced that exact situation. The center of the storm stayed offshore. But what actually reached the coast?',
  [('foot',0),('track',None),('foot',2)]),
 ('A track is only part of the threat.',
  'The Miami weather office places the closest approach about thirty to forty miles east of the Palm Beach County coast, on August second. That distance tells us where the center went. It does not describe every neighborhood.',
  [('track',None),('foot',1),('track',None)]),
 ('Forecast first. Measurements later.',
  'On August first, a hurricane warning covered the coast from Boca Raton northward. This is the official forecast as it looked then. The purple cone follows possible center positions. Wind and rain can reach beyond it.',
  [('warnings',None),('forecast',None),('foot',0)]),
 ('Dania Pier: a brief burst of wind.',
  'Now look at the instruments. The final hurricane center report lists a fifty knot gust at Dania Pier. That converts to roughly fifty eight miles per hour. A gust is a short burst, rather than a sustained reading.',
  [('foot',3),('stations',0),('foot',2)]),
 ('Lake Worth: a different measurement.',
  'At Lake Worth, the report lists sustained winds of thirty six knots, about forty one miles per hour. These are different stations and different measurements. They should never be edited together as if the storm accelerated from one number to the next.',
  [('stations',1),('foot',1),('foot',3)]),
 ('One coastline. Uneven exposure.',
  'Farther north, Stuart Beach recorded forty two knot sustained winds, roughly forty eight miles per hour. The station map makes the pattern more useful: the readings belong to specific coastal sites, rather than to all of Florida.',
  [('stations',2),('foot',1),('stations',2)]),
 ('Why was the storm uneven?',
  'So why did the center pass so close without delivering the same conditions everywhere? The Miami weather office describes strong upper level winds and dry air west of the storm. The strongest winds and heaviest rain remained east, over the Bahamas.',
  [('mechanism',None),('foot',0),('mechanism',None)]),
 ('Rainfall stayed below three inches in Florida.',
  'The final hurricane report says Florida storm rainfall totals stayed below three inches. That is a statewide summary, not a total at every address. We are keeping it separate from the local pier measurements, and from any current forecast.',
  [('foot',2),('rain',None),('foot',0)]),
 ('Warnings changed as the situation changed.',
  'By five in the morning on August second, Palm Beach had moved from a hurricane warning to a tropical storm warning. By eleven, the Miami office says warnings from Palm Beach County south had ended. These are the historical warning decisions.',
  [('warnings',None),('timeline',None),('foot',1)]),
 ('A weaker local impact still left consequences.',
  'For South Florida, the Miami office describes mostly minor wind and flood impacts. It also reports beach erosion, most notably in northern Palm Beach County. The outcome was less severe locally, but the coast was not untouched.',
  [('foot',1),('impact',None),('foot',0)]),
 ('The center forecast and the local experience differ.',
  'The lesson is in the gap between the track and the instruments. A center offshore, exposed coastal stations, and an uneven storm structure can tell different parts of the same story. Matching each number to its place changes what the viewer understands.',
  [('track',None),('stations',3),('foot',3)]),
 ('Place. Time. Measurement. That is the story.',
  'For this coast, the story is not a single hurricane number. It is where the wind reached, how the warnings evolved, and what was measured afterward. This is a historical South Florida chapter, with later coastal footage clearly labeled for illustration.',
  [('foot',0),('stations',3),('foot',1)])]
STATIONS=[
 {'id':'XDAN','name':'DANIA PIER','coordinates':[-80.11,26.05],'knots':50,'measurement':'PEAK GUST','mph':58,'page':27,'detail':'50 kt → 58 mph · Weatherflow'},
 {'id':'LKWF1','name':'LAKE WORTH','coordinates':[-80.03,26.61],'knots':36,'measurement':'SUSTAINED','mph':41,'page':26,'detail':'36 kt → 41 mph · NOS · 10 m'},
 {'id':'STUART','name':'STUART BEACH','coordinates':[-80.17,27.20],'knots':42,'measurement':'SUSTAINED','mph':48,'page':27,'detail':'42 kt → 48 mph · Weather Stem'}]

def ff(*args):subprocess.run(['ffmpeg','-y','-v','error',*map(str,args)],check=True)

def evidence():
 lock=SOURCES/'chapter-checksums.json'
 names=['nws-miami.html','isaias-tcr.pdf','isaias-tcr.txt','nhc18.html','nhc20.html','nhc22.html','forecast-018.zip']
 pins={n:checksum(SOURCES/n) for n in names}
 if lock.exists() and json.loads(lock.read_text())!=pins:raise ValueError('Pinned evidence changed.')
 lock.write_text(json.dumps(pins,indent=2))
 advisories=[]
 for n in [18,20,22]:
  url=f'https://www.nhc.noaa.gov/archive/2020/al09/al092020.public.{n:03}.shtml'
  a=parse_nhc((SOURCES/f'nhc{n}.html').read_text(),url,'official_fetch')
  assert a.event_key=='AL092020' and a.issued_at.strftime('%Y-%m-%d') in ['2020-08-01','2020-08-02']
  advisories.append(a)
 geo=parse((SOURCES/'forecast-018.zip').read_bytes(),advisories[0])
 pages=(SOURCES/'isaias-tcr.txt').read_text().split('\f')
 # Validate the exact source table excerpts; station values are not storm-wide intensity.
 import re
 for s,pattern in zip(STATIONS,[r'Dania Pier \(XDAN\).*?32\s*\(5 min, 9 m\)\s*50',r'Lake Worth \(LKWF1\).*?36\s*\(10 m\)\s*46',r'Stuart Beach.*?42\s*45']):
  assert re.search(pattern,pages[s['page']-1],re.S),s['name']
  assert round(s['knots']*1.150779448)==s['mph']
  assert -81<s['coordinates'][0]<-79 and 25<s['coordinates'][1]<28
 assert 'below 3 inches' in pages[6] or 'less than 3 inches' in pages[6] or 'under 3 inches' in pages[6]
 for m in ASSETS:
  path=MEDIA/(m['id']+'.mp4');m.update(checksum=checksum(path),seconds=float(probe(path)['format']['duration']),region_codes=['FL'],location_reviewed=True,
   context='illustrative; not Isaias event footage',license='Pexels License',license_url='https://www.pexels.com/license/',captured_at=None,
   location_evidence='Source page description identifies '+m['location']+'; visually reviewed coastline; publication date is not capture date.')
 media_lock=SOURCES/'media-checksums.json'
 media_pins={a['id']:a['checksum'] for a in ASSETS}
 if media_lock.exists() and json.loads(media_lock.read_text())!=media_pins:raise ValueError('Pinned Florida footage changed.')
 media_lock.write_text(json.dumps(media_pins,indent=2))
 return pins,advisories,geo


class FloridaComposer:
 def __init__(self,row,advisories,geo):self.row=row;self.advisories=advisories;self.geo=geo
 def frame(self,t):
  r=self.row;mode=r['kind'];target=r.get('target');bounds=documentary.viewport(r['camera_start'],r['camera_end'],t)
  im=map_base(bounds).copy();layer=Image.new('RGBA',SIZE);d=ImageDraw.Draw(layer)
  fl=next(x for x in catalogue()['regions'] if x['code']=='FL')
  for ring in fl['rings']:
   pts=[map_point(c,bounds) for c in ring];d.polygon(pts,fill=(33,69,78,230));d.line(pts,fill='#6a9ba4',width=2)
  label(d,(90,480),'FLORIDA',34,'#b5d8dd')
  if mode=='track':
   pts=[map_point([a.facts['longitude'],a.facts['latitude']],bounds) for a in self.advisories]
   u=easing(min(1,t*1.3))*(len(pts)-1);idx=min(int(u),len(pts)-2);f=u-idx
   partial=pts[:idx+1]+[(pts[idx][0]+(pts[idx+1][0]-pts[idx][0])*f,pts[idx][1]+(pts[idx+1][1]-pts[idx][1])*f)]
   d.line(partial,fill='#82efdc',width=7)
   for a,(x,y) in zip(self.advisories,pts):
    d.ellipse((x-8,y-8,x+8,y+8),fill='#fff')
    label(d,(x+17,y+8),a.issued_at.strftime('%d AUG / %H:%M UTC'),24)
   x,y=partial[-1];radius=15+8*math.sin(math.pi*t);d.ellipse((x-radius,y-radius,x+radius,y+radius),outline='#82efdc',width=4)
   label(d,(65,870),'Reported centers / connectors are presentation',26,'#82efdc')
   label(d,(65,920),'NHC advisories 18, 20, 22 / 01–02 AUG 2020',26)
  elif mode in ['warnings','forecast']:
   colors={'HWR':'#ff6375','TWR':'#ffb06c','TWA':'#ffe388','HWA':'#ffe388'}
   for feature in self.geo['features']:
    p=feature['properties'];g=feature['geometry']
    if p['kind']=='forecast_cone' and mode=='forecast':
     for ring in g['coordinates']:
      pts=[map_point(c,bounds) for c in ring];d.polygon(pts,fill=(174,125,238,60));d.line(pts,fill='#dcc4ff',width=3)
    if p['kind']=='warning_coast' and mode=='warnings':
     for line in g['coordinates']:
      pts=[map_point(c,bounds) for c in line];n=max(2,math.ceil(len(pts)*easing(min(1,t*1.7))))
      d.line(pts[:n],fill=colors.get(p['TCWW'],'#fff'),width=10)
   if mode=='forecast':
    pred=sorted([f for f in self.geo['features'] if f['properties']['kind']=='forecast_point'],key=lambda f:f['properties']['valid_time'])
    pts=[map_point(f['geometry']['coordinates'],bounds) for f in pred];n=max(1,math.ceil(len(pts)*t*1.5))
    if n>1:d.line(pts[:n],fill='#dcc4ff',width=5)
    for x,y in pts[:n]:d.ellipse((x-7,y-7,x+7,y+7),fill='#fff')
    label(d,(65,850),'Cone: center forecast / impacts can extend outside',27,'#dcc4ff')
   else:
    label(d,(65,810),'Hurricane warning',28,'#ff6375');label(d,(65,853),'Tropical storm warning',28,'#ffb06c');label(d,(65,896),'Watch',28,'#ffe388')
   label(d,(65,950),'AS ISSUED / 01 AUG 2020 / 15:00 UTC',25)
  elif mode=='stations':
   for i,s in enumerate(STATIONS):
    x,y=map_point(s['coordinates'],bounds);active=target==3 or i==target;color='#82efdc' if active else '#7a9ba5'
    radius=10+(5*math.sin(t*math.pi)**2 if active else 0);d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
    x2=max(930,x+85);d.line([(x+15,y),(x2-15,y)],fill=color,width=2)
    label(d,(x2,y-28),s['name'],27,color)
    label(d,(x2,y+8),f"{s['mph']} mph / {s['measurement']}",32,color)
   s=STATIONS[target] if target!=3 else None
   if s:
    label(d,(65,650),s['measurement']+' / '+s['name'],28,'#82efdc');label(d,(65,700),str(s['mph'])+' mph',92)
    label(d,(65,820),s['detail'],26);label(d,(65,875),'Different averaging periods / not a time series',25,'#b5d8dd')
   else:label(d,(65,910),'Specific stations / gusts and sustained readings differ',26,'#82efdc')
  elif mode=='mechanism':
   center=map_point([-79.6,26.9],bounds);x,y=center
   for off in [-95,0,95]:
    ax=70+(t*280+off)%470;ay=390+off
    d.line([(ax,ay),(ax+180,ay)],fill='#ffe388',width=7);d.polygon([(ax+180,ay),(ax+158,ay-15),(ax+158,ay+15)],fill='#ffe388')
   d.arc((x-100,y-100,x+100,y+100),int(t*360),int(t*360)+250,fill='#82efdc',width=9)
   label(d,(65,610),'UPPER LEVEL WINDS',31,'#ffe388');label(d,(65,664),'Dry air west of the storm',29,'#ffe388')
   label(d,(1100,750),'Strongest winds / heaviest rain',28,'#82efdc');label(d,(1100,797),'East, over the Bahamas',28,'#82efdc')
   label(d,(65,925),'EXPLANATORY DIAGRAM / no modeled speeds or rain field',25)
  elif mode=='rain':
   label(d,(70,550),'FLORIDA / STORM TOTAL SUMMARY',27,'#82efdc');label(d,(65,610),'Under 3 inches',84)
   label(d,(70,728),'NHC final report / not a uniform rainfall map',29)
   label(d,(70,850),'No interpolated rainfall surface',27,'#b5d8dd')
  elif mode=='timeline':
   for i,(stamp,text) in enumerate([('05:00 EDT','Palm Beach: hurricane → tropical storm warning'),('11:00 EDT','Palm Beach County south: warnings ended')]):
    y=550+i*190;x=75+int(25*(1-easing(t)));label(d,(x,y),stamp+' / 02 AUG',42,'#82efdc');label(d,(x,y+66),text,30)
   d.line((80,920,80+1650*easing(t),920),fill='#82efdc',width=4)
  elif mode=='impact':
   label(d,(70,620),'NORTHERN PALM BEACH COUNTY',32,'#82efdc');label(d,(65,690),'Beach erosion',76)
   label(d,(70,815),'NWS Miami / local post-storm summary',29)
  else:raise ValueError(mode)
  # Keep geographic overlays inside the picture safe area.
  alpha=layer.getchannel('A');mask=Image.new('L',SIZE);mask.paste(alpha.crop((0,235,1920,990)),(0,235));layer.putalpha(mask)
  im=Image.alpha_composite(im.convert('RGBA'),layer).convert('RGB')
  return documentary.overlay(im,r,t)


def prepare():
 OUT.mkdir(parents=True,exist_ok=True);pins,advisories,geo=evidence();rows=[];cursor=0;trims={a['id']:0 for a in ASSETS};narration=[];captions=[]
 for b,(title,text,shots) in enumerate(BEATS):
  aiff=OUT/f'voice-{b:02}.aiff';txt=OUT/f'voice-{b:02}.txt';txt.write_text(text)
  key=hashlib.sha256(('Samantha/145/'+text).encode()).hexdigest();marker=aiff.with_suffix('.sha256')
  if not aiff.exists() or not marker.exists() or marker.read_text()!=key:
   subprocess.run(['/usr/bin/say','-v','Samantha','-r','145','-f',str(txt),'-o',str(aiff)],check=True);marker.write_text(key)
  speech=float(probe(aiff)['format']['duration']);frames=math.ceil((speech+.35)*30);length=frames/30
  wav=OUT/f'voice-{b:02}.wav';ff('-i',aiff,'-af',f'apad=whole_dur={length}', '-t',length,'-ar',48000,'-ac',1,wav)
  narration.append(wav);per=frames//len(shots);beat_start=cursor
  for j,(mode,target) in enumerate(shots):
   count=per+(frames%len(shots) if j==len(shots)-1 else 0);seconds=count/30
   row={'kind':mode,'target':target,'seconds':seconds,'start_seconds':cursor,'beat':b,'text':title,'header':'SOUTH FLORIDA / ISAIAS / 2020',
     'context':'HISTORICAL / 01–02 AUG 2020','credit':'NOAA / NHC & NWS Miami · Census 2024 state outline · historical case study',
     'weather_source_refs':[NHC,NWS],'camera_start':[-83.1,24.3,-77.3,28.5],'camera_end':[-82.1,24.5,-78.2,28.0]}
   if mode=='foot':
    m=ASSETS[target];start=trims[m['id']]
    assert start+seconds<=m['seconds'],(m['id'],start+seconds,m['seconds'])
    row.update(filename=m['id']+'.mp4',trim_start=start,context='ILLUSTRATIVE / '+m['location'].upper(),credit=m['author']+' / Pexels · '+m['location']+' · not Isaias event footage')
    trims[m['id']]+=seconds
    if b in [3,4]:
     st=STATIONS[b-3];row['stat']={'label':st['name']+' / '+st['measurement'],'value':str(st['mph'])+' mph','detail':st['detail']}
   elif mode=='forecast':row.update(camera_start=[-86,23,-72,35],camera_end=[-84,24,-74,33])
   elif mode=='stations':row.update(camera_start=[-82.3,25,-78.0,28.0],camera_end=[-82.0,25.1,-78.3,27.9])
   rows.append(row);cursor+=seconds
  # Sentence-level subtitle cues have measured beat timing; no claim of forced alignment.
  import re
  sentences=re.split(r'(?<=[.?]) +',text);words=sum(len(x.split()) for x in sentences);offset=beat_start
  for sentence in sentences:
   dur=speech*len(sentence.split())/words;captions.append((offset,offset+dur,sentence));offset+=dur
 assert 120<=cursor<=180, cursor
 (OUT/'voice-concat.txt').write_text(''.join(f"file '{p.name}'\n" for p in narration))
 ff('-f','concat','-safe',1,'-i',OUT/'voice-concat.txt','-af','loudnorm=I=-16:TP=-1.5:LRA=9','-ar',48000,'-ac',1,OUT/'narration.wav')
 manifest={'title':'South Florida / The center stayed offshore','event_id':'AL092020','historical':True,'region_codes':['FL'],'seconds':round(cursor,3),'shots':rows,'stations':STATIONS,
 'media':ASSETS,'source_pins':pins,'sources':[{'url':NWS,'path':str(SOURCES/'nws-miami.html')},{'url':NHC,'path':str(SOURCES/'isaias-tcr.pdf')}],
 'official_advisories':[{'url':a.source_url,'issued_at':a.issued_at.isoformat(),'checksum':pins[f'nhc{n}.html']} for n,a in zip([18,20,22],advisories)],
 'official_forecast':{'url':'https://www.nhc.noaa.gov/gis/forecast/archive/al092020_5day_018.zip','issued_at':geo['issued_at'],'advisory':18},
 'voice':{'engine':'macOS say','voice':'Samantha','rate':145,'paid_calls':0,'path':str(OUT/'narration.wav')},'paid_generation_calls':0,
 'limitations':['Later Florida coastline footage is illustrative, not an Isaias capture. Source publication dates are not capture dates.',
 'Station readings have different averaging periods and observation times. They are not an intensity time series.',
 'NWS and NHC disagree on exact Dania gust time; the chapter omits that time.',
 'NWS rain table and prose disagree on accumulation interval; individual NWS rain totals were omitted.',
 'Rain caption is NHC statewide storm-total summary, not a localized rain surface.',
 'Camera paths, arrows and center connectors are presentation; no synthetic radar or interpolated observation frames.',
 'Sentence subtitles are approximately positioned inside individually measured narration paragraphs.',
 'Forecast and warning map is advisory 18, not the later warning decision or a current forecast.']}
 (OUT/'plan.json').write_text(json.dumps(manifest,indent=2))
 (OUT/'script.txt').write_text('\n\n'.join(t+'\n'+s for t,s,_ in BEATS))
 (OUT/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{srt_time(a)} --> {srt_time(b)}\n{text}' for i,(a,b,text) in enumerate(captions))+'\n')
 print('Prepared',round(cursor,2),'seconds;',len(rows),'shots',flush=True)
 return manifest,advisories,geo


async def run():
 p,advisories,geo=prepare()
 if '--prepare' in sys.argv:return
 code=Path(__file__).read_bytes()+Path(documentary.__file__).read_bytes()
 for i,r in enumerate(p['shots']):
  out=OUT/f'shot-{i:02}.mp4';marker=out.with_suffix('.sha256');key=hashlib.sha256(json.dumps(r,sort_keys=True).encode()+code).hexdigest()
  cached=out.exists() and marker.exists() and marker.read_text()==key+':'+checksum(out)
  print(f'Shot {i+1}/{len(p["shots"])}: '+('cached' if cached else r['kind']),flush=True)
  if not cached:
   await documentary.render(r,out,lambda name:(SOURCES/name).read_bytes(),MEDIA/r['filename'] if r['kind']=='foot' else None,
     None if r['kind']=='foot' else FloridaComposer(r,advisories,geo))
   v=next(s for s in probe(out)['streams'] if s['codec_type']=='video');assert int(v['nb_frames'])==round(r['seconds']*30)
   marker.write_text(key+':'+checksum(out))
 (OUT/'concat.txt').write_text(''.join(f"file 'shot-{i:02}.mp4'\n" for i in range(len(p['shots']))))
 seconds=p['seconds'];video=OUT/'south-florida-chapter.mp4'
 ff('-f','concat','-safe',1,'-i',OUT/'concat.txt','-i',OUT/'narration.wav','-f','lavfi','-i',score_filter(seconds),
   '-filter_complex',f'[2:a]loudnorm=I=-30:TP=-5:LRA=6,afade=t=in:d=2,afade=t=out:st={seconds-3}:d=3[bed];[1:a][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.84:level=0[a]',
   '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-ar',48000,'-t',seconds,'-movflags','+faststart',video)
 v=next(s for s in probe(video)['streams'] if s['codec_type']=='video');frames=sum(round(r['seconds']*30) for r in p['shots'])
 assert (v['width'],v['height'],int(v['nb_frames']))==(1920,1080,frames)
 assert abs(float(v['duration'])-seconds)<.05
 qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-af','ebur128=peak=true','-f','null','-'],capture_output=True,check=True)
 (OUT/'qc.log').write_bytes(qc.stderr);assert b'black_start:' not in qc.stderr
 p['output']={'path':str(video),'checksum':checksum(video),'seconds':float(v['duration']),'frames':frames,'width':1920,'height':1080,'fps':30,'full_decode':True,'black_check':True}
 (OUT/'manifest.json').write_text(json.dumps(p,indent=2))
 sheet=Image.new('RGB',(1600,1440))
 for i,r in enumerate(p['shots']):
  frame=OUT/f'frame-{i:02}.jpg';ff('-ss',r['start_seconds']+r['seconds']*.6,'-i',video,'-frames:v',1,'-vf','scale=320:180',frame)
  sheet.paste(Image.open(frame),((i%5)*320,(i//5)*180))
 sheet.save(OUT/'contact.jpg');print(video,flush=True)

if __name__=='__main__':asyncio.run(run())
