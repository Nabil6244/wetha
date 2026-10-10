"""Find and acquire new licensed video candidates from a bulletin's actual needs."""
import asyncio
import copy
import re
from uuid import uuid4
from .contracts import MediaDiscoveryRequest, DiscoveryImportRequest
from . import regional, media_selection


def needs(plan,store):
    result={}
    names={r['code']:r['name'] for r in regional.options()}
    for scene in plan['scenes']:
        scope=scene.get('source_claim_text') or scene['script_segment']
        topics=sorted(media_selection.topics(scope))
        if not topics:continue
        regions=regional.named_regions(scope)
        advisory=store.advisory(scene['parameters']['source_advisory_id'])
        if not regions:
            regions=regional.named_regions(advisory.area)
            # Marine distances such as "20 NM" are nautical miles, not New Mexico.
            area_codes=re.sub(r'\b\d+\s*NM\b','',advisory.area)
            regions += [code for code in re.findall(r'\b[A-Z]{2}\b',area_codes) if code in names]
        if not regions and getattr(advisory,'provider',None)=='NWS':
            regions=regional.named_regions(advisory.text)
        regions=list(dict.fromkeys(regions))
        location=' '.join(names[r] for r in regions) or advisory.area[:80]
        # Search variants separately instead of requiring every weather term in one title.
        for topic in topics[:3]:
            query=(location+' '+topic).strip()[:160]
            row=result.setdefault(query,{'query':query,'regions':regions,'scene_ids':[]})
            row['scene_ids'].append(scene['id'])
    return list(result.values())


class FootageExpansion:
    def __init__(self,discovery):
        self.discovery=discovery;self.jobs={};self.tasks=set()

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
        self.jobs[job['id']]=job
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
        queries=(queries[start:]+queries[:start])[:12]
        try:
            for i,need in enumerate(queries):
                self.discovery.production.validate_plan(plan, require_support=False)
                job.update(stage='Searching '+need['query'],progress=i/max(1,len(queries)))
                result=await self.discovery.search(MediaDiscoveryRequest(query=need['query'],provider='all',kind='video',plan_id=plan['id'],live=True))
                job['searched']+=1
                job['issues'].extend(result['warnings'])
                for candidate in result['results']:
                    if len(job['imported'])>=job['max_new_clips']:break
                    if candidate['id'] in seen:continue
                    seen.add(candidate['id'])
                    if candidate.get('local_media_id'):
                        job['duplicates']+=1;continue
                    if candidate['kind']!='video' or candidate.get('reuse_basis') not in ('cc_by','public_domain'):continue
                    if candidate.get('width') and candidate['width']<640:continue
                    size=candidate.get('bytes',250*1024*1024)
                    if downloaded+size>500*1024*1024:
                        job['issues'].append('This batch reached its 500 MiB download budget. Run another batch for remaining needs.');continue
                    job['stage']='Adding '+candidate['title']
                    try:
                        asset=await self.discovery.import_candidate(DiscoveryImportRequest(candidate_id=candidate['id'],rights_confirmed=True))
                        downloaded+=size
                        if asset.get('duplicate'):job['duplicates']+=1;continue
                        job['imported'].append({'id':asset['id'],'name':asset['name'],'query':need['query'],
                            'seconds':asset['seconds'],'source':asset['source'],'license':asset['license'],
                            'needs_location_review':bool(need['regions']), 'required_regions':need['regions']})
                    except (ValueError,KeyError) as error:job['issues'].append(candidate['title']+': '+str(error))
                if len(job['imported'])>=job['max_new_clips']:break
            job.update(status='completed',progress=1,stage=f"Added {len(job['imported'])} new recordings")
            if not job['imported']:job['issues'].append('No new eligible clips found in this batch. Existing duplicates were skipped; add another source or broaden the location search.')
        except asyncio.CancelledError:
            job.update(status='failed',error='Footage search stopped when the application closed. Imported clips remain in the library.')
            raise
        except Exception as error:job.update(status='failed',error=str(error))
