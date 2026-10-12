"""Find and acquire new licensed video candidates from a bulletin's actual needs."""
import asyncio
import copy
import json
import re
from pathlib import Path
from uuid import uuid4
from .contracts import MediaDiscoveryRequest, DiscoveryImportRequest
from . import regional, media_selection

BUDGET=500*1024*1024
MAX_QUERIES=24
DOWNLOADS=3
MIN_FREE=2*1024**3
ALLOWED_BASIS=('cc_by','public_domain','stock_license')
PRIORITY={'pexels':0,'pixabay':0,'commons':1,'nasa':2,'archive':4}


def free_space(directory):
    import shutil
    try:return shutil.disk_usage(directory or '.').free
    except OSError:return MIN_FREE


# What to search for, per topic: concrete shot descriptions rather than single weather words.
PHRASES={
    'flood':['flooded street','flooded neighborhood','flash flood water'],'waves':['storm surge waves','coastal flooding waves'],
    'rain':['heavy rain street','torrential rain'],'wind':['strong wind trees storm','hurricane wind'],'storm':['storm clouds','thunderstorm'],
    'tornado':['tornado','tornado damage'],'damage':['storm damage houses','debris after storm'],'rescue':['flood rescue boat','emergency crews storm'],
    'cleanup':['storm cleanup','flood cleanup'],'power':['power lines down storm'],'traffic':['flooded road cars'],'lightning':['lightning storm night'],
    'snow':['snowstorm','blizzard'],'hail':['hail storm'],'ice':['ice storm'],'heat':['heat wave city'],'wildfire':['wildfire smoke'],
    'preparedness':['sandbags flood','evacuation traffic'],'residents':['neighborhood flooding residents'],'sky':['dark storm clouds'],
}


# Story-hazard shot descriptions: what footage of this kind of event looks like, by beat topic.
HAZARD_PHRASES={
    'tropical_cyclone':{'wind':'hurricane palm trees wind','waves':'hurricane storm surge waves','flood':'hurricane flooded street',
        'rain':'tropical storm heavy rain','storm':'hurricane waves coast','damage':'hurricane damage houses','rescue':'hurricane rescue boat',
        'default':['hurricane palm trees wind','hurricane storm surge waves','hurricane flooded street','tropical storm heavy rain','hurricane waves coast']},
    'flood':{'rain':'heavy rain flooded street','default':['flooded street','flash flood water','flooded road cars']},
    'tornado':{'default':['tornado','tornado damage','supercell storm']},
    'severe_storm':{'default':['thunderstorm lightning','severe storm wind trees','hail storm']},
    'winter':{'default':['snowstorm road','blizzard','ice storm']},
    'heat':{'default':['heat wave city','heat haze road']},
}
HAZARD_NOUN={'tropical_cyclone':'hurricane','flood':'flooding','tornado':'tornado','severe_storm':'storm','winter':'snowstorm','heat':'heat wave'}


def story_regions(scope,advisory,names):
    """States for located searches: the beat first, then the advisory area, warnings and text (", FL" style codes)."""
    regions=regional.named_regions(scope)
    if regions:return regions
    sources=[advisory.area or '',' '.join(getattr(advisory,'warnings',None) or []),getattr(advisory,'forecast_excerpt',None) or '']
    for text in sources:
        regions+=regional.named_regions(text)
        # Marine distances such as "20 NM" are nautical miles, not New Mexico.
        cleaned=re.sub(r'\b\d+\s*NM\b','',text)
        regions+=[code for code in re.findall(r'(?:^|[,;(]\s*|\s)([A-Z]{2})\b',cleaned) if code in names]
        if regions:break
    if not regions and getattr(advisory,'provider',None)=='NWS':
        regions=regional.named_regions(getattr(advisory,'text','') or '')
    return list(dict.fromkeys(regions))


