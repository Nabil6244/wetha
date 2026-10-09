#!/usr/bin/env python3
"""Complete 90-second source-bound documentary edit, using local assets only."""
import asyncio,copy,hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import app.documentary as documentary
from app.production import checksum,probe,srt_time
from app.cinematic import score_filter
spec=importlib.util.spec_from_file_location('episode',ROOT/'scripts/render-complete-episode.py')
episode=importlib.util.module_from_spec(spec);spec.loader.exec_module(episode)
OUT=ROOT/'.local/exports/documentary'


def plan():
    evidence=episode.plan();catalog={a['filename']:a for a in evidence['media']['assets']};rows=[]
    def stat(label,value,detail):return {'label':label,'value':value,'detail':detail}
    def foot(name,start,text,metric=None):
        m=catalog[name];archival=m['context']=='archival'
        rows.append({'kind':'footage','filename':name,'trim_start':start,'seconds':3,'text':text,'stat':metric,
            'context':'ARCHIVE: IRMA / 2017' if archival else 'ILLUSTRATIVE FOOTAGE',
            'credit':m['attribution']+' · '+('CC BY 3.0 · St. Lucia, 05 SEP 2017 · trimmed; source audio removed' if archival else 'Pexels License · not Isaias ground footage'),
            'media':m,'weather_source_refs':[a['source_url'] for a in evidence['evidence']] if metric else []})
    def observation(kind,a,b,text):
        template=evidence['shots'][10 if kind=='satellite' else 5]
        rows.append({'kind':'observation','seconds':4,'text':text,'context':'OBSERVED '+kind.upper()+' / 2020',
            'credit':template['parameters']['credit'],'direction':copy.deepcopy(template['direction']),
            'parameters':copy.deepcopy(template['parameters']),'frame_range':[a,b]})
    def mapping(mode,index,start,end,text):
        template=evidence['shots'][index]
        rows.append({'kind':'map','seconds':6,'text':text,'context':'FORECAST AS ISSUED / 2020' if mode=='forecast' else 'SOURCE RECORD / 2020',
            'credit':template['parameters']['credit'],'direction':copy.deepcopy(template['direction']),
            'parameters':copy.deepcopy(template['parameters']),'map_kind':mode,'camera_start':start,'camera_end':end})
    sea='storm-sea-1879456.mp4';ocean='ocean-rainstorm-34270425.mp4';rain='rain-wind-4436187.mp4'
    foot(sea,0,'Twelve hours. A stronger storm. A coast ahead.',stat('NHC REPORTED WINDS','70 → 85 mph','03 AUG 15 UTC → 04 AUG 03 UTC'))
    observation('satellite',0,45,'The archive shows the system approaching the coast.')
    foot(ocean,0,'At 15 UTC, the advisory reported 70 mph.',stat('03 AUG 2020 / 15 UTC','70 mph','NHC advisory 26 / sustained wind'))
    mapping('track',2,[-84,27,-72,39],[-81,30,-75,36],'Three reported positions. One coastal approach.')
    foot(rain,0,'Wind strengthened across the next two advisories.',stat('REPORTED CHANGE','+15 mph','Two measurements / 12 hours apart'))
    observation('radar',0,23,'Radar adds another view of the approaching circulation.')
    foot(sea,8,'Pressure fell as the storm strengthened.',stat('NHC CENTRAL PRESSURE','998 → 988 mb','Two advisory measurements / 10 mb decrease'))
    observation('satellite',45,90,'The cloud system evolves in the original sequence.')
    foot(ocean,6,'By 03 UTC, reported winds reached 85 mph.',stat('04 AUG 2020 / 03 UTC','85 mph','NHC advisory 28 / sustained wind'))
    mapping('warnings',4,[-83,28,-71,42],[-81,31,-74,38],'Warning lines identified sections of the coastline.')
    foot('st-lucia-irma-waves.webm',5,'Archival comparison: waves during Irma in 2017.')
    observation('radar',23,46,'Keep the radar clock in view as the frames advance.')
    foot(rain,3,'Wind was one part of the story. Rain was another.')
    observation('radar',46,69,'This is reflectivity—not a rainfall-total map.')
    foot(sea,14,'What did forecasters expect to happen next?')
    mapping('forecast',7,[-84,29,-64,48],[-85,31,-61,57],'The forecast followed the center northward.')
    foot(ocean,12,'The cone was a center forecast, not an impact boundary.')
    observation('radar',69,92,'Later radar frames show the circulation crossing inland.')
    foot(sea,20,'Reported values and observed images tell different parts.')
    observation('satellite',90,136,'Satellite frames complete the cloud-system sequence.')
    foot(ocean,18,'The aftermath added measurements unavailable beforehand.')
    observation('radar',92,115,'The later observation sequence continues inland.')
    foot(rain,6,'One gauge northwest of Pawley’s Island recorded 6.80 inches.',stat('POST-EVENT NWS GAUGE','6.80 inches','SC-GT-42 / 2.4 miles NW of Pawley’s Island'))
    rows[-1]['weather_source_refs']=[evidence['rainfall_gauge']['source_url']]
    observation('radar',115,136,'Stronger winds. Falling pressure. The observed aftermath.')
    cursor=0;ranges={}
    for row in rows:
        row['start_seconds']=cursor;cursor+=row['seconds']
        if row['kind']=='footage':
            name=row['filename'];start=row['trim_start'];end=start+row['seconds']
            if end>float(probe(episode.POOL/name)['format']['duration']):raise ValueError('Footage trim exceeds original duration.')
            if any(start<b and end>a for a,b in ranges.get(name,[])):raise ValueError('Footage ranges may not repeat.')
            ranges.setdefault(name,[]).append((start,end))
    assert cursor==90
    return {'title':'Isaias / The final twelve hours','event_id':'AL092020','historical':True,'shots':rows,
        'evidence':evidence['evidence'],'official_layers':evidence['official_layers'],'rainfall_gauge':evidence['rainfall_gauge'],
        'timestamp_verification':evidence['timestamp_verification'],'source_pins':evidence['source_pins'],
        'moving_imagery_seconds':72,'traveling_map_seconds':18,'full_screen_text_cards':0,
        'limitations':['Historical case study; no current warning or forecast.','Stock footage is illustrative. One labeled Irma clip is a 2017 archival comparison, not Isaias.',
            'All footage trims are distinct, but the four-source library still limits independent scene variety.',
            'Native observation pixels are enlarged. Timestamp and legend strips are retained; no inferred intermediate frames.',
            'Map movement and connectors are presentation, not additional storm observations.','No voiceover. Original local instrumental; source audio removed.'],
        'paid_generation_calls':0}


