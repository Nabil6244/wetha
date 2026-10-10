import asyncio
from types import SimpleNamespace
from app.footage_expansion import needs,FootageExpansion
from app.contracts import FootageExpansionRequest


def plan():
    return {'id':'plan','scenes':[{'id':'fl','script_segment':'Florida rain and flooding','parameters':{'source_advisory_id':'fl'}},{'id':'al','script_segment':'Alabama storm winds','parameters':{'source_advisory_id':'al'}}]}


def test_search_needs_use_each_story_location_not_only_primary_advisory():
    store=SimpleNamespace(advisory=lambda _:SimpleNamespace(area=''))
    rows=needs(plan(),store)
    assert {'Florida rain','Florida flood','Alabama storm','Alabama wind'}=={r['query'] for r in rows}
    assert all(r['scene_ids']==['fl'] for r in rows if 'Florida' in r['query'])


def test_area_codes_are_unique_and_marine_distances_are_not_states():
    selected={'scenes':[{'id':'marine','script_segment':'Dangerous waves',
        'parameters':{'source_advisory_id':'marine'}}]}
    store=SimpleNamespace(advisory=lambda _:SimpleNamespace(
        area='Fernandina Beach FL out 20 NM; Altamaha Sound GA to FL from 20 to 60 NM'))
    rows=needs(selected,store)
    assert rows[0]['regions']==['FL','GA']
    assert rows[0]['query']=='Florida Georgia waves'


def test_expansion_downloads_new_clips_skips_duplicates_and_retains_location_review():
    async def run():
        selected=plan();calls=[];imports=[]
        store=SimpleNamespace(visual_plan=lambda _:selected,advisory=lambda _:SimpleNamespace(area=''))
        class Discovery:
            production=SimpleNamespace(store=store,validate_plan=lambda p,**kwargs:None)
            async def search(self,body):
                calls.append(body.query)
                return {'warnings':[],'results':[
                    {'id':'0'*64,'local_media_id':'local-old','kind':'video','reuse_basis':'cc_by'},
                    {'id':'a'*64,'title':'Florida rain','kind':'video','reuse_basis':'cc_by','width':1280,'bytes':1024},
                    {'id':'b'*64,'title':'Unlicensed','kind':'video','reuse_basis':'unknown'}]}
            async def import_candidate(self,body):
                imports.append(body.candidate_id)
                return {'id':'local-new','name':'new.mp4','seconds':30,'source':'source','license':'CC BY 4.0'}
        manager=FootageExpansion(Discovery())
        job=manager.start(FootageExpansionRequest(plan_id='plan',max_new_clips=1))
        await asyncio.gather(*manager.tasks)
        result=manager.get(job['id'])
        assert result['status']=='completed' and imports==['a'*64]
        assert result['duplicates']==1
        assert result['imported'][0]['needs_location_review']
        assert result['imported'][0]['required_regions']==['FL']
        assert calls==['Florida rain'] or calls==['Florida flood']
        await manager.close()
    asyncio.run(run())
