"""Synthetic, fixed-clock tests for forecast timing, units and stale snapshot rejection."""
import copy,json
from datetime import datetime,timedelta,timezone
import pytest
from app.forecast_news import parse_hourly,at,snapshots,wind_range,official_url,active_alerts,snapshot_status
from app.forecast_archive import local_stamp
NOW=datetime(2026,1,1,10,25,tzinfo=timezone.utc)
CITY={'id':'test','name':'Training Florida point','coordinates':[-80,26]}
URL='https://api.weather.gov/gridpoints/MFL/110,50/forecast/hourly'

def payload():
 periods=[]
 for h in range(80):
  a=NOW.replace(minute=0)+timedelta(hours=h)
  periods.append({'startTime':a.isoformat(),'endTime':(a+timedelta(hours=1)).isoformat(),'temperature':80,'temperatureUnit':'F',
   'probabilityOfPrecipitation':{'unitCode':'wmoUnit:percent','value':None if h==0 else 0},'windSpeed':'10 to 15 mph','windDirection':'NE','shortForecast':'Synthetic training forecast'})
 return {'properties':{'updateTime':NOW.isoformat(),'forecastGenerator':'HourlyForecastGenerator','units':'us','periods':periods}}


def test_exact_source_hours_and_null_probability_survive():
 c=parse_hourly(json.dumps(payload()),CITY,URL,NOW)
 assert at(c,NOW)['rain_probability'] is None
 s=snapshots([c],NOW)
 assert [x['hours'] for x in s]==[0,6,12,24,48,72]
 assert s[1]['valid_at']=='2026-01-01T17:00:00+00:00'
 assert s[1]['points'][0]['forecast']['start']==s[1]['valid_at']
 assert s[1]['points'][0]['forecast']['rain_probability']==0
 assert s[1]['points'][0]['forecast']['wind_mph']==[10,15]

@pytest.mark.parametrize('kind',['stale','future','windunit','rainunit','temperatureunit','overlap'])
def test_unusable_source_periods_are_rejected(kind):
 p=payload();r=p['properties'];x=r['periods'][0]
 if kind=='stale':r['updateTime']=(NOW-timedelta(hours=25)).isoformat()
 if kind=='future':r['updateTime']=(NOW+timedelta(hours=1)).isoformat()
 if kind=='windunit':x['windSpeed']='10 km/h'
 if kind=='rainunit':x['probabilityOfPrecipitation']={'unitCode':'wmoUnit:in','value':40}
 if kind=='temperatureunit':x['temperatureUnit']='C'
 if kind=='overlap':r['periods'][1]['startTime']=x['startTime']
 with pytest.raises(ValueError):parse_hourly(json.dumps(p),CITY,URL,NOW)


def test_wrong_host_and_unknown_period_cannot_enter_news():
 with pytest.raises(ValueError):official_url('https://evil.example/gridpoints/MFL/1,1/forecast/hourly')
 with pytest.raises(ValueError):official_url('https://api.weather.gov@evil.example/alerts')
 c=parse_hourly(json.dumps(payload()),CITY,URL,NOW)
 with pytest.raises(ValueError):at(c,NOW+timedelta(days=10))


def test_incomplete_or_expired_alerts_are_not_called_active():
 a={'type':'FeatureCollection','features':[{'id':'test','geometry':None,'properties':{'status':'Actual','messageType':'Alert','sent':NOW.isoformat(),
 'effective':NOW.isoformat(),'expires':(NOW-timedelta(minutes=1)).isoformat(),'geocode':{'UGC':['FLZ001']}}}]}
 assert active_alerts(a,NOW)==[]
 a['pagination']={'next':'https://api.weather.gov/alerts?cursor=next'}
 with pytest.raises(ValueError):active_alerts(a,NOW)


def test_refresh_status_changes_without_changing_recorded_video():
 m={'title':'Training bulletin','collected_at':NOW.isoformat(),'refresh_after':(NOW+timedelta(minutes=30)).isoformat()}
 assert snapshot_status(m,NOW)['status']=='recent_snapshot'
 assert snapshot_status(m,NOW+timedelta(minutes=31))['status']=='refresh_needed'


def test_nhc_printed_central_time_is_not_treated_as_eastern():
 assert local_stamp('1000 PM CDT Thu Oct 08 2026','%I%M %p %a %b %d %Y').astimezone(timezone.utc).isoformat()=='2026-10-09T03:00:00+00:00'
 assert local_stamp('2026-10-09 7:00 AM Fri CDT','%Y-%m-%d %I:%M %p %a').astimezone(timezone.utc).hour==12
 with pytest.raises(ValueError):local_stamp('1000 PM Thu Oct 08 2026','%I%M %p %a %b %d %Y')
