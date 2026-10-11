"""Build bundled county names and outlines from the official Census archive.

Download https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_20m.zip to .local/regions/
first. Counties are keyed by NWS UGC county code (state abbreviation + 'C' + county FIPS), the code
NWS alerts use, so an alert's counties can be drawn without a network request.
"""
import hashlib,io,json,struct,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.forecast_archive import shp


def dbf(raw):
    """Attribute table; the archive's .cpg declares UTF-8 (names such as Doña Ana)."""
    count,header,size=struct.unpack_from('<IHH',raw,4);fields=[];offset=32
    while offset+32<=header and raw[offset]!=13:
        fields.append((raw[offset:offset+11].split(b'\0')[0].decode('ascii'),raw[offset+16]));offset+=32
    rows=[]
    for i in range(count):
        record=raw[header+i*size:header+(i+1)*size];pos=1;row={}
        for name,length in fields:row[name]=record[pos:pos+length].decode('utf-8').strip();pos+=length
        rows.append(row)
    return rows


NAME='cb_2024_us_county_20m'
raw=(ROOT/f'.local/regions/{NAME}.zip').read_bytes()
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    rows=dbf(z.read(NAME+'.dbf'));shapes=shp(z.read(NAME+'.shp'))
    projection=z.read(NAME+'.prj').decode()
    assert z.read(NAME+'.cpg').decode().strip()=='UTF-8'
    assert 'GCS_North_American_1983' in projection
counties={}
for row,g in zip(rows,shapes):
    rings=[[[round(x,4),round(y,4)] for x,y in ring] for ring in g['coordinates']]
    coords=[c for ring in rings for c in ring]
    counties[row['STUSPS']+'C'+row['COUNTYFP']]={'fips':row['GEOID'],'name':row['NAME'],'label':row['NAMELSAD'],'state':row['STUSPS'],'rings':rings,
        'bounds':[min(c[0] for c in coords),min(c[1] for c in coords),max(c[0] for c in coords),max(c[1] for c in coords)]}
result={'source_url':f'https://www2.census.gov/geo/tiger/GENZ2024/shp/{NAME}.zip',
        'source_checksum':hashlib.sha256(raw).hexdigest(),'year':2024,'projection':projection,
        'note':'Simplified NAD83 county boundaries (1:20,000,000) keyed by NWS UGC county code, for presentation; not warning polygons.',
        'counties':dict(sorted(counties.items()))}
(ROOT/'backend/app/data/us-counties.json').write_text(json.dumps(result,separators=(',',':')))
print(len(counties),'source-pinned counties')
