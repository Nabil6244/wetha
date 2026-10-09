"""One-storm hour structure and content/pacing audit. Never pad a short report."""
import hashlib
import re
from collections import Counter

CHAPTERS=[
 ('hook',120,'The night everything changed','Why did the coast face a stronger storm?', ['satellite','question_reveal','comparison_split'],['A concise hook, stakes and chapter roadmap']),
 ('origins',240,'How the storm reached this point','What happened before the final approach?', ['advisory_timeline','track','source_card'],['Earlier official advisories and origin chronology']),
 ('strengthening',360,'The final twelve hours','Which reported measurements changed?', ['change_gauge','comparison_split','advisory_timeline'],['Multiple sourced measurements; distinct explanations of wind and pressure']),
 ('warnings',300,'The coast on alert','Which places were warned, and when?', ['warnings','regional_closeup','source_card'],['Dated official warning updates; source-linked town and county coverage']),
 ('landfall',360,'The crossing','What do the real observation sequences show?', ['radar','satellite','advisory_timeline'],['Chronological observation sequences and independently sourced landfall details']),
 ('rainfall',420,'The inland rain story','Where did rain totals differ?', ['rainfall','regional_closeup','comparison_split'],['Multiple actual gauge totals, rainfall analysis and verified inland impacts']),
 ('coast',300,'Wind and water at the shore','What changed from place to place?', ['regional_closeup','footage','source_card'],['Event-linked coastal imagery and measured wind/surge reports']),
 ('inland',360,'A storm moving north','How did the event evolve away from the coast?', ['track','radar','forecast_clock'],['Later advisories, inland observation frames and region-specific accounts']),
 ('forecast',300,'What was forecast, what was observed','Where was there uncertainty?', ['forecast','forecast_clock','comparison_split'],['Matching forecast issue/valid times and subsequent observations; avoid hindsight framing']),
 ('record',360,'Reconstructing the evidence','Which facts can the archive establish?', ['advisory_timeline','source_card','question_reveal'],['Independent reports, source chronology and explicit limits on unmeasured claims']),
 ('lessons',300,'Reading a storm beyond one number','What does each weather graphic actually tell us?', ['question_reveal','forecast','radar'],['Official educational references and explanatory demonstrations']),
 ('payoff',180,'The whole picture','What did the evidence show across the hour?', ['comparison_split','track','source_card'],['Concise earned answers to opening questions; no replay montage used as filler']),
]
assert sum(c[1] for c in CHAPTERS)==3600

RULES={'footage_cut_seconds':[3,4], 'graphic_hold_seconds':[4,9],
 'minimum_shots':600,'minimum_families_per_chapter':4,'maximum_same_family_in_a_row':2,
 'maximum_source_uses_per_chapter':3,'source_reappearance_gap_seconds':120,
 'minimum_script_words':5400,'target_script_words':[7000,8500],
 'new_question_or_reveal_seconds':[45,90], 'footage_fraction_target':.25,
 'note':'Editorial targets, not a guarantee of audience retention. Never invent measurements or urgency to meet pacing.'}


