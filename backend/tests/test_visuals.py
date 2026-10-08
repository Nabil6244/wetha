"""Visual evidence tests; all image/geometry transport edge cases are synthetic."""
import asyncio,csv,hashlib,io,json,struct,zipfile,zlib
from datetime import datetime,timedelta,timezone
from pathlib import Path
import httpx,pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.visuals import GOES_PAGE,GOES_BASE,RADAR_BASE,VisualEvidence,goes_catalogue,valid_geometry,source_url,radar_catalogue,radar_url,forecast_geometry,image_size
from app.collector import parse_nhc_feed
from app.fixtures import training_advisories

FIXTURES=Path(__file__).parent/'fixtures'


def png():
    # A synthetic 1x1 pixel tests media transport, never production observation data.
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')


def synthetic_current(client):
    item=training_advisories()[0].model_copy(update={'id':'synthetic-visual-current','provider':'NHC','event_key':'AL012026','provenance':'official_fetch','issued_at':datetime.now(timezone.utc)-timedelta(minutes=5)})
    client.app.state.store.save_advisory(item);return item


def test_real_country_geometry_and_captured_goes_catalogue():
    root=Path(__file__).parents[1]/'app/data'
    provenance=json.loads((root/'provenance.json').read_text())
    assert hashlib.sha256((root/'countries.geojson').read_bytes()).hexdigest()==provenance['bundled_sha256']
    assert len(json.loads((root/'countries.geojson').read_text())['features'])==177
    frames=goes_catalogue((FIXTURES/'goes19-gulf-atlantic-2026-10-08.html').read_text())
    assert len(frames)==12
    assert frames[0]['observed_at']=='2026-10-08T02:31:00+00:00'
    assert frames[-1]['observed_at']=='2026-10-08T03:26:00+00:00'
    assert all(frame['url'].startswith(GOES_BASE) for frame in frames)


@pytest.mark.parametrize('url',['https://evil.test/image.jpg','https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/ga/GEOCOLOR/latest.jpg','http://nowcoast.noaa.gov/x','https://user@www.nhc.noaa.gov/gis/forecast/archive/al142024_5day_013.kmz',RADAR_BASE+'?service=WMS&request=GetMap&url=http://localhost'])
def test_visual_source_allowlist(url):
    with pytest.raises(ValueError):source_url(url)


@pytest.mark.parametrize('coordinates',[[[[0,0],[1,0],[1,1]]],[[[0,0],[1,0],[181,1],[0,0]]],[[[0,0],[1,0],[1,float('nan')],[0,0]]]])
def test_geometry_does_not_accept_unclosed_or_non_geographic_polygons(coordinates):
    with pytest.raises(ValueError):valid_geometry({'type':'Polygon','coordinates':coordinates})


def test_reported_track_and_alert_polygons_keep_original_evidence(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        items=[]
        for file in ['nhc-atlantic-2026-10-08.xml','nhc-atlantic-2026-10-08-0300.xml']:
            parsed,_=parse_nhc_feed((FIXTURES/file).read_text());items+=parsed
            client.app.state.store.save_advisory(parsed[0])
        state=client.get('/api/visuals/geography/'+items[-1].id).json()
        assert len(state['timeline'])==2
        assert state['timeline'][-1]['coordinates']==[-91.9,22.9]
        assert len([f for f in state['geojson']['features'] if f['properties']['kind']=='reported_track'])==1
        assert not any(f['properties']['kind']=='forecast_cone' for f in state['geojson']['features'])
        prior=client.get('/api/visuals/geography/'+items[0].id).json()
        assert len(prior['timeline'])==1 # Never show later centers as known in an earlier advisory.
        client.post('/api/training/load')
        assert client.get('/api/visuals/geography/training:cyclone:2').json()['geojson']['features']==[]
        synthetic=synthetic_current(client).model_copy(update={'id':'synthetic-nws','provider':'NWS','source_payload':{'geometry':{'type':'Polygon','coordinates':[[[-90,30],[-89,30],[-89,31],[-90,30]]]}}})
        client.app.state.store.save_advisory(synthetic)
        geometry=client.get('/api/visuals/geography/synthetic-nws').json()['geojson']['features'][0]['geometry']
        assert geometry==synthetic.source_payload['geometry']


def test_goes_cache_timestamp_checksum_failure_and_restart(tmp_path):
    html=(FIXTURES/'goes19-gulf-atlantic-2026-10-08.html').read_text()
    calls=[]
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200,text=html) if str(request.url)==GOES_PAGE else httpx.Response(200,content=png(),headers={'content-type':'image/png'})
    with TestClient(create_app(tmp_path,visual_transport=httpx.MockTransport(response))) as client:
        assert client.post('/api/visuals/sources/goes/refresh').json()['collected']==12
        first=client.get('/api/visuals').json()['assets'][0]
        assert client.get('/api/visuals/assets/'+first['id']).content==png()
        assert first['checksum']==hashlib.sha256(png()).hexdigest()
        calls.clear();client.post('/api/visuals/sources/goes/refresh')
        assert calls==[GOES_PAGE] # Immutable dated frames are read from the verified local cache.
    with TestClient(create_app(tmp_path,visual_transport=httpx.MockTransport(lambda request:httpx.Response(403)))) as client:
        assert len(client.get('/api/visuals').json()['assets'])==12
        assert client.post('/api/visuals/sources/goes/refresh').status_code==422
        assert len(client.get('/api/visuals').json()['assets'])==12
        assert next(s for s in client.get('/api/visuals').json()['sources'] if s['id']=='goes')['status']=='failed'
        with client.app.state.store.connection() as conn:conn.execute('UPDATE visual_assets SET body=? WHERE id=?',(b'corrupt',first['id']))
        assert client.get('/api/visuals/assets/'+first['id']).status_code==422


