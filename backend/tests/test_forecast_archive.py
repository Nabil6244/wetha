"""Real NHC archive regression: event, issue time, future points and warnings."""
import hashlib
import struct
from datetime import timedelta
from pathlib import Path
import pytest
from app.forecast_archive import parse, shp
from app.weather import parse_nhc

FIXTURES=Path(__file__).parent/'fixtures'


def advisory():
    return parse_nhc((FIXTURES/'al092020-public-028.html').read_text(),
        'https://www.nhc.noaa.gov/archive/2020/al09/al092020.public.028.shtml','official_fetch')


def test_real_cone_archive_retains_forecast_times_and_warning_lines():
    raw=(FIXTURES/'al092020-forecast-028.zip').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f58aa5c2c2cd5adbc6e3ed15ac906e2be048bbd0ee64f9bdcb863d311cfdb440'
    a=advisory();g=parse(raw,a)
    assert g['issued_at']=='2020-08-04T03:00:00+00:00'
    assert g['valid_until']=='2020-08-06T12:00:00+00:00'
    points=[f for f in g['features'] if f['properties']['kind']=='forecast_point']
    assert len(points)==5
    assert points[0]['geometry']['coordinates']==[-76.8,37.0]
    assert points[0]['properties']['valid_time']=='2020-08-04T12:00:00+00:00'
    assert all(f['properties']['valid_time']>g['issued_at'] for f in points)
    warnings=[f for f in g['features'] if f['properties']['kind']=='warning_coast']
    assert len(warnings)==21
    assert {f['properties']['TCWW'] for f in warnings}=={'HWR','TWR','TWA'}
    assert all(f['geometry']['type']=='MultiLineString' for f in warnings)
    assert len([f for f in g['features'] if f['properties']['kind']=='forecast_cone'])==1


def test_archive_cannot_be_bound_to_a_different_issue():
    a=advisory().model_copy(update={'issued_at':advisory().issued_at+timedelta(hours=6)})
    with pytest.raises(ValueError,match='issue time'):
        parse((FIXTURES/'al092020-forecast-028.zip').read_bytes(),a)


def test_negative_shapefile_record_length_is_rejected():
    raw=bytearray(108)
    struct.pack_into('>i',raw,0,9994);struct.pack_into('>i',raw,24,54)
    struct.pack_into('>ii',raw,100,1,-1)
    with pytest.raises(ValueError,match='record length'):shp(raw)
