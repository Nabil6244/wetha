#!/usr/bin/env python3
"""Free local proof of the hour's varied graphics; not a padded hour export."""
import asyncio,copy,importlib.util,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import app.broadcast as engine
from app.episode_graphics import EpisodeComposer
from app.graphic_styles import prepare
from app.production import checksum,probe
from app.cinematic import score_filter
from app.longform import blueprint
spec=importlib.util.spec_from_file_location('episode',ROOT/'scripts/render-complete-episode.py')
episode=importlib.util.module_from_spec(spec);spec.loader.exec_module(episode)
OUT=ROOT/'.local/exports/hour-graphics'


async def run():
    OUT.mkdir(parents=True,exist_ok=True)
    base=episode.plan();a=episode.benchmark.parse_nhc((ROOT/'.local/phase7/sources/nhc28.html').read_text(),episode.benchmark.URLS['nhc28.html'],'official_fetch')
    rows=[]
    for style,index in [('question_reveal',3),('map',2),('change_gauge',3),('map',4),('comparison_split',3),('map',5),('advisory_timeline',2),('map',7),('forecast_clock',7),('source_card',2)]:
        row=copy.deepcopy(base['shots'][index]);row.update(duration=6);row['direction']['duration']=6
        for key in ('episode_caption','episode_beat'):row['parameters'].pop(key,None)
        if style!='map':
            p=row['parameters'];p.pop('episode_map',None)
            if style=='advisory_timeline':
                p['geojson']={'features':[{'type':'Feature','geometry':{'type':'Point','coordinates':r['coordinates']},'properties':{**r,'kind':'reported_center'}} for r in p['records']]}
            scene={'graphic_style':style,'parameters':p,'direction':row['direction']}
            prepare(scene,a)
        rows.append(row)
    engine.Composer=EpisodeComposer
    def load(name):return ((ROOT/'.local/episode/sources' if name=='rainfall.png' else ROOT/'.local/phase7/sources')/name).read_bytes()
    for i,row in enumerate(rows):
        print(f'Graphic {i+1}/10: '+row['direction']['headline'],flush=True)
        await engine.render_clip(row['direction'],row['parameters'],OUT/f'shot-{i:02}.mp4',load,6)
    concat=OUT/'concat.txt';concat.write_text(''.join(f"file 'shot-{i:02}.mp4'\n" for i in range(10)))
    video=OUT/'hour-graphics-60.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(concat),'-f','lavfi','-i',score_filter(60),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-af','afade=t=out:st=58:d=2','-t','60','-movflags','+faststart',str(video)],check=True)
    v=next(s for s in probe(video)['streams'] if s['codec_type']=='video')
    assert (v['width'],v['height'],int(v['nb_frames']),float(v['duration']))==(1920,1080,1800,60)
    qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-f','null','-'],capture_output=True,check=True)
    assert b'black_start:' not in qc.stderr;(OUT/'qc.log').write_bytes(qc.stderr)
    (OUT/'manifest.json').write_text(json.dumps({'title':'Hour-program graphics proof','event_id':'AL092020','historical':True,'shots':rows,'evidence':base['evidence'],'official_layers':base['official_layers'],
        'output':{'path':str(video),'checksum':checksum(video),'seconds':60,'frames':1800,'full_decode':True},'scope':'Ten visual treatments shown for review. This is a 60-second graphics proof, not the one-hour program.','paid_generation_calls':0},indent=2))
    media=[{'kind':'video','rights_confirmed':True,'checksum':m['checksum'],'seconds':float(probe(episode.POOL/m['filename'])['format']['duration'])} for m in base['media']['assets']]
    (OUT/'one-hour-blueprint.json').write_text(json.dumps(blueprint(media),indent=2))
    print(video,flush=True)


if __name__=='__main__':asyncio.run(run())