def test_radar_uses_explicit_source_times_projection_and_legend(tmp_path):
    end=datetime.now(timezone.utc)-timedelta(minutes=5);start=end-timedelta(minutes=25)
    caps=f'<WMS_Capabilities><Capability><Layer><Name>conus_reflectivity_mosaic</Name><Dimension name="time">{start.isoformat()}/{end.isoformat()}/PT5M</Dimension></Layer></Capability></WMS_Capabilities>'.encode()
    layer,times=radar_catalogue(caps)
    assert len(times)==6 and times[-1]==end.isoformat()
    url=radar_url(layer,times[-1]);assert 'EPSG%3A3857' in url and 'time=' in url
    from urllib.parse import parse_qs,urlsplit
    assert parse_qs(urlsplit(url).query)['time'][0].endswith('Z')
    def response(request):
        if request.url.params.get('request')=='GetCapabilities':return httpx.Response(200,content=caps)
        return httpx.Response(200,content=png(),headers={'content-type':'image/png'})
    with TestClient(create_app(tmp_path,visual_transport=httpx.MockTransport(response))) as client:
        assert client.post('/api/visuals/sources/radar/refresh').json()['collected']==6
        assets=client.get('/api/visuals').json()['assets'];radar=[a for a in assets if a['kind']=='radar']
        assert len(radar)==6 and radar[0]['metadata']['projection']=='EPSG:3857'
        assert radar[0]['metadata']['legend_asset_id'] in {a['id'] for a in assets}
    with pytest.raises(ValueError):radar_catalogue(b'<Layer><Name>reflectivity</Name></Layer>')
    with pytest.raises(ValueError):radar_catalogue(b'<!DOCTYPE test [<!ENTITY x SYSTEM "file:///etc/passwd">]><Layer/>')


def kmz(stamp,network=False):
    xml=f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><TimeStamp><when>{stamp}</when></TimeStamp>{"<NetworkLink/>" if network else ""}<Placemark><name>Official forecast cone</name><Polygon><outerBoundaryIs><LinearRing><coordinates>-91,24 -90,24 -90,25 -91,24</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>'
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:z.writestr('cone.kml',xml)
    return stream.getvalue()


def test_forecast_cone_is_inline_timestamped_and_tied_to_advisory(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        item=synthetic_current(client)
        assert forecast_geometry(kmz(item.issued_at.isoformat()),item)['features'][0]['properties']['data_class']=='forecast'
        with pytest.raises(ValueError):forecast_geometry(kmz((item.issued_at-timedelta(days=1)).isoformat()),item)
        with pytest.raises(ValueError):forecast_geometry(kmz(item.issued_at.isoformat(),True),item)
        with pytest.raises(ValueError):forecast_geometry(b'not a zip',item)
    with TestClient(create_app(tmp_path,visual_transport=httpx.MockTransport(lambda request:httpx.Response(200,content=kmz(item.issued_at.isoformat()))))) as client:
        assert client.post('/api/visuals/forecast-cone',json={'advisory_id':item.id}).json()['collected']==1
        state=client.get('/api/visuals/geography/'+item.id).json()
        assert any(f['properties']['kind']=='forecast_cone' for f in state['geojson']['features'])


def test_visual_plan_revision_csv_roundtrip_and_unsupported_replacement(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/training/load');script=client.post('/api/scripts',json={'advisory_id':'training:cyclone:2'}).json()
        result=client.post('/api/visuals/plans',json={'script_id':script['id'],'expected_revision':1,'style':'satellite'})
        assert result.status_code==200;plan=result.json()
        assert plan['script_revision']==1 and plan['broadcast_eligible'] is False and plan['rendered'] is False
        assert 'satellite_timelapse' not in {s['type'] for s in plan['scenes']}
        assert plan['scenes'][1]['parameters']['unavailable_requested_layer']=='satellite'
        path='/api/visuals/plans/'+plan['id']
        csv_text=client.get(path+'/scenes.csv').text
        rows=list(csv.DictReader(io.StringIO(csv_text)));rows[0]['transition']='cut'
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        imported=client.post(path+'/import',json={'csv_text':stream.getvalue()})
        assert imported.status_code==200 and imported.json()['scenes'][0]['transition']=='cut'
        rows[0]['parameters']='{"fake_forecast":"tomorrow"}'
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        assert client.post(path+'/import',json={'csv_text':stream.getvalue()}).status_code==422
        client.post('/api/scripts/'+script['id']+'/revisions',json={'expected_revision':1,'editor':'Test editor','note':'Changed text','text':script['text']+'\n\nA synthetic test addition.'})
        assert client.get(path).json()['superseded_script_revision'] is True
        assert client.post('/api/visuals/plans',json={'script_id':script['id'],'expected_revision':1}).status_code==409
    with TestClient(create_app(tmp_path)) as client:
        assert len(client.get('/api/visuals').json()['plans'])==2
