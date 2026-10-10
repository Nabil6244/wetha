"""Local speech timestamps, revision-bound matching, and reviewable scene timing."""
import copy
import hashlib
import json
import os
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4


def tokens(text):
    return re.findall(r"[a-z0-9]+",text.lower())


def word_frames(plan, offsets, matched, boundaries, total):
    """Start frame of each written word, relative to its scene. Unmatched words are interpolated."""
    anchors=sorted(matched);result={}
    def second(n):
        if n in matched:return matched[n]
        before=next((a for a in reversed(anchors) if a<n),None);after=next((a for a in anchors if a>n),None)
        if before is None:return matched[after]
        if after is None:return matched[before]
        return matched[before]+(matched[after]-matched[before])*(n-before)/(after-before)
    for i,scene in enumerate(plan['scenes']):
        start,end=boundaries[i],boundaries[i+1];cursor=offsets[i];frames=[]
        for word in scene['script_segment'].split():
            count=len(tokens(word))
            if count and cursor<total:
                frames.append(min(end-start,max(0,round(second(cursor)*30)-start)))
            else:
                frames.append(frames[-1] if frames else 0)
            cursor+=count
        # Recognized times can jitter by a frame; captions must never move backwards.
        for n in range(1,len(frames)):frames[n]=max(frames[n],frames[n-1])
        result[scene['id']]=frames
    return result


def align(plan, words, duration):
    script=[]; offsets=[]
    for scene in plan['scenes']:
        offsets.append(len(script));script.extend(tokens(scene['script_segment']))
    heard=[];starts=[]
    for word in words:
        parts=tokens(word['word'])
        for i,part in enumerate(parts):
            heard.append(part);starts.append(word['start']+(word['end']-word['start'])*i/max(1,len(parts)))
    if not script or not heard:raise ValueError('No speech detected. Check the uploaded audio.')
    matcher=SequenceMatcher(None,script,heard,autojunk=False)
    matched={}
    for block in matcher.get_matching_blocks():
        for i in range(block.size):matched[block.a+i]=starts[block.b+i]
    coverage=len(matched)/len(script)
    issues=[]
    if coverage<.85:
        raise ValueError(f'Only {coverage:.0%} of script words match the recording. Upload audio for this exact script or correct the text before alignment.')
    anchors=sorted(matched)
    for i,offset in enumerate(offsets):
        end=offsets[i+1] if i+1<len(offsets) else len(script)
        if sum(n in matched for n in range(offset,end))/max(1,end-offset)<.6:
            raise ValueError(f'Scene {i+1} does not match the spoken narration. Correct this part of the script or recording.')
    # Use nearby heard words at scene boundaries. Never invent a whole unmatched paragraph.
    boundaries=[0]; inferred=[]
    for i,offset in enumerate(offsets[1:],1):
        nearby=min(anchors,key=lambda n:abs(n-offset))
        if abs(nearby-offset)>5:raise ValueError(f'Scene {i+1} has no reliable spoken boundary. Correct this script/audio mismatch.')
        if offset in matched:second=matched[offset]
        else:
            before=next((n for n in reversed(anchors) if n<offset),None)
            after=next((n for n in anchors if n>offset),None)
            if before is None or after is None:raise ValueError('Opening or closing narration does not match the recording.')
            second=matched[before]+(matched[after]-matched[before])*(offset-before)/(after-before)
            inferred.append(plan['scenes'][i]['id'])
        boundaries.append(round(second*30))
    boundaries.append(round(duration*30))
    edits=[]
    for i,scene in enumerate(plan['scenes']):
        frames=boundaries[i+1]-boundaries[i]
        if frames<30 or frames>3600:
            raise ValueError(f'Scene {i+1} has an unreliable speech duration. Review this part of the recording.')
        if frames>300:
            issues.append({'scene_id':scene['id'],'code':'long_aligned_shot','message':'Speech alignment gives this shot more than 10 seconds. Split the beat or add footage before export.'})
        edits.append({'id':scene['id'],'seconds':frames/30,'media_id':None,'trim_start':0,'transition':'cut','cuts':[],'map_mode':'auto','graphic_style':'auto','regional_focus':'auto'})
    if inferred:issues.append({'code':'inferred_boundaries','message':f'{len(inferred)} scene boundaries fall between matched words. Listen and review these transitions.'})
    return {'scenes':edits,'coverage':round(coverage,3),'inferred_scene_ids':inferred,'seconds':round(duration*30)/30,
            'word_frames':word_frames(plan,offsets,matched,boundaries,len(script)),
            'issues':issues,'timing_basis':'Local recognized word timestamps matched to the saved script; unmatched boundary words interpolated and flagged.'}


