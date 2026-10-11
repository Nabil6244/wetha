"""Archived NEXRAD radar for stories older than NOAA nowCOAST's few-hour window.

Source: the Iowa Environmental Mesonet (IEM) archive of NWS NEXRAD national base-reflectivity
composites, one PNG every 5 minutes with a world file giving its lat/lon grid. n0q (0.5 dBZ steps)
is used when it exists for the date, n0r (5 dBZ steps) for older dates. Each frame is cropped to the
story region, reprojected from EPSG:4326 to Web Mercator and saved as an ordinary 'radar' asset, so
the existing radar scene, director option and renderer use it unchanged. Source colours are kept;
only values below 5 dBZ are made transparent so the basemap shows where there is no echo.
"""
import asyncio
import hashlib
import io
import math
from datetime import datetime, timedelta, timezone
import httpx
from PIL import Image, ImageDraw

ARCHIVE = 'https://mesonet.agron.iastate.edu/archive/data/'
DOCS = 'https://mesonet.agron.iastate.edu/docs/nexrad_mosaic/'
ATTRIBUTION = 'NOAA/NWS NEXRAD composite · Iowa Environmental Mesonet archive'
# Palette index -> dBZ for each product (checked against the archive's own palettes).
PRODUCTS = {'n0q': lambda i: i / 2 - 32, 'n0r': lambda i: (i - 6) * 5}
MIN_DBZ = 5
WIDTH = 1600            # Output width in pixels; height follows the Mercator aspect of the extent.
STRIPS = 64             # Horizontal strips in the reprojection mesh; latitude is linear within each.
STEP = timedelta(minutes=10)


def frame_times(moment, frames=6):
    """Frame times up to the story time at 10-minute spacing, aligned to the archive's 5-minute grid."""
    moment = moment.astimezone(timezone.utc).replace(second=0, microsecond=0)
    last = moment - timedelta(minutes=moment.minute % 5)
    return [last - STEP * k for k in range(frames - 1, -1, -1)]


def frame_url(product, stamp, suffix='png'):
    return f"{ARCHIVE}{stamp:%Y/%m/%d}/GIS/uscomp/{product}_{stamp:%Y%m%d%H%M}.{suffix}"


def world_file(body):
    """Pixel size and upper-left pixel centre from an ESRI world file: (dx, dy, west, north)."""
    values = [float(v) for v in body.decode().split()]
    if len(values) != 6 or values[1] or values[2] or values[0] <= 0 or values[3] >= 0:
        raise ValueError('Radar world file is not a north-up lat/lon grid.')
    return values[0], values[3], values[4], values[5]


