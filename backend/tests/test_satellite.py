import asyncio
import io
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import httpx
from PIL import Image
import pytest
from app.satellite import catalogue, matching, collect, SECTORS
from app.storage import Store
from app.visuals import VisualEvidence,source_url,GOES_CONUS

MOMENT=datetime(2026,10,14,19,30,tzinfo=timezone.utc)
REGION=[-103,30,-102,31]


def filenames():
    return [f'{(MOMENT+timedelta(minutes=m)):%Y%j%H%M}_GOES19-ABI-CONUS-GEOCOLOR-2500x1500.jpg' for m in (-20,-15,-10,-5,0,10)]


def test_dated_catalogue_never_uses_future_frames_or_another_sector():
    frames=catalogue(' '.join(filenames()),MOMENT,'conus')
    assert len(frames)==5 and frames[-1]['observed_at']==MOMENT.isoformat()
    assert catalogue(' '.join(filenames()),MOMENT,'ga')==[]
    assert source_url(frames[0]['url'])==frames[0]['url']
    assert source_url(GOES_CONUS)==GOES_CONUS
    with pytest.raises(ValueError):source_url(GOES_CONUS+'latest.jpg')
    assets=[{'observed_at':MOMENT.isoformat(),'metadata':{'extent':SECTORS['ga'][1]}},
            {'observed_at':MOMENT.isoformat(),'metadata':{'extent':SECTORS['conus'][1]}},
            {'observed_at':(MOMENT+timedelta(minutes=10)).isoformat(),'metadata':{'extent':SECTORS['conus'][1]}}]
    assert matching(assets,MOMENT,REGION)==[assets[1]]


def test_conus_collection_is_cached_and_keeps_sector_metadata(tmp_path):
    out=io.BytesIO();Image.new('RGB',(400,240),'#183040').save(out,'JPEG');calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,content=' '.join(filenames()).encode() if str(request.url)==GOES_CONUS else out.getvalue(),headers={'content-type':'text/html' if str(request.url)==GOES_CONUS else 'image/jpeg'})
    store=Store(tmp_path/'db.sqlite3');store.initialize();service=VisualEvidence(store,httpx.MockTransport(handler))
    async def run():
        first=await collect(service,MOMENT,REGION);count=len(calls)
        second=await collect(service,MOMENT,REGION)
        assert len(first)==5 and set(first)==set(second) and len(calls)==count
        assets=store.visual_assets('goes')
        assert all(a['metadata']['sector']=='conus' for a in assets)
        assert not matching(assets,MOMENT,[-151,63,-150,64])
        await service.close()
    asyncio.run(run())
