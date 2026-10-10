from types import SimpleNamespace
from app.bulletin_edit import draft


def scenes(count=40):
    return [{'id':str(i),'type':'lower_third','seconds':7,'script_segment':'Storm winds and rain.',
        'parameters':{'source_advisory_id':'source'},'media_id':None,'trim_start':0,'transition':'cut',
        'cuts':[],'map_mode':'auto','graphic_style':'auto','regional_focus':'auto'} for i in range(count)]


def assets(count=20):
    return [{'id':str(i),'kind':'video','name':'Storm winds and rain','seconds':60,'rights_confirmed':True,
             'context':'illustrative','attribution':'Synthetic fixture','source':'Synthetic fixture','catalog':{'tags':['storm','rain','wind']}} for i in range(count)]


def test_mixed_draft_preserves_audio_duration_and_uses_distinct_ranges_with_cooldown():
    timeline={'scenes':scenes()}
    source=lambda _:SimpleNamespace(event_key='test')
    result=draft(timeline,assets(),source)
    assert result['coverage']['footage_fraction']>=.3
    assert result['seconds']==280
    assert [s['id'] for s in result['scenes']]==[s['id'] for s in timeline['scenes']]
    ranges={};last={};cursor=0
    for scene in result['scenes']:
        for cut in scene['cuts']:
            assert 2.5<=cut['seconds']<=5
            identity=cut['media_id'];start=cut['trim_start'];end=start+cut['seconds']
            assert not any(start<b and end>a for a,b in ranges.get(identity,[]))
            assert cursor-last.get(identity,-9999)>=120
            ranges.setdefault(identity,[]).append((start,end));last[identity]=cursor+scene['seconds']
        cursor+=scene['seconds']
    assert not any(s['cuts'] for s in timeline['scenes'])


def test_missing_location_footage_is_exposed_and_manual_maps_are_preserved():
    rows=scenes(10)
    for s in rows:s['script_segment']='Storm winds in Florida.'
    rows[1]['map_mode']='warnings'
    result=draft({'scenes':rows},assets(),lambda _:SimpleNamespace(event_key='test'))
    assert not result['ready'] and result['coverage']['footage_clips']==0
    assert result['scenes'][1]['map_mode']=='warnings'
    assert 'footage_gap' in {i['code'] for i in result['issues']}


def test_bulletin_edit_endpoint_returns_a_reviewable_draft_without_rendering(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_production import prepare
    with TestClient(create_app(tmp_path)) as client:
        _,plan,body=prepare(client)
        body['presentation']='broadcast'
        for scene in body['scenes']:scene['seconds']=7
        response=client.post('/api/production/bulletin-edit',json=body)
        assert response.status_code==200,response.text
        result=response.json()
        assert [s['id'] for s in result['scenes']]==[s['id'] for s in plan['scenes']]
        assert result['seconds']==7*len(plan['scenes'])
        assert result['coverage']['footage_clips']==0 and not result['ready']
        assert not client.get('/api/production/progress').json()['renders']


def test_four_to_six_second_beats_receive_footage_and_short_beats_are_counted():
    rows=scenes(12)
    for i,s in enumerate(rows):s['seconds']=[5,2,4.5][i%3]
    result=draft({'scenes':rows},assets(),lambda _:SimpleNamespace(event_key='test'))
    lengths=[c['seconds'] for s in result['scenes'] for c in s['cuts']]
    assert lengths and all(2.5<=n<=5 for n in lengths)
    assert any(s['seconds'] in (5,4.5) and s['cuts'] for s in result['scenes'])
    assert result['coverage']['short_beats_without_footage']>0


def test_footage_runs_vary_instead_of_strictly_alternating():
    result=draft({'scenes':scenes(40)},assets(),lambda _:SimpleNamespace(event_key='test'))
    flags=[bool(s['cuts']) for s in result['scenes']]
    runs=[];count=0
    for flag in flags+[False]:
        if flag:count+=1
        elif count:runs.append(count);count=0
    assert max(runs)==2 and all(n<=2 for n in runs)
    assert not flags[0]