async def run():
    OUT.mkdir(parents=True,exist_ok=True);p=plan()
    def load(name):return (ROOT/'.local/phase7/sources'/name).read_bytes()
    code=Path(__file__).read_bytes()+Path(documentary.__file__).read_bytes()
    for i,row in enumerate(p['shots']):
        out=OUT/f'shot-{i:02}.mp4';marker=out.with_suffix('.sha256')
        key=hashlib.sha256(json.dumps(row,sort_keys=True).encode()+code).hexdigest()
        cached=out.exists() and marker.exists() and marker.read_text()==key+':'+checksum(out)
        print(f'Shot {i+1}/24: '+('cached' if cached else row['kind']),flush=True)
        if not cached:
            await documentary.render(row,out,load,episode.POOL/row['filename'] if row['kind']=='footage' else None)
            v=next(s for s in probe(out)['streams'] if s['codec_type']=='video')
            if int(v['nb_frames'])!=row['seconds']*30:raise ValueError('Missing picture frames in a shot.')
            marker.write_text(key+':'+checksum(out))
    (OUT/'concat.txt').write_text(''.join(f"file 'shot-{i:02}.mp4'\n" for i in range(len(p['shots']))))
    video=OUT/'isaias-documentary-90.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','1','-i',str(OUT/'concat.txt'),'-f','lavfi','-i',score_filter(90),
        '-map','0:v:0','-map','1:a:0','-c:v','copy','-af','loudnorm=I=-22:TP=-2:LRA=9,afade=t=in:d=1,afade=t=out:st=87:d=3','-c:a','aac','-ar','48000','-t','90','-movflags','+faststart',str(video)],check=True)
    v=next(s for s in probe(video)['streams'] if s['codec_type']=='video')
    assert (v['width'],v['height'],v['r_frame_rate'],int(v['nb_frames']))==(1920,1080,'30/1',2700)
    assert abs(float(v['duration'])-90)<.05
    qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-f','null','-'],capture_output=True,check=True)
    (OUT/'qc.log').write_bytes(qc.stderr);assert b'black_start:' not in qc.stderr
    p['output']={'path':str(video),'checksum':checksum(video),'seconds':90,'frames':2700,'width':1920,'height':1080,'fps':30,'full_decode':True,'black_check':True}
    (OUT/'manifest.json').write_text(json.dumps(p,indent=2))
    (OUT/'script.txt').write_text('\n\n'.join(f"{r['start_seconds']:02}–{r['start_seconds']+r['seconds']:02}s / {r['kind']}\n{r['text']}" for r in p['shots']))
    (OUT/'captions.srt').write_text('\n\n'.join(f"{i+1}\n{srt_time(r['start_seconds'])} --> {srt_time(r['start_seconds']+r['seconds'])}\n{r['text']}" for i,r in enumerate(p['shots']))+'\n')
    sheet=Image.new('RGB',(1600,1080))
    for i,row in enumerate(p['shots']):
        frame=OUT/f'frame-{i:02}.jpg'
        subprocess.run(['ffmpeg','-y','-v','error','-ss',str(row['start_seconds']+row['seconds']*.65),'-i',str(video),'-frames:v','1','-vf','scale=320:180',str(frame)],check=True)
        sheet.paste(Image.open(frame),((i%5)*320,(i//5)*180))
    sheet.save(OUT/'contact.jpg');print(video,flush=True)


if __name__=='__main__':asyncio.run(run())
