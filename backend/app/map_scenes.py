"""Four geographic scene treatments, with explicit source-availability gates."""
import hashlib
import io
import json
from datetime import datetime
from PIL import Image
from . import broadcast

MODES={'track':'REPORTED MOVEMENT','warnings':'WARNING AREAS','radar':'RADAR: OBSERVED WEATHER','forecast':'FORECAST OUTLOOK'}


def prepare(service, scene, advisory, source, radar_assets=None):
    mode=scene['map_mode'];p=scene['parameters'];features=p.get('geojson',{}).get('features',[])
    p['map_mode']=mode;p['map_warning_text']=advisory.warnings[:3] or ([advisory.area] if advisory.area else [])
    p['map_source_label']='TRAINING' if advisory.provider=='TRAINING' else 'PRERECORDED' if source.historical else 'SOURCE RECORD'
    p['map_forecast_text']=' '.join((advisory.forecast_excerpt or '').split())
    p['map_issue_time']=advisory.issued_at.isoformat()
    p['map_observations']=[]
    fallback=None;layers=['reported_track'];sources=[source];asset_ids=[]
    if mode=='warnings':
        layers=[]
        if not any(f.get('properties',{}).get('kind')=='alert_area' for f in features):
            fallback='No source warning polygon available. Named coverage is shown as text; no boundary is inferred.'
    elif mode=='forecast':
        layers=[]
        assets=[a for a in service.store.visual_assets('forecast_cone') if a['metadata'].get('advisory_id')==advisory.id and a['metadata'].get('advisory_checksum')==advisory.checksum and a['metadata'].get('forecast_valid_time')]
        if assets:
            a=assets[-1];row=service.store.visual_asset(a['id'])
            if hashlib.sha256(row['body']).hexdigest()!=a['checksum']:raise ValueError('Forecast geometry checksum mismatch.')
            valid=datetime.fromisoformat(a['metadata']['forecast_valid_time'])
            forecast=broadcast.VisualSource(**{**source.model_dump(),'data_type':'forecast','forecast_valid_time':valid,'source_url':a['source_url'],'checksum':a['checksum']})
            geometry=json.loads(row['body']);p['geojson']={'features':[f for f in features if f['properties'].get('kind')!='forecast_cone']+[dict(f,properties={**f['properties'],'kind':'forecast_cone'}) for f in geometry['features']]}
            sources.append(forecast);layers=['forecast_cone'];p['map_valid_time']=valid.isoformat()
        else:
            fallback='Forecast geometry with matching issue and valid times is unavailable. Source wording only; no predicted path drawn.'
    elif mode=='radar':
        layers=[]
        pool=radar_assets if radar_assets is not None else service.store.visual_assets('radar')
        assets=sorted([a for a in pool if abs((datetime.fromisoformat(a['observed_at'])-advisory.issued_at).total_seconds())<=3600 and a['metadata'].get('projection')=='EPSG:3857'],key=lambda a:a['observed_at'])[-6:]
        if len(assets)>=2 and len({tuple(a['metadata']['extent']) for a in assets})==1 and advisory.provider!='TRAINING':
            p['radar_extent']=assets[0]['metadata']['extent'];p['bounds']=p['radar_extent']
            for a in assets:
                row=service.store.visual_asset(a['id'])
                if hashlib.sha256(row['body']).hexdigest()!=a['checksum']:raise ValueError('Radar checksum mismatch.')
                with Image.open(io.BytesIO(row['body'])) as im:im.verify()
                path=service.root/'observations'/(a['checksum']+'.image');path.write_bytes(row['body'])
                p['map_observations'].append({**a,'filename':path.name})
                asset_ids.append(a['id'])
                sources.append(broadcast.VisualSource(**{**source.model_dump(),'data_type':'radar_reflectivity','source_url':a['source_url'],'checksum':a['checksum'],'observation_start':datetime.fromisoformat(a['observed_at']),'observation_end':datetime.fromisoformat(a['observed_at']),'projection':'EPSG:3857','coverage':'Regional NOAA radar context; event attribution unverified','attribution':'NOAA nowCOAST'}))
            legend_id=assets[-1]['metadata'].get('legend_asset_id')
            if legend_id:
                row=service.store.visual_asset(legend_id)
                if hashlib.sha256(row['body']).hexdigest()!=row['checksum']:raise ValueError('Radar legend checksum mismatch.')
                path=service.root/'observations'/(row['checksum']+'.image');path.write_bytes(row['body'])
                p['map_legend']={'id':legend_id,'filename':path.name,'checksum':row['checksum']}
            layers=['radar']
        else:
            fallback='No matching timestamped radar sequence. Rainfall and future precipitation are not estimated.'
    direction=broadcast.SceneDirection(scene_type='radar_animation' if mode=='radar' else 'region_focus' if mode in ('warnings','forecast') else 'storm_track',event_id=advisory.event_key,duration=scene['seconds'],headline=MODES[mode],layers=layers,sources=sources,asset_ids=asset_ids,fallback=fallback,camera=broadcast.Camera(movement='smooth_zoom_in',end_zoom=1.08))
    p['fallback_label']=fallback or '';p['map_has_layer']=not bool(fallback)
    p['credit']=advisory.provider+' · issue '+advisory.issued_at.isoformat()+' · Natural Earth'
    return direction.model_dump(mode='json')