def blueprint(media):
    chapters=[];cursor=0
    for identity,seconds,title,question,graphics,needs in CHAPTERS:
        chapters.append({'id':identity,'title':title,'question':question,'seconds':seconds,'start_seconds':cursor,
            'graphics':graphics,'needs':needs,'minimum_shots':seconds//6})
        cursor+=seconds
    usable=[m for m in media if m['kind']=='video' and m.get('rights_confirmed')]
    return {'format':'storm_deep_dive_60','seconds':3600,'frames':108000,'chapters':chapters,'rules':RULES,
        'library':{'independent_video_sources':len({m['checksum'] for m in usable}),
            'total_video_seconds':round(sum(m['seconds'] for m in usable),1),
            'footage_seconds_target':900,'three_to_four_second_cuts_target':[225,300]},
        'ready':False,'note':'A chapter blueprint. Assign completed source-linked timelines and run the content audit before planning a full-hour export.'}


def audit(assignments, lookup):
    issues=[];durations={};families={};shots=[];words=0;seen_timelines=set();claim_chapters={};event=None
    by_chapter={a['chapter_id']:a['timeline_ids'] for a in assignments}
    if len(by_chapter)!=len(assignments):raise ValueError('A chapter may only be assigned once.')
    known={c[0] for c in CHAPTERS}
    if set(by_chapter)-known:raise ValueError('Unknown chapter ID.')
    for identity,seconds,title,*_ in CHAPTERS:
        chapter_shots=[];duration=0;chapter_words=0;chapter_claims=set()
        for timeline_id in by_chapter.get(identity,[]):
            if timeline_id in seen_timelines:
                issues.append({'chapter_id':identity,'code':'repeated_timeline','message':'A short timeline cannot be replayed to fill another chapter.'});continue
            seen_timelines.add(timeline_id)
            timeline=lookup(timeline_id)
            if timeline.get('event_id'):
                if event is None:event=timeline['event_id']
                elif timeline['event_id']!=event:issues.append({'chapter_id':identity,'code':'different_storm','message':'This deep dive must use one storm event. Label unrelated archival footage within its own source context.'})
            if timeline.get('superseded'):issues.append({'chapter_id':identity,'code':'superseded','message':'Create a timeline from the current script revision.'})
            for scene in timeline['scenes']:
                text=scene.get('source_claim_text') or scene['script_segment']
                fingerprint=hashlib.sha256(' '.join(text.split()).casefold().encode()).hexdigest()
                if fingerprint not in chapter_claims:
                    chapter_words+=len(re.findall(r'\b\w+\b',scene['script_segment']));chapter_claims.add(fingerprint)
                    if fingerprint in claim_chapters and identity!='payoff':
                        issues.append({'chapter_id':identity,'code':'repeated_script','message':'This source passage was already used in '+claim_chapters[fingerprint]+'. Add a new chapter-specific explanation.'})
                    claim_chapters.setdefault(fingerprint,identity)
                cuts=scene.get('cuts') or [{'media_id':scene.get('media_id'),'seconds':scene['seconds'],'trim_start':scene.get('trim_start',0)}]
                for cut in cuts:
                    media=cut.get('media_id');length=cut['seconds']
                    family='footage' if media else scene.get('graphic_style','auto')
                    if family=='auto':family=scene.get('map_mode','auto')
                    if family=='auto':family=scene.get('direction',{}).get('scene_type',scene['type'])
                    chapter_shots.append({'chapter_id':identity,'family':family,'seconds':length,'media_id':media,'trim_start':cut.get('trim_start',0)})
                    if media and not 3<=length<=4:issues.append({'chapter_id':identity,'code':'footage_hold','message':'Footage cuts must last 3–4 seconds.'})
                    if not media and length>9:issues.append({'chapter_id':identity,'code':'graphic_hold','message':'A graphic holds longer than nine seconds. Add a new sourced visual beat.'})
                    duration+=length
        durations[identity]=duration;words+=chapter_words
        families[identity]=len({s['family'] for s in chapter_shots})
        if abs(duration-seconds)>.02:issues.append({'chapter_id':identity,'code':'chapter_duration','message':f'{title}: {duration:g}s assigned / {seconds}s required.'})
        if duration and len(chapter_shots)<seconds//6:issues.append({'chapter_id':identity,'code':'too_few_shots','message':'This chapter needs more distinct visual beats; do not extend existing holds.'})
        if duration and families[identity]<4:issues.append({'chapter_id':identity,'code':'visual_variety','message':'Use at least four visual families in this chapter.'})
        uses=Counter(s['media_id'] for s in chapter_shots if s['media_id'])
        if any(n>3 for n in uses.values()):issues.append({'chapter_id':identity,'code':'source_overuse','message':'One recording appears more than three times in this chapter. Add independently filmed material.'})
        shots.extend(chapter_shots)
    last_family=None;run=0;cursor=0;ranges={};last_media={}
    for shot in shots:
        family=shot['family'];run=run+1 if family==last_family else 1;last_family=family
        if run==3:issues.append({'chapter_id':shot['chapter_id'],'code':'repetitive_sequence','message':'More than two consecutive shots use the same visual family.'})
        media=shot['media_id']
        if media:
            start=shot['trim_start'];end=start+shot['seconds']
            if any(start<b-.01 and end>a+.01 for a,b in ranges.get(media,[])):
                issues.append({'chapter_id':shot['chapter_id'],'code':'repeated_clip','message':'Footage source ranges overlap. Choose unused footage.'})
            ranges.setdefault(media,[]).append((start,end))
            if media in last_media and cursor-last_media[media]<120:
                issues.append({'chapter_id':shot['chapter_id'],'code':'source_cooldown','message':'The same recording returns within two minutes. Use a different source.'})
            last_media[media]=cursor+shot['seconds']
        cursor+=shot['seconds']
    if words<RULES['minimum_script_words']:issues.append({'code':'short_script','message':f'{words} distinct edited words / at least 5400 needed for the hour. Write and source the missing chapters.'})
    return {'ready':not issues,'seconds':round(sum(durations.values()),3),'target_seconds':3600,
        'shots':len(shots),'script_words':words,'chapter_seconds':durations,'chapter_families':families,'issues':issues,
        'note':'Content and pacing audit only; completed chapter renders and a final frame/decode check are still required for export.'}
