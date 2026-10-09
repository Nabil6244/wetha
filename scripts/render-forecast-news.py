#!/usr/bin/env python3
"""Narrated, timestamped Florida forecast news from one immutable official snapshot."""
import asyncio,hashlib,importlib.util,json,math,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import documentary
from app.broadcast import SIZE,label,map_base,map_point,easing
from app.forecast_news import stamp,snapshot_status
from app.regional import catalogue
from app.production import checksum,probe,srt_time
from app.cinematic import score_filter
from app.forecast_graphics import STAT_MODES, render_stat, rain_gap, alert_counts
from app import forecast_graphics
SOURCES=ROOT/'.local/forecast-news/sources';MEDIA=ROOT/'.local/forecast-news/media';OUT=ROOT/'.local/exports/forecast-news'


def ff(*args):subprocess.run(['ffmpeg','-y','-v','error',*map(str,args)],check=True)

def media():
 p=json.load(open(ROOT/'.local/exports/florida-chapter/manifest.json'))
 assets=[{**a,'path':str(ROOT/'.local/florida/media'/(a['id']+'.mp4'))} for a in p['media']]
 assets +=[
 {'id':'31040646','location':'Panama City Beach, Florida','author':'Jabriel','page':'https://www.pexels.com/video/aerial-view-of-panama-city-beach-at-sunrise-31040646/','path':str(MEDIA/'31040646.mp4'),'location_evidence':'Source description identifies Panama City Beach, Florida at sunrise.'},
 {'id':'2425846','location':'Panama City Beach, Florida','author':'Ruvim M','page':'https://www.pexels.com/video/aerial-view-of-a-beach-waterfront-2425846/','path':str(MEDIA/'2425846.mp4'),'location_evidence':'Source page location tag: Panama City Beach. Visually reviewed matching Florida beachfront.'}]
 for a in assets:
  a.update(seconds=float(probe(a['path'])['format']['duration']),checksum=checksum(a['path']),license='Pexels License',license_url='https://www.pexels.com/license/',region_codes=['FL'],context='illustrative; not a current storm or observation',captured_at=None)
 return assets


