#!/usr/bin/env python3
"""Collect a bounded fresh official-source snapshot, never silently reuse old bytes."""
import asyncio,hashlib,json,shutil,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import httpx
from app.forecast_news import CITIES,official_url,parse_hourly,snapshots,active_alerts
from app.collector import parse_nhc_feed
from app.forecast_archive import parse
from app.weather import parse_nhc
OUT=ROOT/'.local/forecast-news/sources'

async def run():
 OUT.mkdir(parents=True,exist_ok=True);sources=[];now=datetime.now(timezone.utc)
 async with httpx.AsyncClient(timeout=40,follow_redirects=False,headers={'User-Agent':'WeatherIntelligenceStudio/0.5 (local editorial forecast preview)'}) as client:
  async def fetch(url,name,nws=True):
   if nws:official_url(url)
   raw=None
   for attempt in range(3):
    try:
     response=await client.get(url);response.raise_for_status();raw=response.content
     if len(raw)>8*1024*1024:raise ValueError('Source exceeds collection limit.')
     break
    except (httpx.TimeoutException,httpx.HTTPStatusError):
     if attempt==2:raise
     await asyncio.sleep(1)
   (OUT/name).write_bytes(raw);sources.append({'url':url,'filename':name,'checksum':hashlib.sha256(raw).hexdigest(),'retrieved_at':datetime.now(timezone.utc).isoformat()})
   return raw
  cities=[]
  for city in CITIES:
   lon,lat=city['coordinates'];meta=json.loads(await fetch(f'https://api.weather.gov/points/{lat},{lon}',city['id']+'-point.json'))
   if meta['properties']['relativeLocation']['properties']['state']!='FL':raise ValueError('Point lookup returned an unrelated state.')
   url=meta['properties']['forecastHourly'];raw=await fetch(url,city['id']+'-hourly.json')
   cities.append(parse_hourly(raw,city,url,datetime.now(timezone.utc)));print(city['name'],'collected',flush=True)
  alerts_raw=await fetch('https://api.weather.gov/alerts/active?area=FL','florida-alerts.json')
  nhc_raw=await fetch('https://www.nhc.noaa.gov/index-at.xml','nhc-atlantic.xml',False)
  advisories,rejected=parse_nhc_feed(nhc_raw.decode());nhc=[]
  for a in advisories:
   if (now-a.issued_at).total_seconds()>6*3600 or a.issued_at>now+timedelta(minutes=5):raise ValueError('NHC bulletin is not current.')
   number=int(''.join(c for c in str(a.facts['advisory_number']) if c.isdigit()));event=a.event_key.lower()
   url=f'https://www.nhc.noaa.gov/archive/{event[-4:]}/{event[:4]}/{event}.public.{number:03}.shtml'
   full=parse_nhc((await fetch(url,event+'-public.html',False)).decode(),url,'official_fetch')
   if full.event_key!=a.event_key or full.issued_at>a.issued_at or (a.issued_at-full.issued_at).total_seconds()>3*3600:raise ValueError('Full advisory does not match latest intermediate bulletin.')
   geo_url=f'https://www.nhc.noaa.gov/gis/forecast/archive/{event}_5day_{number:03}.zip'
   geo=parse(await fetch(geo_url,event+'-forecast.zip',False),full)
   nhc.append({'latest':a.model_dump(mode='json'),'full':full.model_dump(mode='json'),'geometry':geo,'geometry_url':geo_url})
  if rejected:raise ValueError('NHC feed contains unparsed public bulletins; cannot call the news snapshot complete.')
 now=datetime.now(timezone.utc);active=active_alerts(json.loads(alerts_raw),now)
 # Next-hour anchor makes all cities share exact valid times.
 p={'title':'Florida / What happens next?','collected_at':now.isoformat(),'refresh_after':(now+timedelta(minutes=30)).isoformat(),
    'region_codes':['FL'],'historical':False,'sources':sources,'cities':cities,'snapshots':snapshots(cities,now),'alerts':active,'nhc':nhc,
    'limitations':['Selected city grid points do not cover every Florida location.','Point rain probabilities are not rainfall amounts or a spatial rain field.',
      'NHC center winds and city forecast winds describe different things.','Recorded snapshot; future source changes do not update the video automatically.']}
 archive=OUT/'snapshots'/now.strftime('%Y%m%dT%H%M%S%fZ');archive.mkdir(parents=True,exist_ok=False)
 for source in sources:
  shutil.copy2(OUT/source['filename'],archive/source['filename'])
  source['archived_file']=str((archive/source['filename']).relative_to(OUT))
 (archive/'snapshot.json').write_text(json.dumps(p,indent=2))
 (OUT/'snapshot.json').write_text(json.dumps(p,indent=2));print('Snapshot complete:',len(active),'active Florida alerts;',len(nhc),'NHC storms',flush=True)

if __name__=='__main__':asyncio.run(run())