def needs(plan,store):
    """Searches built from each beat: its place, its words, the story's hazard and the kind of shot it needs."""
    from .visual_director import classify, story_text
    result={}
    names={r['code']:r['name'] for r in regional.options()}
    def add(query,regions,scene_id):
        query=' '.join(query.split())[:160]
        row=result.setdefault(query,{'query':query,'regions':regions,'scene_ids':[]})
        if scene_id not in row['scene_ids']:row['scene_ids'].append(scene_id)
    from .visual_concepts import beat_need, search_variants
    occurrences={}
    for index,scene in enumerate(plan['scenes']):
        scope=scene.get('source_claim_text') or scene['script_segment']
        # The beat's visual concept decides what to film-search for (rotated so beats sharing a concept differ).
        concept=beat_need(scene['script_segment'])
        concept_queries=search_variants(concept,occurrences.get(concept,0))[:2]
        occurrences[concept]=occurrences.get(concept,0)+1
        advisory=store.advisory(scene['parameters'].get('source_advisory_id') or plan['advisory_id'])
        topics=sorted(media_selection.topics(scope))
        intent=classify(scene['script_segment'],story_text(advisory)) if hasattr(advisory,'title') else {'footage_class':'phenomenon','hazard':'general'}
        # Prefer topics in the shot class the beat needs (impact beats search impact footage first).
        wanted=media_selection.SHOT_CLASSES.get(intent['footage_class'],set())
        topics=sorted(topics,key=lambda t:(t not in wanted,t))
        hazard=HAZARD_PHRASES.get(intent.get('hazard'))
        if not topics and not hazard:
            for query in concept_queries:add(query,[],scene['id'])
            continue
        regions=story_regions(scope,advisory,names)
        location=' '.join(names[r] for r in regions) or (advisory.area or '')[:80]
        for topic in topics[:3]:
            # Located query first (best evidence), then the plain shot description (most stock footage is unlocated).
            add(location+' '+topic,regions,scene['id'])
            add(PHRASES.get(topic,[topic])[0],[],scene['id'])
        if hazard:
            # The story's hazard decides what the footage should look like, so a hurricane beat never searches "storm clouds" alone.
            phrases=[hazard[t] for t in topics if t in hazard] or [hazard['default'][(index+n)%len(hazard['default'])] for n in range(2)]
            for phrase in phrases[:2]:add(phrase,[],scene['id'])
            if regions:add(' '.join(names[r] for r in regions[:2])+' '+HAZARD_NOUN[intent['hazard']],regions,scene['id'])
        # Located evidence first; the beat's concrete visual searches follow.
        for query in concept_queries:add(query,[],scene['id'])
    # Search the biggest gaps first: needs shared by the most beats.
    return sorted(result.values(),key=lambda r:-len(r['scene_ids']))