def build_beats(p):
 s={x['hours']:x for x in p['snapshots']};cities={x['id']:x for x in p['cities']}
 def f(h,city,key):return next(x for x in s[h]['points'] if x['id']==city)['forecast'][key]
 def num(v):return str(round(v))
 storm=p['nhc'][0] if p['nhc'] else None
 if not storm:raise ValueError('This hurricane-led story needs a current NHC storm. Choose a new editorial story for a quiet-weather snapshot.')
 a=storm['latest'];text=a['text']
 # Do not turn a fixed story into unsupported copy if the next collection differs.
 required=['Florida Panhandle','Big Bend','4 to 8 inches','up to 15 inches','5-7 ft','Indian Pass','tonight or early Saturday']
 if any(x not in text for x in required):raise ValueError('This snapshot no longer supports the hurricane-led script; revise its sourced story.')
 event=a['event_key'];assert event=='AL092026' and a['issued_at'].startswith('2026-10-09')
 warning=a['facts']['warnings_summary'];assert 'Bay/Gulf County Line' in warning and 'Hurricane Warning' in warning
 ref=s[6]['valid_at'];clock=stamp(ref).strftime('%H:%M UTC')
 # Each visual remains tied to either a forecast hour or the NHC product issue.
 return [
 ('A Gulf-coast threat. Different forecasts across Florida.',
  'Florida faces very different forecasts today. The hurricane center reports a Gulf Coast threat, while local conditions vary across the state. Here is what the official forecasts say could happen next, and when.',
  [('foot', 4), ('rain-contrast', 6), ('cone', 0)]),
 ('The storm report is not a city wind reading.',
  f"The latest hurricane bulletin reports maximum sustained winds near {a['facts']['wind_mph']} miles per hour. The pressure is {a['facts']['pressure_mb']} millibars, and forward motion is {a['facts']['movement_mph']} miles per hour. These are three different storm measurements, not Florida city conditions.",
  [('center', 0), ('storm-facts', 0), ('foot', 5)]),
 ('Friday night into early Saturday: the forecast window.',
  'The bulletin expects landfall within the warning area tonight or early Saturday. The official cone shows the forecast center. Warning lines identify the coastal threat. Impacts can extend outside the cone, so it is not a safety boundary.',
  [('warnings', 0), ('forecast-window', 0), ('forecast-scope', 0)]),
 ('Storm surge: location and conditions matter.',
  'For the coast from Dauphin Island to Indian Pass, the bulletin gives a five to seven foot water-height range above ground, if peak surge coincides with high tide. That conditional range is not a prediction for every property.',
  [('surge-height', 0), ('foot', 4), ('source-clock', 0)]),
 ('Forecast rainfall: a total through the weekend.',
  'For the Florida Panhandle and Big Bend, the bulletin forecasts four to eight inches of rain through the weekend, with localized totals up to fifteen possible. Those are forecast amounts across a region, not measurements already recorded.',
  [('rainfall-range', 0), ('foot', 5), ('alert-counts', 0)]),
 ('Next six hours: compare the city forecasts.',
  f"Now compare the city forecasts at {clock.replace(':00 UTC',' hundred U T C')}. Panama City's hourly rain chance is {num(f(6,'panama-city','rain_probability'))} percent; Miami's is {num(f(6,'miami','rain_probability'))} percent. That is an {num(rain_gap(p,6))} percentage point gap between two grid forecasts, not the share of Florida covered by rain.",
  [('rain-ranking', 6), ('rain', 6), ('foot', 2)]),
 ('Twelve hours: the forecast changes by location.',
  f"At the twelve hour forecast checkpoint, Pensacola's rain chance is {num(f(12,'pensacola','rain_probability'))} percent. Panama City's is {num(f(12,'panama-city','rain_probability'))} percent. At the same hour, Orlando is {num(f(12,'orlando','rain_probability'))} percent. The heatmap compares six supplied forecast hours across eight local grid points.",
  [('rain-matrix', 12), ('wind-ranges', 12), ('forecast-timeline', 12)]),
 ('Local winds: keep the place and period attached.',
  f"At the twenty four hour checkpoint, the Pensacola grid point forecasts winds of {f(24,'pensacola','wind_mph')[1]} miles per hour. That hourly forecast is separate from the storm's central wind estimate. Use local warnings alongside it, not a single point as a complete risk assessment.",
  [('wind', 24), ('wind-ladder', 24), ('wind-direction', 24)]),
 ('South Florida has its own forecast.',
  f"In Miami, the twelve hour point forecast is {f(12,'miami','temperature_f')} degrees Fahrenheit, with a {num(f(12,'miami','rain_probability'))} percent rain chance. West Palm Beach has a {num(f(12,'west-palm','rain_probability'))} percent chance. Florida's forecast deserves more than one statewide weather number.",
  [('foot', 0), ('temperature-strip', 12), ('south-cards', 12)]),
 ('Forty-eight hours: another forecast checkpoint.',
  f"At forty eight hours, Tampa's point rain chance is {num(f(48,'tampa','rain_probability'))} percent, compared with {num(f(48,'miami','rain_probability'))} percent in Miami. A lower number elsewhere does not cancel coastal flooding or other hazards. Each forecast layer answers a different question.",
  [('rain-lollipops', 48), ('temperature-heat', 48), ('foot', 3)]),
 ('Seventy-two hours: a forecast, not a promise.',
  f"The seventy two hour view reaches Monday. Miami's point rain chance is {num(f(72,'miami','rain_probability'))} percent. Pensacola and Panama City are {num(f(72,'pensacola','rain_probability'))} and {num(f(72,'panama-city','rain_probability'))} percent. These are forecasts, not a promise of safe conditions. New information can change the outlook.",
  [('rain-dots', 72), ('wind-checkpoints', 72), ('foot', 1)]),
 ('Check the latest local warning before acting.',
  'The takeaway is place, timing, and the kind of threat. Check updated National Weather Service and hurricane center bulletins, and follow instructions from your local officials. This recorded forecast snapshot will need a refresh as the situation develops.',
  [('alerts', 0), ('takeaways', 0), ('outlook', 0)])]