class AlignmentJobs:
    def __init__(self, production):
        self.production=production;self.jobs={};self.lock=threading.Lock()
        self.directory=production.store.path.parent/'alignments'
        self.directory.mkdir(parents=True,exist_ok=True)

    def start(self, plan_id, narration_id):
        plan=self.production.store.visual_plan(plan_id)
        self.production.validate_plan(plan, require_support=False)
        asset=next((a for a in self.production.store.production_list('media') if a['id']==narration_id),None)
        if not asset or asset['kind']!='audio':raise ValueError('Choose an imported narration audio file.')
        path=self.production.media_path(asset)
        with self.lock:
            for job in self.jobs.values():
                if job['status'] in ('queued','running'):
                    if job['plan_id']==plan_id and job['narration_id']==narration_id:return copy.deepcopy(job)
                    raise ValueError('Another recording is being aligned. Wait for it to finish.')
            identity=str(uuid4())
            job={'id':identity,'plan_id':plan_id,'narration_id':narration_id,'script_revision':plan['script_revision'],
                 'script_text_checksum':plan['script_text_checksum'],'audio_checksum':asset['checksum'],
                 'status':'queued','progress':0,'stage':'Starting local speech model','error':None,'result':None}
            self.jobs[identity]=job
            self._save(job)
        threading.Thread(target=self._run,args=(identity,plan,asset,path),daemon=True).start()
        return copy.deepcopy(job)

    def get(self, identity):
        try:identity=str(__import__('uuid').UUID(identity))
        except ValueError:raise KeyError(identity)
        with self.lock:
            if identity not in self.jobs:
                path=self.directory/f'{identity}.json'
                if not path.is_file():raise KeyError(identity)
                job=json.loads(path.read_text())
                if job['status'] in ('queued','running'):
                    # Saved while running; the speech thread did not survive an application restart.
                    job.update(status='failed',stage='Alignment needs attention',error='Alignment stopped when the application closed. Start it again.')
                    self._save(job)
                self.jobs[identity]=job
            return copy.deepcopy(self.jobs[identity])

    def _save(self,job):
        (self.directory/f"{job['id']}.json").write_text(json.dumps(job))

    def update(self,identity,**values):
        with self.lock:
            self.jobs[identity].update(values)
            if 'status' in values:
                self._save(self.jobs[identity])

    def _run(self,identity,plan,asset,path):
        try:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ValueError('Local speech engine is missing. Install backend/requirements-speech.txt in this app’s Python runtime.') from None
            local=Path(__file__).resolve().parents[2]/'.local/speech-model'
            model_root=Path(os.environ.get('WETHA_SPEECH_CACHE',local if local.exists() else self.directory.parent/'speech-model'))
            self.update(identity,status='running',stage='Loading local English speech model')
            model=WhisperModel('base.en',device='cpu',compute_type='int8',cpu_threads=4,download_root=str(model_root))
            segments,_=model.transcribe(str(path),language='en',word_timestamps=True,beam_size=5,vad_filter=True,condition_on_previous_text=False)
            words=[]
            for segment in segments:
                words.extend({'word':w.word,'start':w.start,'end':w.end} for w in segment.words or [])
                self.update(identity,stage='Listening and matching speech',progress=min(.95,segment.end/asset['seconds']))
            result=align(plan,words,asset['seconds'])
            self.production.validate_plan(plan, require_support=False)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=asset['checksum']:raise ValueError('Audio changed during alignment. Reimport it.')
            self.update(identity,status='completed',progress=1,stage='Review aligned scene changes',result=result)
        except Exception as error:
            self.update(identity,status='failed',stage='Alignment needs attention',error=str(error))
