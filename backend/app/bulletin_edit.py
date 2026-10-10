"""Draft mixed bulletins from reviewed local media; never loop or invent footage."""
import copy
from . import media_selection, regional, footage_library
from .automatic_edit import shot_frames, MIN_SHOT

MAX_RUN=2


def draft(timeline, media, advisory_lookup, unavailable=()):
    edits=[];issues=[];short_beats=0;offsets={};last_end={};uses={};gaps={};cursor=0;footage_seconds=0;clip_count=0
    by_id={a['id']:a for a in media}
    reserved={s['media_id'] for s in timeline['scenes'] if s.get('media_id')} | {c['media_id'] for s in timeline['scenes'] for c in s.get('cuts',[])}
    for index,scene in enumerate(timeline['scenes']):
        edit={k:copy.deepcopy(scene[k]) for k in ('id','seconds','media_id','trim_start','transition','cuts','map_mode','graphic_style','regional_focus')}
        edit['cuts']=[{k:c[k] for k in ('media_id','seconds','trim_start')} for c in edit['cuts']]
        # Keep chosen shots and source graphs. New footage alternates with graphics.
        protected=bool(scene['parameters'].get('report_graphs')) or scene['type']=='what_changed' or edit['map_mode']!='auto' or edit['graphic_style']!='auto' or index==0
        # Footage runs of up to MAX_RUN beats, then a graphic, so the rhythm is not a strict alternation.
        run=0
        for previous in reversed(edits):
            if not (previous['media_id'] or previous['cuts']):break
            run+=1
        needs_footage=footage_seconds < (cursor+scene['seconds'])*.4
        if not protected and not edit['media_id'] and not edit['cuts'] and needs_footage and run<MAX_RUN:
            frames=round(scene['seconds']*30)
            lengths=shot_frames(frames)
            if frames<MIN_SHOT:
                short_beats+=1
            else:
                choices=media_selection.rank(scene,media,advisory_lookup(scene['parameters']['source_advisory_id']),set(unavailable)|reserved,limit=None)
                proposed=[];proposed_offsets=dict(offsets);proposed_ends=dict(last_end);proposed_uses=dict(uses)
                for length in lengths:
                    seconds=length/30
                    varied=sorted(choices,key=lambda c:(proposed_uses.get(c['media_id'],0),-c['score'],c['media_id']))
                    choice=start=None
                    for c in varied:
                        asset=by_id[c['media_id']]
                        if asset['kind']!='video' or cursor-proposed_ends.get(c['media_id'],-9999)<120:continue
                        # Start on a clean camera shot inside the unused part of the recording.
                        start=footage_library.place(asset,proposed_offsets.get(c['media_id'],c['trim_start']),seconds)
                        if start is not None:
                            choice=c;break
                    if choice is None:
                        break
                    identity=choice['media_id']
                    proposed.append({'media_id':identity,'seconds':seconds,'trim_start':start})
                    proposed_offsets[identity]=start+seconds
                    proposed_ends[identity]=cursor+sum(c['seconds'] for c in proposed)
                    proposed_uses[identity]=proposed_uses.get(identity,0)+1
                if len(proposed)==len(lengths):
                    edit.update(cuts=proposed,map_mode='auto',graphic_style='auto',transition='cut')
                    if edits:edits[-1]['transition']='cut'
                    offsets=proposed_offsets;last_end=proposed_ends;uses=proposed_uses
                else:
                    issues.append({'scene_id':scene['id'],'code':'footage_gap','message':'No unused, location-matched footage available for this beat. Add a different reviewed recording.'})
                    locations=[r['name'] for r in regional.options() if r['code'] in regional.targets(scene)]
                    topics=sorted(media_selection.topics(scene.get('source_claim_text') or scene['script_segment']))
                    query=' '.join(locations+topics) or 'weather footage'
                    gap=gaps.setdefault(query,{'query':query,'locations':locations,'topics':topics,'scene_ids':[],'seconds':0})
                    gap['scene_ids'].append(scene['id']);gap['seconds']+=scene['seconds']
        if edit['cuts'] or edit['media_id']:
            footage_seconds+=edit['seconds'];clip_count+=len(edit['cuts']) or 1
        edits.append(edit);cursor+=scene['seconds']
    ratio=footage_seconds/cursor if cursor else 0
    if ratio<.25:
        issues.append({'code':'low_footage_coverage','message':f'Only {ratio:.0%} footage coverage. Target about 40%; add relevant recordings rather than repeat clips.'})
    return {'scenes':edits,'seconds':round(cursor,3),'ready':not issues,'issues':issues,
            'footage_needs':[{**g,'seconds':round(g['seconds'],1)} for g in gaps.values()],
            'coverage':{'footage_clips':clip_count,'footage_seconds':round(footage_seconds,1),'footage_fraction':round(ratio,3),'short_beats_without_footage':short_beats},
            'note':'Draft only. Review source relevance and visual variety. Cuts are 2.5–5 seconds; beats under 2.5 seconds keep their graphic; source ranges do not overlap and each recording has a two-minute reuse gap.'}