def _mercator_y(lat):
    lat = max(-85, min(85, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def reproject(body, wld, extent, product):
    """Crop a lat/lon composite to `extent` [W, S, E, N] and return a transparent Web Mercator PNG."""
    dx, dy, west0, north0 = world_file(wld)
    with Image.open(io.BytesIO(body)) as source:
        if source.mode != 'P':
            raise ValueError('Radar composite is not a palette image.')
        to_dbz = PRODUCTS[product]
        alpha = [0 if to_dbz(i) < MIN_DBZ else 255 for i in range(256)]
        w, s, e, n = extent
        # Source pixel columns/rows of the extent (world file gives pixel centres).
        x0, x1 = (w - west0) / dx + .5, (e - west0) / dx + .5
        y0, y1 = (n - north0) / dy + .5, (s - north0) / dy + .5
        if x0 < 0 or y0 < 0 or x1 > source.width or y1 > source.height:
            raise ValueError('Story region lies outside the radar composite.')
        box = (int(x0), int(y0), math.ceil(x1), math.ceil(y1))
        crop = source.crop(box)
        crop.load()
    left, top = x0 - box[0], y0 - box[1]
    ym = _mercator_y(n), _mercator_y(s)
    height = max(2, round(WIDTH * (ym[0] - ym[1]) / math.radians(e - w)))
    mesh = []
    for k in range(STRIPS):
        a, b = round(height * k / STRIPS), round(height * (k + 1) / STRIPS)
        lat_a = math.degrees(math.atan(math.sinh(ym[0] - (ym[0] - ym[1]) * a / height)))
        lat_b = math.degrees(math.atan(math.sinh(ym[0] - (ym[0] - ym[1]) * b / height)))
        ra, rb = top + (n - lat_a) / -dy, top + (n - lat_b) / -dy
        r0, r1 = left, left + (e - w) / dx
        mesh.append(((0, a, WIDTH, b), (r0, ra, r0, rb, r1, rb, r1, ra)))
    # Nearest-neighbour on palette indices: every output pixel is an unaltered source colour.
    image = crop.transform((WIDTH, height), Image.Transform.MESH, mesh, Image.Resampling.NEAREST)
    out = io.BytesIO();image.save(out, 'PNG', optimize=True, transparency=bytes(alpha))
    return out.getvalue()


def legend_png(product, palette):
    """Colour key drawn from the product's own palette at 5 dBZ intervals."""
    from .broadcast import font
    stops = list(range(MIN_DBZ, 75, 5));to_dbz = PRODUCTS[product]
    image = Image.new('RGB', (40 + 46 * len(stops), 92), '#061724');d = ImageDraw.Draw(image)
    d.text((20, 8), 'REFLECTIVITY (dBZ) · NEXRAD COMPOSITE', font=font(18), fill='#a8c4d0')
    for k, dbz in enumerate(stops):
        index = next(i for i in range(256) if to_dbz(i) >= dbz)
        x = 20 + 46 * k;d.rectangle((x, 38, x + 44, 60), fill=tuple(palette[3 * index:3 * index + 3]))
        d.text((x + 6, 66), str(dbz), font=font(16), fill='#ecf6fa')
    out = io.BytesIO();image.save(out, 'PNG')
    return out.getvalue()


async def collect(service, moment, region, frames=6):
    """Save archived radar frames ending at `moment`, cropped to the story region. Returns asset ids.

    `service` is the VisualEvidence collector (its store, allowlisted fetch and cache)."""
    from .visuals import region_extent
    extent = region_extent(region);store = service.store
    if moment > datetime.now(timezone.utc) - timedelta(minutes=30):
        raise ValueError('Archived radar is only used for past stories; live stories use NOAA nowCOAST.')
    ids = [];product = None;legend_id = None;missing = []
    for stamp in frame_times(moment, frames):
        derived = None
        for name in ([product] if product else list(PRODUCTS)):
            url = frame_url(name, stamp) + '#extent=' + ','.join(str(v) for v in extent)
            derived = next((a for a in store.visual_assets('radar') if a['source_url'] == url), None)
            if derived:
                product = name;break
        if derived:
            ids.append(derived['id']);legend_id = legend_id or derived['metadata'].get('legend_asset_id');continue
        body = wld = None
        for name in ([product] if product else list(PRODUCTS)):
            try:
                body, mime = await service.fetch(frame_url(name, stamp))
                wld, _ = await service.fetch(frame_url(name, stamp, 'wld'))
                product = name;break
            except (httpx.HTTPError, ValueError):   # 404: product not archived for this date, or a missing frame
                body = None
        if body is None:
            missing.append(f'{stamp:%H:%M}');continue
        if mime != 'image/png':
            raise ValueError('Archived radar frame is not a PNG.')
        png = await asyncio.to_thread(reproject, body, wld, extent, product)
        if legend_id is None:
            with Image.open(io.BytesIO(body)) as source:
                palette = source.getpalette()[:768]
            key = DOCS + '#legend=' + product
            existing = next((a for a in store.visual_assets('radar_legend') if a['source_url'] == key), None)
            legend_id = existing['id'] if existing else store.save_visual_asset({'kind': 'radar_legend', 'source_url': key,
                'observed_at': stamp.isoformat(), 'content_type': 'image/png',
                'metadata': {'attribution': ATTRIBUTION, 'label': f'Colour key drawn from the {product} palette (dBZ)'}}, legend_png(product, palette))
        ids.append(store.save_visual_asset({'kind': 'radar', 'source_url': frame_url(product, stamp) + '#extent=' + ','.join(str(v) for v in extent),
            'observed_at': stamp.isoformat(), 'content_type': 'image/png',
            'metadata': {'product': f'NEXRAD base reflectivity composite ({product})', 'data_class': 'radar_observation',
                         'projection': 'EPSG:3857', 'extent': extent, 'legend_asset_id': legend_id, 'attribution': ATTRIBUTION,
                         'original_url': frame_url(product, stamp), 'original_sha256': hashlib.sha256(body).hexdigest(),
                         'transformation': 'Cropped to the story region and reprojected from EPSG:4326 to EPSG:3857; values below 5 dBZ transparent.',
                         'catalogue_url': DOCS, 'note': 'Reflectivity is measured in dBZ; it is not a rainfall accumulation estimate.'}}, png))
    if len(ids) < 2:
        raise ValueError(f'Archived radar for {moment:%d %b %Y %H:%M UTC} is unavailable' + (f' (missing {", ".join(missing)} UTC).' if missing else '.'))
    return ids
