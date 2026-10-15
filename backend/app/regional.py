"""Regional editorial relevance. Source declarations are review attestations, not geolocation inference."""
import copy,json,re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def catalogue():
    return json.loads((Path(__file__).parent/'data/us-regions.json').read_text())


def options():
    return [{'code':r['code'],'name':r['name']} for r in catalogue()['regions']]


def named_regions(text):
    return list(_named_regions(text))


@lru_cache(maxsize=4096)
def _named_regions(text):
    # Full names avoid treating ordinary words such as IN, OR and ME as states.
    return tuple(r['code'] for r in catalogue()['regions']
            if re.search(r'(?<!\w)'+re.escape(r['name'])+r'(?!\w)'+(r'(?!\s+River\b)' if r['code']=='MS' else ''),text,re.I))


def targets(scene):
    scope=scene.get('source_claim_text') or scene.get('script_segment','')
    names=named_regions(scope)
    focus=scene.get('regional_focus','auto')
    if focus!='auto':
        if names and focus not in names:
            raise ValueError('Scene focus conflicts with the locations named in its script.')
        return [focus]
    if scene.get('type')=='storm_track' and re.search(r'\b(?:center|centre)\b[\s\S]*\blatitude\b',scope,re.I):
        # A basin-wide forecast can mention a coastal observation station. That
        # station must not crop the offshore storm out of the entire scene.
        return []
    return names


def split_targets(scene):
    """(primary, cited) among the states a beat names: primary are those the shot's own warning areas touch,
    or, when it names none of them, the state its warning areas lie in; cited are named for other stories the
    beat cites. Without own warning areas to test, all named states are primary."""
    wanted=targets(scene)
    # The story's location is its own warning areas; a storm-centre point or track is not a place claim.
    own=[f['geometry'] for f in scene.get('parameters',{}).get('geojson',{}).get('features',[]) if f.get('geometry') and f.get('properties',{}).get('kind')=='alert_area']
    index={r['code']:r for r in catalogue()['regions']}
    if not own or scene.get('regional_focus','auto')!='auto':
        return wanted,[]
    primary=[c for c in wanted if c in index and any(intersects(index[c]['bounds'],g) for g in own)]
    if not primary:
        # The beat names only other stories' places: the shot is located by its own geography instead.
        pts=[q for g in own for q in points(g['coordinates'])]
        x,y=sum(q[0] for q in pts)/len(pts),sum(q[1] for q in pts)/len(pts)
        primary=[c for c,r in index.items() if r['bounds'][0]<=x<=r['bounds'][2] and r['bounds'][1]<=y<=r['bounds'][3]]
        if not primary:
            return wanted,[]
    return primary,[c for c in wanted if c not in primary]


# Practical coverage groups: footage reviewed in one state can stand in, labelled with where it was filmed,
# for a story in a comparable state of the same group. Not a claim that a hazard is confined to a group.
COMPARABLE=({'FL','TX','LA','MS','AL'},{'GA','SC','NC','TN','AL','FL','VA','KY'},{'OK','KS','NE','TX','SD','ND','CO'},
            {'IL','MO','IA','AR','IN','OH','KY','WI','MN'},{'CA','OR','WA','NV','AZ','UT','CO','NM','ID','MT','WY'},
            {'NY','NJ','PA','CT','MA','RI','NH','VT','ME','MD','DE','DC','VA'},{'MI','WI','MN','OH','IL','IN','NY','PA'})


def location_status(scene,asset):
    """'unscoped' (beat names no place), 'reviewed' (reviewed capture region matches), 'nearby' (reviewed
    capture region is a comparable state; shown labelled with its own location), 'elsewhere' (reviewed
    capture region is an unrelated place), or 'unverified' (location unknown or only declared)."""
    wanted=targets(scene)
    if not wanted:return 'unscoped'
    if match_media(scene,asset):return 'reviewed'
    cat=asset.get('catalog',{})
    if cat.get('location_reviewed') and cat.get('region_codes'):
        filmed=set(cat['region_codes'])
        return 'nearby' if cat.get('reference') and any(g&filmed and g&set(wanted) for g in COMPARABLE) else 'elsewhere'
    return 'unverified'


def match_media(scene,asset,wanted=None):
    if wanted is None:wanted=targets(scene)
    if not wanted:return True
    cat=asset.get('catalog',{})
    return bool(cat.get('location_reviewed') and cat.get('reference') and set(wanted)&set(cat.get('region_codes',[])))


def points(value):
    if len(value)>=2 and isinstance(value[0],(int,float)):return [value[:2]]
    return [p for child in value for p in points(child)]


def intersects(bounds,geometry):
    # Coverage intersection is a viewport relevance check, not local attribution.
    coords=points(geometry['coordinates'])
    if not coords:return False
    west,south,east,north=bounds
    return not (max(p[0] for p in coords)<west or min(p[0] for p in coords)>east or
                max(p[1] for p in coords)<south or min(p[1] for p in coords)>north)


