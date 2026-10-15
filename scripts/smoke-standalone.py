#!/usr/bin/env python3
"""Run from the bundled interpreter with a fresh workspace and no developer tools."""
import argparse,json,os,shutil,socket,subprocess,sys,tempfile,time,urllib.error,urllib.request,wave
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    resources=args.resources.resolve();runtime=resources/'backend-runtime';tools=runtime/'tools';model=runtime/'speech-model'
    if Path(sys.base_prefix).resolve()!=runtime.resolve():raise RuntimeError('Run this check with the bundled Python, not a system interpreter.')
    with tempfile.TemporaryDirectory(prefix='wetha-standalone-smoke-') as work:
        work=Path(work);environment={**os.environ,'PATH':str(tools)+os.pathsep+(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32') if sys.platform=='win32' else '/usr/bin:/bin'),
              'PYTHONHOME':str(runtime),'PYTHONNOUSERSITE':'1','HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','WETHA_PACKAGED':'1','WETHA_SPEECH_MODEL_PATH':str(model),
              'WETHA_DATA_DIR':str(work/'data'),'WETHA_UI_DIR':str(resources/'ui')}
        environment.pop('PYTHONPATH',None)
        for name in ('ffmpeg','ffprobe'):
            resolved=Path(shutil.which(name,path=environment['PATH']) or '').resolve()
            if resolved.parent!=tools:raise RuntimeError('Bundled '+name+' was not selected.')
            subprocess.run([str(resolved),'-version'],stdout=subprocess.DEVNULL,check=True,env=environment)
        silent=work/'silence.wav'
        with wave.open(str(silent),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000)
        speech_test="from faster_whisper import WhisperModel; m=WhisperModel("+repr(str(model))+",device='cpu',compute_type='int8',local_files_only=True); segments,info=m.transcribe("+repr(str(silent))+",language='en',vad_filter=True); list(segments); print('Offline model inference passed')"
        subprocess.run([sys.executable,'-c',speech_test],check=True,env=environment,timeout=120)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}/api';environment['WETHA_DESKTOP_ORIGIN']=f'http://127.0.0.1:{port}'
        log=(work/'backend.log').open('wb')
        child=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=resources/'backend',env=environment,stdout=log,stderr=log)
        def request(route,body=None):
            req=urllib.request.Request(base+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
            try:return json.load(urllib.request.urlopen(req,timeout=30))
            except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from None
        try:
            for _ in range(100):
                if child.poll() is not None:raise RuntimeError('Bundled backend exited: '+(work/'backend.log').read_text())
                try:request('/health');break
                except OSError:time.sleep(.2)
            else:raise RuntimeError('Bundled backend did not become ready.')
            request('/training/load',{})
            script=request('/scripts',{'advisory_id':'training:cyclone:2'})
            plan=request('/visuals/plans',{'script_id':script['id'],'expected_revision':script['revision']})
            timeline=request('/production/timelines',{'plan_id':plan['id'],'title':'Standalone synthetic render check','presentation':'broadcast',
                'scenes':[{'id':s['id'],'seconds':1,'transition':'cut'} for s in plan['scenes']]})
            job=request('/production/renders',{'timeline_id':timeline['id']})
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                row=next(r for r in request('/production/progress')['renders'] if r['id']==job['id'])
                if row['status'] in ('succeeded','failed','cancelled'):break
                time.sleep(.5)
            else:raise RuntimeError('Standalone render timed out.')
            if row['status']!='succeeded':raise RuntimeError(str(row))
            result={'platform':sys.platform,'architecture':__import__('platform').machine(),'bundled_interpreter':True,'fresh_data_directory':True,
                    'developer_tools_excluded_from_path':True,'offline_speech_model_loaded':True,'render':row['validation'],'clean_machine_tested':False,
                    'note':'Isolated installed-resource smoke test on the build host. Separate clean-machine installation acceptance remains required.'}
            args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2))
        finally:
            child.terminate()
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            log.close()

if __name__=='__main__':main()