class FootageExpansion:
    def __init__(self,discovery):
        self.discovery=discovery;self.jobs={};self.tasks=set()
        path=getattr(discovery.production.store,'path',None)
        self.directory=Path(path).parent/'footage-searches' if path else None
        if self.directory:
            self.directory.mkdir(parents=True,exist_ok=True)
            for saved in self.directory.glob('*.json'):
                try:job=json.loads(saved.read_text())
                except (OSError,ValueError):continue
                if job.get('status') in ('queued','running'):
                    # The search task did not survive an application restart.
                    job.update(status='failed',error='Footage search stopped when the application closed. Imported clips remain in the library; run it again for the rest.')
                    self.save(job)
                self.jobs[job['id']]=job

    def save(self,job):
        if self.directory:(self.directory/f"{job['id']}.json").write_text(json.dumps(job))

    def start(self,body):
        plan=self.discovery.production.store.visual_plan(body.plan_id)
        self.discovery.production.validate_plan(plan, require_support=False)
        for job in self.jobs.values():
            if job['status'] in ('queued','running'):
                if job['plan_id']==body.plan_id:return copy.deepcopy(job)
                raise ValueError('A footage search is already running. Wait for it to finish.')
        queries=needs(plan,self.discovery.production.store)
        job={'id':str(uuid4()),'plan_id':body.plan_id,'status':'queued','stage':'Finding footage for the script',
             'progress':0,'queries':queries,'imported':[],'duplicates':0,'issues':[],'error':None,'searched':0,'max_new_clips':body.max_new_clips}
        self.jobs[job['id']]=job;self.save(job)
        task=asyncio.create_task(self.run(job,plan))
        self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        return copy.deepcopy(job)

    def get(self,identity):
        if identity not in self.jobs:raise KeyError(identity)
        return copy.deepcopy(self.jobs[identity])

    async def close(self):
        for task in self.tasks:task.cancel()
        if self.tasks:await asyncio.gather(*self.tasks,return_exceptions=True)

    async def run(self,job,plan):
        job['status']='running';seen=set();downloaded=0
        # Rotate queries between runs so later batches explore the full bulletin.
        queries=job['queries'];start=sum(j['searched'] for j in self.jobs.values() if j['plan_id']==plan['id'] and j['id']!=job['id'])%max(1,len(queries))
        queries=(queries[start:]+queries[:start])[:MAX_QUERIES]
        try:
            for i,need in enumerate(queries):
                self.discovery.production.validate_plan(plan, require_support=False)
                job.update(stage='Searching '+need['query'],progress=i/max(1,len(queries)))
                result=await self.discovery.search(MediaDiscoveryRequest(query=need['query'],provider='all',kind='video',plan_id=plan['id'],live=True))
                job['searched']+=1;self.save(job)
                job['issues'].extend(result['warnings'])
                eligible=[]
                for candidate in result['results']:
                    if candidate['id'] in seen:continue
                    seen.add(candidate['id'])
                    if candidate.get('local_media_id'):
                        job['duplicates']+=1;continue
                    if candidate['kind']!='video' or candidate.get('reuse_basis') not in ALLOWED_BASIS:continue
                    if candidate.get('width') and candidate['width']<640:continue
                    if candidate.get('provider')=='archive' and candidate.get('archive_verdict')!='strong':
                        job.setdefault('needs_review',[]).append({'title':candidate['title'],'source':candidate['source'],'reasons':candidate.get('archive_reasons',[])})
                        continue  # Archive items short of strong evidence are listed for review, never imported automatically.
                    eligible.append(candidate)
                # Licensed stock first, then Wikimedia and NASA, with the Internet Archive last.
                eligible.sort(key=lambda c:PRIORITY.get(c.get('provider'),3))
                room=job['max_new_clips']-len(job['imported'])
                # Bounded parallel downloads; each file still counts its real bytes against the batch budget.
                gate=asyncio.Semaphore(DOWNLOADS)
                async def fetch(candidate):
                    nonlocal downloaded
                    async with gate:
                        if len(job['imported'])>=job['max_new_clips']:return
                        size=candidate.get('bytes') or 0
                        if downloaded+size>BUDGET:
                            job['issues'].append('This batch reached its 500 MiB download budget. Run another batch for remaining needs.');return
                        if free_space(self.directory)<MIN_FREE:
                            job['issues'].append('Less than 2 GiB of disk space is free; downloads paused.');return
                        downloaded+=size  # Reserve now so parallel downloads cannot overshoot the budget.
                        job['stage']='Adding '+candidate['title']
                        for attempt in range(3):
                            try:
                                asset=await self.discovery.import_candidate(DiscoveryImportRequest(candidate_id=candidate['id'],rights_confirmed=True))
                                break
                            except ValueError as error:
                                transient='download failed' in str(error)
                                if not transient or attempt==2:
                                    downloaded-=size;job['issues'].append(candidate['title']+': '+str(error));return
                                await asyncio.sleep(1.5*(2**attempt))
                            except KeyError as error:
                                downloaded-=size;job['issues'].append(candidate['title']+': '+str(error));return
                        if asset.get('duplicate'):
                            downloaded-=size;job['duplicates']+=1;return
                        downloaded+=(asset.get('bytes') or 0)-size
                        if asset.get('seconds') and asset['seconds']<5:
                            job['issues'].append(asset['name']+': under five seconds; it gives at most one cut.')
                        if len(job['imported'])<job['max_new_clips']:
                            job['imported'].append({'id':asset['id'],'name':asset['name'],'query':need['query'],
                                'seconds':asset['seconds'],'source':asset['source'],'license':asset['license'],
                                'needs_location_review':bool(need['regions']), 'required_regions':need['regions']})
                        self.save(job)
                await asyncio.gather(*(fetch(c) for c in eligible[:max(0,room)*2]))
                if len(job['imported'])>=job['max_new_clips']:break
            job.update(status='completed',progress=1,stage=f"Added {len(job['imported'])} new recordings")
            if not job['imported']:job['issues'].append('No new eligible clips found in this batch. Existing duplicates were skipped; add another source or broaden the location search.')
        except asyncio.CancelledError:
            job.update(status='failed',error='Footage search stopped when the application closed. Imported clips remain in the library.')
            self.save(job)
            raise
        except Exception as error:job.update(status='failed',error=str(error))
        self.save(job)
