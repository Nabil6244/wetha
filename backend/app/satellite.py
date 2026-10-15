"""Dated STAR GeoColor frames at the story time, including inland CONUS stories.

Native satellite pixels are contextual imagery, never treated as a geographic tile or precipitation.
"""
import re
from datetime import datetime, timezone
from .visuals import GOES_BASE, GOES_CONUS, image_size

SECTORS = {'ga': (GOES_BASE, [-100,15,-70,34], 'ga', '1000x1000', 'Gulf/Atlantic'),
           'conus': (GOES_CONUS, [-125,24,-66,50], 'CONUS', '2500x1500', 'CONUS')}
WINDOW = 5400


def contains(extent, region):
    return extent[0] <= region[0] and extent[1] <= region[1] and extent[2] >= region[2] and extent[3] >= region[3]


def matching(assets, moment, region):
    return [a for a in assets if contains(a['metadata'].get('extent', SECTORS['ga'][1]), region)
            and -WINDOW <= (datetime.fromisoformat(a['observed_at']) - moment).total_seconds() <= 300]


def catalogue(html, moment, sector):
    base, _, name, size, _ = SECTORS[sector]
    files = set(re.findall(r'\d{11}_GOES19-ABI-' + name + '-GEOCOLOR-' + size + r'\.jpg', html))
    frames = []
    for filename in sorted(files):
        stamp = datetime.strptime(filename[:11], '%Y%j%H%M').replace(tzinfo=timezone.utc)
        if stamp.strftime('%Y%j%H%M') == filename[:11] and -WINDOW <= (stamp-moment).total_seconds() <= 300:
            frames.append({'url':base+filename,'observed_at':stamp.isoformat()})
    return frames[-6:]


async def collect(service, moment, region):
    sector = next((key for key, (_,extent,*_) in SECTORS.items() if contains(extent, region)), None)
    if sector is None:
        raise ValueError('No configured satellite sector covers this story region.')
    base, extent, _, _, title = SECTORS[sector]
    assets = service.store.visual_assets('goes')
    cached = [a for a in matching(assets, moment, region) if a['metadata'].get('sector', 'ga') == sector]
    if len(cached) >= 2:
        return [a['id'] for a in cached[:6]]
    index = service.store.cache(base)
    if index and (datetime.now(timezone.utc)-datetime.fromisoformat(index['checked_at'])).total_seconds() < 300:
        html = index['body']
    else:
        body, _ = await service.fetch(base)
        html = body.decode()
        service.store.cache_response(base, html, None, None)
    frames = catalogue(html, moment, sector)
    if len(frames) < 2:
        raise ValueError(f'No dated {title} satellite loop is available near {moment:%d %b %Y %H:%M UTC}.')
    existing = {a['source_url']:a for a in assets};ids = []
    for frame in frames:
        if frame['url'] in existing:
            ids.append(existing[frame['url']]['id']);continue
        body, mime = await service.fetch(frame['url'])
        width, height = image_size(body, mime)
        ids.append(service.store.save_visual_asset({'kind':'goes','source_url':frame['url'],
            'observed_at':frame['observed_at'],'content_type':mime,'metadata':{
                'width':width,'height':height,'sector':sector,'extent':extent,
                'product':f'GOES-19 GeoColor · {title}','data_class':'observation_composite',
                'projection':'Native NOAA image; contextual viewport, not a geographic map overlay',
                'catalogue_url':base,'attribution':'CIRA / NOAA / NESDIS / STAR',
                'note':'Observation times are independent of the advisory. GeoColor is not rainfall; nighttime colors include infrared enhancement.'}}, body))
    return ids
