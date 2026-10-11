"""Subdivide aligned narration into visual shots without retranscribing audio."""
import copy
import math
from uuid import uuid4
from .storage import now

MIN_SHOT = 75   # 2.5 seconds; shorter internal cuts read as flashes.
MAX_SHOT = 120  # 4 seconds.
SNAP = 15       # Move a cut up to half a second to land on a spoken word.


def shot_frames(frames):
    """Even shots of 2.5-4 seconds. Sections under five seconds stay whole."""
    count=max(1,min(math.ceil(frames/MAX_SHOT),frames//MIN_SHOT))
    return [frames//count+(1 if i<frames%count else 0) for i in range(count)]


def snapped(lengths, starts):
    """Move each internal cut to the nearest word start while keeping shot limits."""
    total=sum(lengths);cuts=[];cursor=0
    for length in lengths[:-1]:
        cursor+=length
        previous=cuts[-1] if cuts else 0
        remaining=len(lengths)-len(cuts)-1
        low=max(previous+MIN_SHOT,total-MAX_SHOT*remaining)
        high=min(previous+MAX_SHOT,total-MIN_SHOT*remaining)
        target=min(high,max(low,cursor))
        options=[s for s in starts if max(low,cursor-SNAP)<=s<=min(high,cursor+SNAP)]
        cuts.append(min(options,key=lambda s:abs(s-cursor)) if options else target)
    bounds=[0,*cuts,total]
    return [b-a for a,b in zip(bounds,bounds[1:])]


def subdivide(plan, job):
    result=copy.deepcopy(plan);result['id']=str(uuid4())
    result.update(automatic_shots=True,parent_plan_id=plan['id'],created_at=now())
    result['scenes']=[];edits=[]
    timed={s['id']:s for s in job['result']['scenes']}
    spoken=job['result'].get('word_frames',{})
    for scene in plan['scenes']:
        frames=round(timed[scene['id']]['seconds']*30)
        words=scene['script_segment'].split()
        starts=spoken.get(scene['id']) if len(spoken.get(scene['id'],[]))==len(words) else None
        lengths=shot_frames(frames)
        if starts and len(lengths)>1:
            lengths=snapped(lengths,sorted(set(starts[1:])))
        cursor=0;word_cursor=0
        for index,length in enumerate(lengths):
            begin=cursor;cursor+=length
            if index==len(lengths)-1:
                end=len(words)
            elif starts:
                # Words spoken before the cut belong to this shot.
                end=max(word_cursor,sum(1 for s in starts if s<cursor))
            else:
                end=max(word_cursor+1,round(len(words)*cursor/frames))
            shot=copy.deepcopy(scene)
            shot.update(id=f"{scene['id']}-shot-{index+1}",parent_scene_id=scene['id'],script_segment=' '.join(words[word_cursor:end]),target_seconds=length/30)
            # Shots of one section continue a single camera move and graphic reveal.
            shot.setdefault('parameters',{})['camera_span']=[round(begin/frames,6),round(cursor/frames,6)]
            if starts:
                # Spoken start of each caption word, in frames from this shot's start.
                shot['word_frames']=[max(0,min(length-1,f-begin)) for f in starts[word_cursor:end]]
            word_cursor=end
            result['scenes'].append(shot)
            edits.append({'id':shot['id'],'seconds':length/30,'media_id':None,'trim_start':0,'transition':'cut'})
    basis=' Visual shots subdivided in whole frames inside aligned narration sections'
    basis+='; cuts snapped to recognized word starts.' if spoken else '; internal shot boundaries are editorial cuts, not newly recognized word boundaries.'
    derived=copy.deepcopy(job);derived.update(id=str(uuid4()),plan_id=result['id'],parent_alignment_id=job['id'],stage='Spoken timing applied; shorter visual shots prepared')
    derived['result'].update(scenes=edits,timing_basis=job['result']['timing_basis']+basis)
    derived['result'].pop('word_frames',None)
    return result,derived,edits