class ForecastComposer:
 def __init__(self,row,p):self.r=row;self.p=p
 def frame(self,t):
  r=self.r;p=self.p;mode=r['kind']
  if mode in STAT_MODES:return documentary.overlay(render_stat(r,p,t),r,t)
  bounds=documentary.viewport(r['camera_start'],r['camera_end'],t)
  im=map_base(bounds).copy();layer=Image.new('RGBA',SIZE);d=ImageDraw.Draw(layer)
  for ring in next(x for x in catalogue()['regions'] if x['code']=='FL')['rings']:
   pts=[map_point(c,bounds) for c in ring];d.polygon(pts,fill=(33,69,78,235));d.line(pts,fill='#6a9ba4',width=2)
  storm=p['nhc'][0];features=storm['geometry']['features'];snapshot=next(x for x in p['snapshots'] if x['hours']==r['hours'])
  if mode in ['cone','warnings','center']:
   for f in features:
    g=f['geometry'];pr=f['properties']
    if pr['kind']=='forecast_cone' and mode=='cone':
     for ring in g['coordinates']:
      pts=[map_point(c,bounds) for c in ring];d.polygon(pts,fill=(174,125,238,65));d.line(pts,fill='#dcc4ff',width=3)
    if pr['kind']=='warning_coast' and mode=='warnings':
     for line in g['coordinates']:
      pts=[map_point(c,bounds) for c in line];n=max(2,math.ceil(len(pts)*easing(min(1,t*1.8))));d.line(pts[:n],fill='#ff6375' if pr['TCWW']=='HWR' else '#ffb06c',width=10)
   if mode=='cone':
    pred=sorted([f for f in features if f['properties']['kind']=='forecast_point'],key=lambda f:f['properties']['valid_time'])
    pts=[map_point(f['geometry']['coordinates'],bounds) for f in pred];n=max(1,math.ceil(len(pts)*min(1,t*1.6)))
    if n>1:d.line(pts[:n],fill='#dcc4ff',width=5)
    for f,(x,y) in zip(pred[:n],pts):
     d.ellipse((x-8,y-8,x+8,y+8),fill='#fff');label(d,(x+15,y+6),stamp(f['properties']['valid_time']).strftime('%d OCT %H:%M UTC'),24)
    label(d,(65,840),'Forecast center / cone is not an impact boundary',27,'#dcc4ff')
   elif mode=='warnings':
    label(d,(65,720),'HURRICANE WARNING',30,'#ff6375');label(d,(65,770),'TROPICAL STORM WARNING',30,'#ffb06c')
   else:
    a=storm['latest'];x,y=map_point([a['facts']['longitude'],a['facts']['latitude']],bounds)
    d.ellipse((x-14,y-14,x+14,y+14),fill='#ff6375');label(d,(x+22,y),'Reported storm center',27)
    label(d,(65,580),'ISAIAS / NHC STORM MAXIMUM SUSTAINED WIND',29,'#82efdc');label(d,(65,640),str(a['facts']['wind_mph'])+' mph',94)
    label(d,(65,775),'Not a Florida city wind measurement',29)
    label(d,(65,840),'REPORTED '+stamp(a['issued_at']).strftime('%d OCT %H:%M UTC'),27)
   if mode!='center':label(d,(65,920),'NHC FORECAST ISSUED '+stamp(storm['geometry']['issued_at']).strftime('%d OCT %H:%M UTC'),26)
  elif mode in ['rain','wind','temperature']:
   # Numbered pins refer to exact source grid points; no interpolated fields.
   displayed=snapshot['points'][:4] if mode=='wind' else snapshot['points']
   for i,point in enumerate(displayed):
    f=point['forecast'];color='#82efdc'
    if mode=='rain':val=f['rain_probability'];value='N/A' if val is None else str(round(val))+'%';color='#ffb06c' if val is not None and val>=60 else '#82efdc'
    elif mode=='wind':value=str(f['wind_mph'][0])+('–'+str(f['wind_mph'][1]) if f['wind_mph'][1]!=f['wind_mph'][0] else '')+' mph'
    else:value=str(f['temperature_f'])+'°F'
    x,y=map_point(point['coordinates'],bounds)
    d.ellipse((x-14,y-14,x+14,y+14),fill=color);label(d,(x-7,y-12),str(i+1),23,'#081d2c')
    # The city list is outside the geographic layer, avoiding false placement.
    if mode=='wind':
     label(d,(x+22,y-18),point['name'].upper(),25,color);label(d,(x+22,y+20),value,35,color)
    else:
     yy=335+i*68;label(d,(65,yy),str(i+1)+'  '+point['name'].upper(),27,color);label(d,(440,yy-3),value,34,color)
   desc={'rain':'HOURLY PRECIPITATION CHANCE','wind':'HOURLY FORECAST WIND','temperature':'HOURLY FORECAST TEMPERATURE'}[mode]
   label(d,(65,260),desc,31,'#fff')
   label(d,(65,925),('4 northern grid points' if mode=='wind' else '8 grid points')+' / no inferred field between points',26,'#b5d8dd')
  elif mode in ['rain-total','surge']:
   if mode=='rain-total':
    label(d,(65,480),'PANHANDLE & BIG BEND / THROUGH THE WEEKEND',28,'#82efdc');label(d,(65,545),'4–8 inches',96)
    label(d,(65,675),'Localized totals up to 15 inches possible',30,'#ffb06c');label(d,(65,750),'Forecast amount / not a recorded total',29)
   else:
    label(d,(65,475),'DAUPHIN ISLAND, AL → INDIAN PASS, FL',28,'#ffb06c');label(d,(65,545),'5–7 feet',96)
    label(d,(65,680),'Above ground / if peak surge occurs at high tide',29);label(d,(65,750),'Conditional coastal range / not every property',28)
   label(d,(65,915),'NHC PUBLIC BULLETIN '+stamp(storm['latest']['issued_at']).strftime('%d OCT %H:%M UTC'),26)
  elif mode=='alerts':
   shown=0
   for a in p['alerts']:
    g=a.get('geometry')
    if not g or g['type'] not in ['Polygon','MultiPolygon']:continue
    polys=g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]
    color=(255,99,117,65) if 'Warning' in a['event'] else (255,176,108,40)
    for poly in polys:
     pts=[map_point(c,bounds) for c in poly[0]];d.polygon(pts,fill=color);d.line(pts,fill=color[:3]+(210,),width=2)
    shown+=1
   types=sorted(set(a['event'] for a in p['alerts'] if a['event'] in ['Hurricane Warning','Storm Surge Warning','Flood Watch','Tropical Storm Warning']))
   label(d,(65,460),'NWS / ALERT SNAPSHOT',34,'#ffb06c')
   for i,name in enumerate(types):label(d,(65,535+i*60),name,35)
   label(d,(65,850),'Only source-supplied polygons shown',27,'#b5d8dd');label(d,(65,900),'Other zone-based alerts are listed in the source pack',25)
  elif mode=='trend':
   # Repeated source hours, never a fabricated continuous data series.
   pc=[next(x for x in s['points'] if x['id']=='panama-city')['forecast']['rain_probability'] for s in p['snapshots']]
   label(d,(65,310),'PANAMA CITY / RAIN CHANCE CHECKPOINTS',30,'#82efdc')
   for i,(s,v) in enumerate(zip(p['snapshots'],pc)):
    yy=390+i*77;color='#82efdc' if s['hours']<=r['hours'] else '#89a8b2';label(d,(65,yy),f"+{s['hours']:02} hours",28,color)
    if v is not None:
     width=round(400*v/100)*easing(min(1,t*1.8));d.rectangle((290,yy,290+width,yy+29),fill=color);label(d,(735,yy-3),str(round(v))+'%',31,color)
   label(d,(65,935),'Discrete forecast hours / not rainfall totals',27)
  elif mode=='outlook':
   label(d,(65,475),'PLACE → TIME → THREAT',58,'#82efdc')
   label(d,(65,590),'Forecasts and warnings can change',33);label(d,(65,662),'Check the latest official local bulletin',33)
   label(d,(65,820),'RECORDED SOURCE SNAPSHOT',29,'#ffb06c');label(d,(65,875),stamp(p['collected_at']).strftime('%d OCT %Y / %H:%M UTC'),29)
  else:raise ValueError(mode)
  alpha=layer.getchannel('A');mask=Image.new('L',SIZE);mask.paste(alpha.crop((0,235,1920,985)),(0,235));layer.putalpha(mask)
  im=Image.alpha_composite(im.convert('RGBA'),layer).convert('RGB')
  return documentary.overlay(im,r,t)


