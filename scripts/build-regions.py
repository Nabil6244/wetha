"""Build bundled state names and outlines from the official Census archive."""
import hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.forecast_archive import dbf,shp
raw=(ROOT/'.local/regions/cb_2024_us_state_20m.zip').read_bytes()
with zipfile.ZipFile(__import__('io').BytesIO(raw)) as z:
    rows=dbf(z.read('cb_2024_us_state_20m.dbf'));shapes=shp(z.read('cb_2024_us_state_20m.shp'))
    projection=z.read('cb_2024_us_state_20m.prj').decode()
    assert 'GCS_North_American_1983' in projection
states=[]
for row,g in zip(rows,shapes):
    coords=[c for ring in g['coordinates'] for c in ring]
    states.append({'code':row['STUSPS'],'name':row['NAME'],'rings':g['coordinates'],
                   'bounds':[min(c[0] for c in coords),min(c[1] for c in coords),max(c[0] for c in coords),max(c[1] for c in coords)]})
result={'source_url':'https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_20m.zip',
        'source_checksum':hashlib.sha256(raw).hexdigest(),'year':2024,'projection':projection,
        'note':'Simplified NAD83 state boundaries for presentation and regional coverage checks; not warning polygons.',
        'regions':sorted(states,key=lambda r:r['name'])}
(ROOT/'backend/app/data/us-regions.json').write_text(json.dumps(result,separators=(',',':')))
print(len(states),'source-pinned regions')
