"""Subdivide aligned narration into visual shots without retranscribing audio."""
import copy
from uuid import uuid4
from .storage import now


def shot_frames(frames):
    parts=[]
    while frames>120:
        length=min(120,frames-30) if frames<180 else frames//2 if frames<=240 else 120
        parts.append(length);frames-=length
    parts.append(frames)
    return parts


def subdivide(plan, job):
    result=copy.deepcopy(plan);result['id']=str(uuid4())
    result.update(automatic_shots=True,parent_plan_id=plan['id'],created_at=now())
    result['scenes']=[];edits=[]
    timed={s['id']:s for s in job['result']['scenes']}
    for scene in plan['scenes']:
        frames=round(timed[scene['id']]['seconds']*30)
        lengths=shot_frames(frames)
        words=scene['script_segment'].split();cursor=0;word_cursor=0
        for index,length in enumerate(lengths):
            cursor+=length
            end=len(words) if index==len(lengths)-1 else max(word_cursor+1,round(len(words)*cursor/frames))
            shot=copy.deepcopy(scene)
            shot.update(id=f"{scene['id']}-shot-{index+1}",parent_scene_id=scene['id'],script_segment=' '.join(words[word_cursor:end]),target_seconds=length/30)
            word_cursor=end
            result['scenes'].append(shot)
            edits.append({'id':shot['id'],'seconds':length/30,'media_id':None,'trim_start':0,'transition':'cut'})
    derived=copy.deepcopy(job);derived.update(id=str(uuid4()),plan_id=result['id'],parent_alignment_id=job['id'],stage='Spoken timing applied; shorter visual shots prepared')
    derived['result'].update(scenes=edits,timing_basis=job['result']['timing_basis']+' Visual shots subdivided in whole frames inside aligned narration sections; internal shot boundaries are editorial cuts, not newly recognized word boundaries.')
    return result,derived,edits
