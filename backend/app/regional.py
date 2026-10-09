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
    # Full names avoid treating ordinary words such as IN, OR and ME as states.
    return [r['code'] for r in catalogue()['regions']
            if re.search(r'(?<!\w)'+re.escape(r['name'])+r'(?!\w)',text,re.I)]


def targets(scene):
    names=named_regions(scene.get('script_segment',''))
    focus=scene.get('regional_focus','auto')
    if focus!='auto':
        if names and focus not in names:
            raise ValueError('Scene focus conflicts with the locations named in its script.')
        return [focus]
    return names


def match_media(scene,asset):
    wanted=targets(scene)
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


def focus(scene,media,presentation):
    wanted=targets(scene)
    if not wanted:return {'regions':[], 'status':'unscoped'}
    regions=[r for r in catalogue()['regions'] if r['code'] in wanted]
    if len(regions)!=len(set(wanted)):raise ValueError('Unknown regional focus.')
    names=', '.join(r['name'] for r in regions)
    selected=[media[c['media_id']] for c in scene.get('cuts',[])]
    if scene.get('media_id'):selected.append(media[scene['media_id']])
    if selected:
        for asset in selected:
            if not match_media(scene,asset):
                raise ValueError(f"{names}: {asset['name']} needs a matching capture region and a reviewed location reference. Unknown or unrelated footage cannot cover this scene.")
        return {'regions':wanted,'status':'reviewed_capture_location','note':'Location is editor-attested from the recorded reference; event attribution remains separately labeled.'}
    if presentation!='broadcast':
        raise ValueError(f'{names}: use Broadcast style for a region-focused source graphic or choose location-reviewed footage.')
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
    p['regional_cartography']={k:catalogue()[k] for k in ('source_url','source_checksum','year','note')}
    p['facts']={} # Prevent automatically drawing storm-wide winds/pressure over a local scene.
    if sd.get('camera',{}).get('geographic_target') and not intersects(bounds,{'coordinates':sd['camera']['geographic_target']}):
        sd['camera'].update(geographic_target=None,movement='smooth_zoom_in')
    has_data=bool(filtered or p.get('map_observations'))
    if not has_data:
        sd['layers']=[];sd['fallback']='No source weather layer available for '+names
        p['fallback_label']=sd['fallback'];p['map_has_layer']=False
    p['credit'] += ' · '+names+' · Census 2024 boundaries'
    return {'regions':wanted,'status':'regional_source_context' if has_data else 'missing_regional_weather',
            'note':'Map extent matches the region. Layer intersection indicates regional context, not a measurement at every local point.',
            'cartography_checksum':catalogue()['source_checksum']}


def coverage(plans,assets):
    rows=[]
    for plan in plans:
        for scene in plan['scenes']:
            wanted=targets(scene)
            if wanted:
                matches=[a['id'] for a in assets if a['kind']!='audio' and a.get('rights_confirmed') and match_media(scene,a)]
                rows.append({'plan_id':plan['id'],'scene_id':scene['id'],'script_segment':scene['script_segment'],
                             'regions':wanted,'matching_media_ids':matches,'needs_footage':not bool(matches),
                             'data_requirement':'Use local source measurements; storm-wide values are not local observations.'})
    return {'scenes':rows,'note':'Capture locations require source review. Unknown-location stock is excluded from named regional scenes.'}
