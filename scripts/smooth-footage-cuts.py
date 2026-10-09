#!/usr/bin/env python3
"""Replace footage hard-cut windows with short image overlaps, preserving timing/audio."""
import concurrent.futures,hashlib,json,subprocess,sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.broadcast import encoder_args
from app.production import checksum,probe
OUT=ROOT/'.local/exports/florida-mixed-report';TRANS=OUT/'transitions';FPS=30;HALF=4;COUNT=HALF*2;SIZE=(1920,1080);BYTES=1920*1080*3

def make_window(item):
 source,boundary=item;start=boundary-HALF;output=TRANS/f'cut-{boundary}.mp4';marker=output.with_suffix('.sha256');key=hashlib.sha256((checksum(source)+str(boundary)+'/overlap-eight-frames-v1').encode()).hexdigest()
 if output.exists() and marker.exists() and marker.read_text()==key+':'+checksum(output):return start,output
 raw=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{start/FPS:.9f}','-i',str(source),'-frames:v',str(COUNT),'-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
 if len(raw)!=BYTES*COUNT:raise ValueError('Incomplete transition window')
 frames=[Image.frombytes('RGB',SIZE,raw[i*BYTES:(i+1)*BYTES]) for i in range(COUNT)];mixed=[]
 for i in range(COUNT):
  u=i/(COUNT-1);alpha=u*u*(3-2*u)
  outgoing=frames[min(i,HALF-1)];incoming=frames[HALF+max(0,i-HALF)]
  mixed.append(Image.blend(outgoing,incoming,alpha).tobytes())
 subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r',str(FPS),'-i','pipe:0','-frames:v',str(COUNT),'-an',*encoder_args(),'-pix_fmt','yuv420p','-y',str(output)],input=b''.join(mixed),check=True);marker.write_text(key+':'+checksum(output));return start,output

def main():
 p=json.load(open(OUT/'manifest.json'));source=Path(p['output']['path'])
 if checksum(source)!=p['output']['checksum']:raise ValueError('Approved video changed')
 if p.get('footage_crossfades'):raise ValueError('Already smoothed; restore the pre-overlap source manifest to rebuild')
 TRANS.mkdir(exist_ok=True);rows=p['shots'];boundaries=[round(r['start_seconds']*FPS) for i,r in enumerate(rows) if i and (r['kind'] in ('foot','archive_footage') and rows[i-1]['kind'] in ('foot','archive_footage'))]
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:windows=list(ex.map(make_window,[(source,b) for b in boundaries]))
 args=['ffmpeg','-v','error','-threads','2','-i',str(source)]
 for _,path in windows:args+=['-threads','1','-i',str(path)]
 graph=[];previous='0:v'
 for i,(start,_) in enumerate(windows,1):
  end=start+COUNT;graph.append(f'[{i}:v]setpts=PTS-STARTPTS+{start}/(30*TB)[c{i}]');graph.append(f'[{previous}][c{i}]overlay=eof_action=pass:repeatlast=0:enable=\'gte(t,{start}/30)*lt(t,{end}/30)\'[v{i}]');previous=f'v{i}'
 temp=OUT/'florida-clips-stats-maps-crossfades.tmp.mp4'
 subprocess.run(args+['-filter_complex_threads','2','-filter_complex',';'.join(graph),'-map',f'[{previous}]','-map','0:a:0','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-r','30','-fps_mode','cfr','-c:a','copy','-movflags','+faststart','-y',str(temp)],check=True)
 qc=subprocess.run(['ffmpeg','-hide_banner','-xerror','-i',str(temp),'-vf','crop=1920:850:0:100,blackdetect=d=0.01:pix_th=0.02:pic_th=0.995','-an','-f','null','-'],capture_output=True,check=True);(OUT/'crossfade-qc.log').write_bytes(qc.stderr)
 if b'black_start:' in qc.stderr:raise ValueError('Blank interval detected')
 v=next(s for s in probe(temp)['streams'] if s['codec_type']=='video');assert int(v['nb_frames'])==p['output']['frames'];assert abs(float(v['duration'])-p['output']['seconds'])<.04
 final=OUT/'florida-clips-stats-maps-crossfades.mp4';temp.replace(final);p['footage_crossfades']={'count':len(windows),'frames':COUNT,'seconds':COUNT/FPS,'preserve_total_timing':True,'source':str(source),'source_checksum':checksum(source)};p['output'].update(path=str(final),checksum=checksum(final),full_decode=True,black_check=True);(OUT/'manifest.json').write_text(json.dumps(p,indent=2)+'\n');print(final)
if __name__=='__main__':main()
