#!/usr/bin/env python3
"""Assemble a validated hour from completed chapter renders, without filler."""
import argparse,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.storage import Store
from app.intelligence import IntelligenceDesk
from app.editorial import evaluate,legacy_document
from app.longform import audit,CHAPTERS
from app.production import Production,checksum,probe,srt_time


def collect(data_dir,assignments):
    if not (data_dir/'studio.sqlite3').is_file():raise ValueError('An existing local studio database is required.')
    store=Store(data_dir/'studio.sqlite3')
    def describe_script(document):
        advisory=store.advisory(document['advisory_id'])
        evidence=[store.advisory(i) for i in document.get('source_advisory_ids',[advisory.id])]
        document=legacy_document(document,evidence)
        review=next((r for r in store.reviews(document['id']) if r['revision']==document['revision']),None)
        return evaluate(document,IntelligenceDesk(store.advisories(),store.feeds(),store.memberships()),evidence,review)
    service=Production(store,describe_script)
    rows=[];chapters=[];timelines={};used=set()
    supplied={c['chapter_id']:c['render_ids'] for c in assignments}
    if len(supplied)!=len(assignments) or set(supplied)-{c[0] for c in CHAPTERS}:
        raise ValueError('Use each known chapter ID at most once.')
    for identity,seconds,*_ in CHAPTERS:
        ids=[]
        for render_id in supplied.get(identity,[]):
            if render_id in used:raise ValueError('A chapter render cannot be replayed to fill the hour.')
            used.add(render_id)
            job=store.production_get('renders',render_id)
            if job['status']!='succeeded':raise ValueError('Every chapter render must have completed output validation.')
            timeline=job['snapshot']
            live,_=service.validate_timeline(timeline)
            if live['source_label']!=timeline['source_label']:raise ValueError('Chapter source status changed. Render that chapter again.')
            script=store.script(timeline['script_id']);timeline={**timeline,'event_id':store.advisory(script['advisory_id']).event_key}
            timelines[timeline['id']]=timeline;ids.append(timeline['id'])
            video=service.output_path(render_id,'video');manifest=service.output_path(render_id,'manifest');subtitles=service.output_path(render_id,'subtitles')
            v=next(s for s in probe(video)['streams'] if s['codec_type']=='video')
            if (v['codec_name'],v['width'],v['height'],v['r_frame_rate'])!=('h264',1920,1080,'30/1') or int(v['nb_frames'])!=round(timeline['seconds']*30):
                raise ValueError('Chapter picture does not match validated timing.')
            rows.append({'chapter_id':identity,'seconds':timeline['seconds'],'video':video,'subtitles':subtitles,'manifest':json.loads(manifest.read_text()),'checksum':checksum(video),'render_id':render_id})
        chapters.append({'chapter_id':identity,'timeline_ids':ids})
    result=audit(chapters,lambda identity:timelines[identity])
    if not result['ready']:
        raise ValueError('Hour content audit failed:\n'+'\n'.join(i['message'] for i in result['issues']))
    return rows,result


def shifted_subtitles(raw,offset):
    def seconds(stamp):
        h,m,s,ms=map(int,re.split('[:,]',stamp));return h*3600+m*60+s+ms/1000
    result=[]
    for block in re.split(r'\n\s*\n',raw.strip()):
        lines=block.splitlines()
        if len(lines)<3:raise ValueError('Malformed chapter subtitles.')
        match=re.fullmatch(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})',lines[1])
        if not match:raise ValueError('Malformed chapter subtitle timestamp.')
        a,b=map(seconds,match.groups())
        if b<a:raise ValueError('Reversed chapter subtitle interval.')
        result.append(srt_time(a+offset)+' --> '+srt_time(b+offset)+'\n'+'\n'.join(lines[2:]))
    return result


def run(args):
    assignments=json.loads(args.chapters.read_text())['chapters']
    rows,result=collect(args.data,assignments)
    print(json.dumps(result,indent=2),flush=True)
    if args.check_only:return
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    concat=[];cues=[];cursor=0;metadata=[';FFMETADATA1','title=Isaias / One-hour historical deep dive']
    for i,row in enumerate(rows):
        linked=output/f'chapter-input-{i:03}.mp4'
        if linked.exists() or linked.is_symlink():linked.unlink()
        linked.symlink_to(row['video'].resolve())
        concat.append(f"file '{linked.name}'")
        cues.extend(shifted_subtitles(row['subtitles'].read_text(),cursor))
        row['start_seconds']=cursor;cursor+=row['seconds']
    assert cursor==3600
    for identity,seconds,title,*_ in CHAPTERS:
        start=next(r['start_seconds'] for r in rows if r['chapter_id']==identity)
        metadata.extend(['[CHAPTER]','TIMEBASE=1/1000',f'START={round(start*1000)}',f'END={round((start+seconds)*1000)}','title='+title])
    (output/'concat.txt').write_text('\n'.join(concat)+'\n');(output/'chapters.ffmetadata').write_text('\n'.join(metadata)+'\n')
    (output/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{cue}' for i,cue in enumerate(cues))+'\n')
    video=output/'storm-deep-dive-60min.mp4'
    print('Assembling completed chapter videos and preserving their audio',flush=True)
    subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','1','-i',str(output/'concat.txt'),'-f','ffmetadata','-i',str(output/'chapters.ffmetadata'),
        '-map','0:v:0','-map','0:a:0','-map_metadata','1','-map_chapters','1','-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(video)],check=True)
    info=probe(video);v=next(s for s in info['streams'] if s['codec_type']=='video')
    if abs(float(v['duration'])-3600)>.15 or int(v['nb_frames'])!=108000 or abs(float(info['format']['duration'])-3600)>.15:
        raise ValueError('Full-hour video failed independent picture duration and frame validation.')
    print('Decoding the complete hour and checking black intervals',flush=True)
    qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(video),'-vf','blackdetect=d=1:pix_th=0.005:pic_th=0.995','-f','null','-'],capture_output=True,check=True)
    (output/'qc.log').write_bytes(qc.stderr)
    if b'black_start:' in qc.stderr:raise ValueError('A black interval was found in the assembled program.')
    manifest={'title':'Isaias / One-hour historical deep dive','content_audit':result,'chapters':[{k:str(v) if isinstance(v,Path) else v for k,v in row.items()} for row in rows],
        'output':{'path':str(video.resolve()),'checksum':checksum(video),'seconds':3600,'frames':108000,'full_decode':True,'black_check':True},'paid_generation_calls':0,'voiceover_generated':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(video.resolve(),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--chapters',type=Path,required=True)
    p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/weather-intelligence-studio/data')
    p.add_argument('--output',type=Path,default=ROOT/'.local/exports/hour');p.add_argument('--check-only',action='store_true')
    try:run(p.parse_args())
    except (ValueError,KeyError,OSError) as e:print(str(e),file=sys.stderr);sys.exit(1)
