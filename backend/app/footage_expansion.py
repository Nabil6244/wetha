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


def needs(plan,store):
    """Searches built from each beat: its place, its hazard and the kind of shot it needs."""
    from .visual_director import classify, story_text
    result={}
    names={r['code']:r['name'] for r in regional.options()}
    for scene in plan['scenes']:
        scope=scene.get('source_claim_text') or scene['script_segment']
        advisory=store.advisory(scene['parameters']['source_advisory_id'])
        topics=sorted(media_selection.topics(scope))
        intent=classify(scene['script_segment'],story_text(advisory)) if hasattr(advisory,'title') else {'footage_class':'phenomenon'}
        # Prefer topics in the shot class the beat needs (impact beats search impact footage first).
        wanted=media_selection.SHOT_CLASSES.get(intent['footage_class'],set())
        topics=sorted(topics,key=lambda t:(t not in wanted,t))
        if not topics:continue
        regions=regional.named_regions(scope)
        if not regions:
            regions=regional.named_regions(advisory.area)
            # Marine distances such as "20 NM" are nautical miles, not New Mexico.
            area_codes=re.sub(r'\b\d+\s*NM\b','',advisory.area)
            regions += [code for code in re.findall(r'\b[A-Z]{2}\b',area_codes) if code in names]
        if not regions and getattr(advisory,'provider',None)=='NWS':
            regions=regional.named_regions(advisory.text)
        regions=list(dict.fromkeys(regions))
        location=' '.join(names[r] for r in regions) or advisory.area[:80]
        for topic in topics[:3]:
            # Located query first (best evidence), then the plain shot description (most stock footage is unlocated).
            phrase=PHRASES.get(topic,[topic])[0]
            for query,scoped in (((location+' '+topic).strip(),True),(phrase,False)):
                row=result.setdefault(query[:160],{'query':query[:160],'regions':regions if scoped else [],'scene_ids':[]})
                row['scene_ids'].append(scene['id'])
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
                    eligible.append(candidate)
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