def prepare():
 OUT.mkdir(parents=True,exist_ok=True);p=json.load(open(SOURCES/'snapshot.json'));now=datetime.now(timezone.utc)
 if snapshot_status(p,now)['status']=='refresh_needed' and '--archived-review' not in sys.argv:raise ValueError('Snapshot needs recollection before starting a render.')
 for source in p['sources']:
  if checksum(SOURCES/source.get('archived_file',source['filename']))!=source['checksum']:raise ValueError('Official source bytes changed after collection.')
 p['visual_revision']=2;p['archived_review']='--archived-review' in sys.argv;p['title']='Florida / Isaias: what happens next?';assets=media();beats=build_beats(p);rows=[];cursor=0;trims={a['id']:0 for a in assets};narration=[];captions=[]
 for b,(title,text,shots) in enumerate(beats):
  aiff=OUT/f'voice-{b:02}.aiff';txt=OUT/f'voice-{b:02}.txt';txt.write_text(text)
  key=hashlib.sha256(('Samantha/150/'+text).encode()).hexdigest();marker=aiff.with_suffix('.sha256')
  if not aiff.exists() or not marker.exists() or marker.read_text()!=key:
   subprocess.run(['/usr/bin/say','-v','Samantha','-r','150','-f',str(txt),'-o',str(aiff)],check=True);marker.write_text(key)
  speech=float(probe(aiff)['format']['duration']);frames=math.ceil((speech+.35)*30);length=frames/30;wav=OUT/f'voice-{b:02}.wav'
  ff('-i',aiff,'-af',f'apad=whole_dur={length}','-t',length,'-ar',48000,'-ac',1,wav);narration.append(wav)
  footage_count=sum(mode=='foot' for mode,_ in shots);footage_frames=105
  graphic_count=len(shots)-footage_count;remaining_frames=frames-footage_count*footage_frames
  if remaining_frames<graphic_count*30:raise ValueError('Narration is too short for the selected shot sequence.')
  per=remaining_frames//graphic_count;beat_start=cursor;graphic_index=0
  for j,(mode,target) in enumerate(shots):
   if mode=='foot':count=footage_frames
   else:
    count=per+(remaining_frames%graphic_count if graphic_index==graphic_count-1 else 0);graphic_index+=1
   seconds=count/30
   row={'kind':mode,'hours':target if mode!='foot' else 0,'seconds':seconds,'start_seconds':cursor,'beat':b,'text':title,
      'header':'RECORDED FLORIDA FORECAST / 09 OCT 2026','static_title':True,'context':'FORECAST / SOURCE VALID TIMES','credit':'NWS & NHC · recorded source snapshot / '+stamp(p['collected_at']).strftime('%d OCT %H:%M UTC'),
      'camera_start':[-93,22,-77,34.5],'camera_end':[-92.5,22.3,-77.5,34.2]}
   if mode=='center':row['context']='REPORTED / '+stamp(p['nhc'][0]['latest']['issued_at']).strftime('%d OCT %H:%M UTC')
   if mode in ['rain','wind','temperature','trend'] or mode in STAT_MODES:
    valid=next(s['valid_at'] for s in p['snapshots'] if s['hours']==target);row['context']='VALID '+stamp(valid).strftime('%d OCT %H:%M UTC')
    row['valid_at']=valid
    issues=[stamp(c['issued_at']) for c in p['cities']]
    row['credit']='NWS city forecasts issued '+min(issues).strftime('%d OCT %H:%M')+'–'+max(issues).strftime('%H:%M UTC')+' · point forecasts / no inferred field'
   if mode=='foot':
    a=assets[target];start=trims[a['id']];assert start+seconds<=a['seconds'],(a['id'],start+seconds,a['seconds'])
    row.update(filename=a['id']+'.mp4',path=a['path'],trim_start=start,context='ILLUSTRATIVE / '+a['location'].replace(', Florida','').upper(),credit=a['author']+' / Pexels · '+a['location']+' · not current weather footage')
    trims[a['id']]+=seconds
   if mode in ['rain-matrix','wind-checkpoints','forecast-timeline']:
    row['context']='FORECAST / SIX VALID HOURS'
   if mode in ['storm-facts','forecast-window','forecast-scope','surge-height','rainfall-range']:
    row['context']='NHC / '+stamp(p['nhc'][0]['latest']['issued_at']).strftime('%d OCT %H:%M UTC')
    row['credit']='NHC public bulletin / '+stamp(p['nhc'][0]['latest']['issued_at']).strftime('%d OCT %H:%M UTC')+' · '+('reported storm facts' if mode=='storm-facts' else 'forecast / conditional hazard values')
   if mode in ['alert-counts','alerts']:
    row['context']='ALERT SNAPSHOT / '+stamp(p['collected_at']).strftime('%d OCT %H:%M UTC')
    row['credit']='NWS Florida active-alert feed / collection '+stamp(p['collected_at']).strftime('%d OCT %H:%M UTC')+' · records can overlap'
   if mode in ['source-clock','takeaways','forecast-scope','forecast-window','outlook']:
    row['credit']='NWS & NHC / recorded edition collected '+stamp(p['collected_at']).strftime('%d OCT %H:%M UTC')+' · check current bulletins before acting'
   if mode=='wind':row.update(camera_start=[-89,27.5,-79.5,33],camera_end=[-88.5,28,-79.8,32.8])
   if mode in ['center','cone','warnings']:row.update(camera_start=[-94,22,-78,35.5],camera_end=[-94,23,-76,38])
   rows.append(row);cursor+=seconds
  import re
  sentences=re.split(r'(?<=[.?]) +',text);words=sum(len(x.split()) for x in sentences);offset=beat_start
  for sentence in sentences:
   dur=speech*len(sentence.split())/words;captions.append((offset,offset+dur,sentence));offset+=dur
 assert 120<=cursor<=210,cursor
 kinds=[r['kind'] for r in rows if r['kind']!='foot']
 assert len(kinds)==len(set(kinds)), 'A graphic treatment repeats'
 p['visual_audit']={'shots':len(rows),'unique_graphic_treatments':len(kinds),'repeated_graphic_treatments':0,'footage_trims_disjoint':True,'timing':'Reveal each graphic once, then hold; no graphic loop'}
 (OUT/'voice-concat.txt').write_text(''.join(f"file '{x.name}'\n" for x in narration));ff('-f','concat','-safe',1,'-i',OUT/'voice-concat.txt','-af','loudnorm=I=-16:TP=-1.5:LRA=9','-ar',48000,'-ac',1,OUT/'narration.wav')
 p['statistical_summary']={'rain_chance_gap_6h_percentage_points':rain_gap(p,6),
  'rain_matrix_cells':len(p['cities'])*len(p['snapshots']),'alert_records_by_event':dict(alert_counts(p)),
  'storm_facts':{k:p['nhc'][0]['latest']['facts'][k] for k in ['wind_mph','pressure_mb','movement_mph']},
  'semantics':'Point forecast values; alert records can overlap; future valid hours are not forecast revisions'}
 manifest={**p,'seconds':round(cursor,3),'shots':rows,'media':assets,'voice':{'engine':'macOS say','voice':'Samantha','rate':150},'paid_generation_calls':0,
  'limitations':p['limitations']+['Footage is illustrative, with unknown capture dates; never current observations.',
   'NHC forecast geometry issued 03 UTC is shown separately from the 06 UTC intermediate public bulletin.',
   'Alerts with no native polygons are not invented on the map; their full records remain in the manifest.',
   'Sentence captions use approximate positions within each measured spoken paragraph.',
   'This visual revision uses the original archived edition; rendering does not refresh weather data.',
   'Alert statistics count records that may overlap, not people, cities or unique covered areas.',
   'The rain-chance contrast is a percentage-point subtraction between two grid forecasts at one valid hour.',
   'No comparable previous forecast snapshot exists; no forecast-change claims were made.']}
 (OUT/'plan.json').write_text(json.dumps(manifest,indent=2));(OUT/'script.txt').write_text('\n\n'.join(t+'\n'+s for t,s,_ in beats))
 (OUT/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{srt_time(a)} --> {srt_time(b)}\n{text}' for i,(a,b,text) in enumerate(captions))+'\n')
 print('Prepared',round(cursor,2),'seconds /',len(rows),'shots',flush=True);return manifest


async def run():
 p=prepare()
 if '--prepare' in sys.argv:return
 code=Path(__file__).read_bytes()+Path(documentary.__file__).read_bytes()+Path(forecast_graphics.__file__).read_bytes()
 code+=json.dumps({k:p[k] for k in ['snapshots','alerts','nhc']},sort_keys=True).encode()
 for i,r in enumerate(p['shots']):
  out=OUT/f'shot-{i:02}.mp4';marker=out.with_suffix('.sha256');key=hashlib.sha256(json.dumps(r,sort_keys=True).encode()+code).hexdigest()
  cached=out.exists() and marker.exists() and marker.read_text()==key+':'+checksum(out)
  print(f'Shot {i+1}/{len(p["shots"])}: '+('cached' if cached else r['kind']),flush=True)
  if not cached:
   await documentary.render(r,out,lambda name:(SOURCES/name).read_bytes(),Path(r['path']) if r['kind']=='foot' else None,None if r['kind']=='foot' else ForecastComposer(r,p))
   v=next(s for s in probe(out)['streams'] if s['codec_type']=='video');assert int(v['nb_frames'])==round(r['seconds']*30)
   marker.write_text(key+':'+checksum(out))
 (OUT/'concat.txt').write_text(''.join(f"file 'shot-{i:02}.mp4'\n" for i in range(len(p['shots']))));seconds=p['seconds'];video=OUT/'florida-forecast-bulletin.revised.mp4'
 ff('-f','concat','-safe',1,'-i',OUT/'concat.txt','-i',OUT/'narration.wav','-f','lavfi','-i',score_filter(seconds),
    '-filter_complex',f'[2:a]loudnorm=I=-30:TP=-5:LRA=6,afade=t=in:d=2,afade=t=out:st={seconds-3}:d=3[bed];[1:a][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.84:level=0[a]',
    '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-ar',48000,'-t',seconds,'-movflags','+faststart',video)
 v=next(s for s in probe(video)['streams'] if s['codec_type']=='video');frames=sum(round(r['seconds']*30) for r in p['shots'])
 assert (v['width'],v['height'],int(v['nb_frames']))==(1920,1080,frames);assert abs(float(v['duration'])-seconds)<.05
 qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-af','ebur128=peak=true','-f','null','-'],capture_output=True,check=True)
 (OUT/'qc.log').write_bytes(qc.stderr);assert b'black_start:' not in qc.stderr
 final=OUT/'florida-forecast-bulletin.mp4';video.replace(final)
 p['output']={'path':str(final),'checksum':checksum(final),'seconds':float(v['duration']),'frames':frames,'width':1920,'height':1080,'fps':30,'full_decode':True,'black_check':True}
 contact=Image.new('RGB',(1920,1080),'#071722')
 for i,r in enumerate(p['shots']):
  preview=OUT/f'frame-{i:02}.jpg'
  ff('-ss',min(r['seconds']-.05,r['seconds']*.65),'-i',OUT/f'shot-{i:02}.mp4','-frames:v',1,'-q:v',2,preview)
  with Image.open(preview) as frame:contact.paste(frame.resize((320,180)),((i%6)*320,(i//6)*180))
 contact.save(OUT/'contact.jpg',quality=92)
 p['rendered_at']=datetime.now(timezone.utc).isoformat();temp=OUT/'manifest.json.tmp';temp.write_text(json.dumps(p,indent=2));temp.replace(OUT/'manifest.json')
 print(final,flush=True)

if __name__=='__main__':asyncio.run(run())
