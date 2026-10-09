"""Point forecasts and current-source checks for timed forecast-news snapshots."""
import json,math,re
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit

CITIES=[
 {'id':'pensacola','name':'Pensacola','coordinates':[-87.2169,30.4213]},
 {'id':'panama-city','name':'Panama City','coordinates':[-85.6602,30.1588]},
 {'id':'tallahassee','name':'Tallahassee','coordinates':[-84.2807,30.4383]},
 {'id':'jacksonville','name':'Jacksonville','coordinates':[-81.6557,30.3322]},
 {'id':'orlando','name':'Orlando','coordinates':[-81.3792,28.5383]},
 {'id':'tampa','name':'Tampa','coordinates':[-82.4572,27.9506]},
 {'id':'west-palm','name':'West Palm Beach','coordinates':[-80.0534,26.7153]},
 {'id':'miami','name':'Miami','coordinates':[-80.1918,25.7617]}]
HORIZONS=[0,6,12,24,48,72]


def stamp(value):
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Forecast timestamp needs an explicit timezone.')
    return d.astimezone(timezone.utc)


def official_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname!='api.weather.gov' or u.port is not None or u.username or u.password or u.fragment:
        raise ValueError('Forecast data must come from the official NWS HTTPS API.')
    if not re.fullmatch(r'/points/-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?|/gridpoints/[A-Z]{3}/\d+,\d+/forecast/hourly|/alerts(?:/active)?',u.path):
        raise ValueError('Unsupported NWS forecast URL.')
    if u.query and (u.path not in ['/alerts','/alerts/active'] or not re.fullmatch(r'(area=FL|active=true)(?:&[^#]*)?',u.query)):
        raise ValueError('Unsupported forecast query.')
    return url


def wind_range(value):
    m=re.fullmatch(r'(\d+)(?: to (\d+))? mph',str(value))
    if not m:raise ValueError('Unsupported wind unit or speed format.')
    low=int(m[1]);high=int(m[2] or m[1])
    if not 0<=low<=high<=250:raise ValueError('Invalid forecast wind range.')
    return [low,high]


def parse_hourly(raw,city,url,now):
    official_url(url)
    payload=json.loads(raw);p=payload['properties'];issued=stamp(p['updateTime'])
    age=(now-issued).total_seconds()
    if not -300<=age<=86400:raise ValueError('NWS forecast is future-dated or older than 24 hours.')
    if p.get('forecastGenerator')!='HourlyForecastGenerator' or p.get('units')!='us':raise ValueError('Expected an official hourly US-unit forecast.')
    periods=[];last=None
    for source in p['periods']:
        start,end=stamp(source['startTime']),stamp(source['endTime'])
        if end-start!=timedelta(hours=1) or (last and start<last):raise ValueError('Forecast periods overlap or are not hourly.')
        last=end
        temp=source['temperature'];pop=source.get('probabilityOfPrecipitation',{})
        if source['temperatureUnit']!='F' or not isinstance(temp,(int,float)) or not math.isfinite(temp) or not -100<=temp<=160:
            raise ValueError('Invalid hourly temperature or unit.')
        chance=pop.get('value')
        if chance is not None and (pop.get('unitCode')!='wmoUnit:percent' or not isinstance(chance,(int,float)) or not math.isfinite(chance) or not 0<=chance<=100):
            raise ValueError('Invalid precipitation probability or unit.')
        periods.append({'start':start.isoformat(),'end':end.isoformat(),'temperature_f':temp,'rain_probability':chance,
          'wind_mph':wind_range(source['windSpeed']),'wind_direction':source['windDirection'],'short_forecast':source['shortForecast']})
    if not any(stamp(x['start'])<=now<stamp(x['end']) for x in periods):raise ValueError('Hourly forecast does not cover the current hour.')
    return {**city,'issued_at':issued.isoformat(),'source_url':url,'periods':periods,'coverage':'one forecast grid point; not a citywide uniform field'}


def at(city,time):
    matches=[p for p in city['periods'] if stamp(p['start'])<=time<stamp(p['end'])]
    if len(matches)!=1:raise ValueError('No unique source forecast period at the requested time.')
    return matches[0]


def snapshots(cities,now):
    anchor=now.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1)
    return [{'hours':h,'valid_at':(anchor+timedelta(hours=h)).isoformat(),
             'points':[{**{k:v for k,v in c.items() if k!='periods'},'forecast':at(c,anchor+timedelta(hours=h))} for c in cities]} for h in HORIZONS]


def active_alerts(payload,now):
    if payload.get('type')!='FeatureCollection' or payload.get('pagination',{}).get('next'):raise ValueError('Alert snapshot is incomplete.')
    valid=[]
    for a in payload['features']:
        p=a['properties']
        if p.get('status')!='Actual' or p.get('messageType') in ['Cancel','Ack','Error']:continue
        sent,expires=stamp(p['sent']),stamp(p['expires'])
        effective=stamp(p.get('effective') or p['sent'])
        if sent>now+timedelta(minutes=5):raise ValueError('Alert issue time is in the future.')
        if effective>now or expires<=now:continue
        if not any(str(code).startswith('FL') for code in p.get('geocode',{}).get('UGC',[])):continue
        valid.append({'id':a.get('id') or p['id'],'event':p['event'],'sent':sent.isoformat(),'expires':expires.isoformat(),
            'area':p['areaDesc'],'headline':p.get('headline'),'severity':p['severity'],'geometry':a.get('geometry'),
            'affected_zones':p.get('affectedZones',[]),'instruction':p.get('instruction'),'description':p['description'],
            'source_url':p.get('@id') or a.get('id')})
    return valid


def snapshot_status(manifest,now):
    collected=stamp(manifest['collected_at']);refresh=stamp(manifest['refresh_after'])
    return {'available':True,'title':manifest['title'],'seconds':manifest.get('output',{}).get('seconds'),
            'visual_revision':manifest.get('visual_revision',1),'visual_audit':manifest.get('visual_audit'),
            'collected_at':collected.isoformat(),'refresh_after':refresh.isoformat(),
            'status':'refresh_needed' if now>=refresh else 'recent_snapshot',
            'note':'Recorded forecast bulletin. Recollect sources before publishing; this video does not update automatically.'}