def focus(scene,media,presentation,allow_unverified=False):
    wanted=targets(scene)
    if not wanted:return {'regions':[], 'status':'unscoped'}
    regions=[r for r in catalogue()['regions'] if r['code'] in wanted]
    if len(regions)!=len(set(wanted)):raise ValueError('Unknown regional focus.')
    names=', '.join(r['name'] for r in regions)
    selected=[media[c['media_id']] for c in scene.get('cuts',[])]
    if scene.get('media_id'):selected.append(media[scene['media_id']])
    if selected:
        statuses=[location_status(scene,asset) for asset in selected]
        for asset,status in zip(selected,statuses):
            if status=='reviewed' or (allow_unverified and status in ('unverified','nearby')):continue
            raise ValueError(f"{names}: {asset['name']} needs a matching capture region and a reviewed location reference. Unknown or unrelated footage cannot cover this scene.")
        if 'unverified' in statuses:
            return {'regions':wanted,'status':'illustrative_location_not_verified','note':'Illustrative footage; its filming location is not verified and is labelled on screen.'}
        if 'nearby' in statuses:
            return {'regions':wanted,'status':'comparable_region_footage','note':'Reviewed footage from a comparable region, labelled on screen with where it was filmed.'}
        return {'regions':wanted,'status':'reviewed_capture_location','note':'Location is editor-attested from the recorded reference; event attribution remains separately labeled.'}
    if presentation!='broadcast':
        raise ValueError(f'{names}: use Broadcast style for a region-focused source graphic or choose location-reviewed footage.')
    # The map describes the shot's own story; places named only for other cited stories stay as attribution.
    wanted,cited=split_targets(scene)
    regions=[r for r in catalogue()['regions'] if r['code'] in wanted];names=', '.join(r['name'] for r in regions)
    cited_names=', '.join(r['name'] for r in catalogue()['regions'] if r['code'] in cited)
    p=scene['parameters'];sd=scene['direction']
    if scene.get('type')=='what_changed' or scene.get('graphic_style','auto') in ('change_gauge','comparison_split','advisory_timeline','question_reveal','forecast_clock'):
        raise ValueError(f'{names}: storm-wide advisory statistics cannot be presented as local measurements. Supply a source-linked local data scene.')
    if sd.get('asset_ids') and not p.get('map_observations'):
        raise ValueError(f'{names}: native imagery has no verified regional extent. Use geographically registered observations or a local source map.')
    bbox=[min(r['bounds'][0] for r in regions),min(r['bounds'][1] for r in regions),
          max(r['bounds'][2] for r in regions),max(r['bounds'][3] for r in regions)]
    # Padding shows adjacent coastal context, without inferring a warning boundary.
    bounds=[max(-179.9,bbox[0]-.7),max(-84,bbox[1]-.7),min(179.9,bbox[2]+.7),min(84,bbox[3]+.7)]
    if p.get('map_observations') and not intersects(bounds,{'coordinates':[[p['radar_extent'][0],p['radar_extent'][1]],[p['radar_extent'][2],p['radar_extent'][3]]]}):
        raise ValueError(f'{names}: radar coverage does not intersect the requested region.')
    features=p.get('geojson',{}).get('features',[])
    filtered=[copy.deepcopy(f) for f in features if intersects(bounds,f['geometry'])]
    p['geojson']={'type':'FeatureCollection','features':filtered}
    p['records']=[r for r in p.get('records',[]) if intersects(bounds,{'coordinates':r['coordinates']})]
    p['places'] = [(name,coord) for name,coord in p.get('places',[]) if intersects(bounds,{'coordinates':coord})]
    p['map_warning_text'] = [text for text in p.get('map_warning_text',[]) if set(named_regions(text)) & set(wanted)]
    p['map_forecast_text'] = ' '.join(sentence for sentence in re.split(r'(?<=[.!?]) +',p.get('map_forecast_text','')) if set(named_regions(sentence)) & set(wanted))
    p['bounds']=bounds;p['regional_boundaries']=copy.deepcopy(regions);p['regional_title']=names
    if cited_names:p['regional_cited']=cited_names;p['regional_cited_codes']=cited
    else:p.pop('regional_cited',None);p.pop('regional_cited_codes',None)
    p['regional_cartography']={k:catalogue()[k] for k in ('source_url','source_checksum','year','note')}
    # Prevent automatically drawing storm-wide winds/pressure over a local scene; values an NWS alert states for its own area stay.
    from .alert_facts import KEYS
    p['facts']={k:v for k,v in p.get('facts',{}).items() if k in KEYS}
    if sd.get('camera',{}).get('geographic_target') and not intersects(bounds,{'coordinates':sd['camera']['geographic_target']}):
        sd['camera'].update(geographic_target=None,movement='smooth_zoom_in')
    has_data=bool(filtered or p.get('map_observations'))
    if not has_data:
        sd['layers']=[];sd['fallback']='No source weather layer available for '+names
        p['fallback_label']=sd['fallback'];p['map_has_layer']=False
    p['credit'] += ' · '+names+' · Census 2024 boundaries'+(' · Also cited: '+cited_names if cited_names else '')
    return {'regions':wanted,'cited_regions':cited,'status':'regional_source_context' if has_data else 'missing_regional_weather',
            'note':'Map extent matches the region. Layer intersection indicates regional context, not a measurement at every local point.',
            'cartography_checksum':catalogue()['source_checksum']}


def coverage(plans,assets):
    rows=[]
    for plan in plans:
        for scene in plan['scenes']:
            wanted=targets(scene)
            if wanted:
                matches=[a['id'] for a in assets if a['kind']!='audio' and a.get('rights_confirmed') and match_media(scene,a,wanted)]
                rows.append({'plan_id':plan['id'],'scene_id':scene['id'],'script_segment':scene['script_segment'],
                             'regions':wanted,'matching_media_ids':matches,'needs_footage':not bool(matches),
                             'data_requirement':'Use local source measurements; storm-wide values are not local observations.'})
    return {'scenes':rows,'note':'Capture locations require source review. Unknown-location stock is excluded from named regional scenes.'}
