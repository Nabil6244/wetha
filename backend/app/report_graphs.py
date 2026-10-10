"""Automatic report charts. Only pinned source observations become plotted values."""
import math
import re
from datetime import datetime
from PIL import Image, ImageDraw
from .broadcast import label, easing

METRICS = {'wind_mph': ('Sustained wind', 'mph'), 'pressure_mb': ('Central pressure', 'mb')}


def prepare(scene, advisory):
    p = scene['parameters']
    if scene.get('media_id') or scene.get('cuts') or scene.get('map_mode', 'auto') != 'auto' or scene.get('graphic_style', 'auto') != 'auto':
        return None
    if getattr(advisory,'provider',None)=='NWS':
        return nws_graphs(scene,advisory)
    # Region-focused maps deliberately clear storm-wide facts.
    facts = p.get('facts', {})
    text = scene.get('script_segment', '').lower()
    eligible = scene.get('type') == 'what_changed' or any(word in text for word in ('sustained winds', 'central pressure', 'maximum winds'))
    if not eligible:
        return None
    charts = []
    for key, (name, unit) in METRICS.items():
        value = facts.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            continue
        points = {}
        for f in p.get('geojson', {}).get('features', []) if scene.get('type') == 'what_changed' else []:
            r = f.get('properties', {})
            v = r.get(key)
            if r.get('kind') != 'reported_center' or not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                continue
            # Never mix future forecast points with reported observations.
            stamp = r.get('issued_at')
            if not stamp:
                continue
            when = datetime.fromisoformat(stamp)
            if when <= advisory.issued_at and r.get('advisory_id'):
                points[when.isoformat()] = {'value': v, 'issued_at': when.isoformat(), 'advisory_id': r['advisory_id']}
        stamp = advisory.issued_at.isoformat()
        points[stamp] = {'value': value, 'issued_at': stamp, 'advisory_id': advisory.id}
        series = [points[k] for k in sorted(points)][-6:]
        chart = {'field': key, 'name': name, 'unit': unit, 'kind': 'trend' if len(series) > 1 else 'measurement', 'points': series}
        motion = facts.get('movement_mph')
        if key == 'wind_mph' and len(series) == 1 and isinstance(motion, (int,float)) and not isinstance(motion,bool) and math.isfinite(motion) and motion >= 0:
            chart['bars'] = [{'label':'Sustained wind','value':value},{'label':'Storm motion','value':motion}]
        charts.append(chart)
    if not charts:
        return None
    return {'title': advisory.title, 'source_advisory_id': advisory.id, 'charts': charts,
            'note': 'Reported advisory measurements. Connectors are visual guides, not intermediate observations.'}


def nws_graphs(scene, advisory):
    """Ranges quoted from this scene's pinned warning, never synthetic trends."""
    from .preview_audit import canonical, numeric_tokens
    text=canonical(advisory.text)
    scope=canonical(scene.get('source_claim_text') or scene.get('script_segment',''))
    charts=[]
    narrated_values=numeric_tokens(scope)
    if not narrated_values:return None
    specs=[('surge','Surge forecast above ground','ft',r'(\d+)\s*(?:to|and|-)\s*(\d+)\s*ft'),
           ('rain','Rainfall reported / forecast','in',r'(\d+)\s*(?:to|and|-)\s*(\d+)\s*in'),
           ('wind','Wind forecast','mph',r'(\d+)\s*(?:to|and|-)\s*(\d+)\s*mph'),
           ('gust','Forecast wind gust','mph',r'gusts(?:\s+up to)?\s*(\d+)\s*mph'),
           ('moving','Reported storm motion','knots',r'moving.{0,40}?(\d+)\s*knots'),
           ('gust','Marine gust threshold','knots',r'(\d+)\s*knots\s*or greater')]
    for topic,name,unit,pattern in specs:
        if topic not in scope:continue
        for m in list(re.finditer(pattern,text))[:2]:
            vals=[float(v) for v in m.groups()]
            if not all(f'{v:g}' in narrated_values for v in vals):continue
            before=re.split(r'[.!?]',text[max(0,m.start()-150):m.start()])[-1]
            qualifier='Additional possible' if any(w in before for w in ('additional','another')) else 'Already fallen' if any(w in before for w in ('fallen','radar indicated')) or 'fallen' in text[m.end():m.end()+45] else 'Source forecast'
            chart={'field':topic,'name':name,'unit':unit,'kind':'range' if len(vals)>1 else 'threshold' if 'threshold' in name.lower() else 'measurement',
                   'points':[{'value':vals[-1],'issued_at':advisory.issued_at.isoformat(),'advisory_id':advisory.id}],
                   'range':vals,'qualifier':'Warning threshold' if 'threshold' in name.lower() else 'Reported motion' if topic=='moving' else qualifier,'quote':m[0]}
            charts.append(chart)
    if not charts:return None
    return {'title':advisory.area,'source_advisory_id':advisory.id,'charts':charts[:2],
            'note':'Ranges and thresholds from the pinned warning. Forecast and already-fallen amounts remain separate; no invented trend.'}


def draw(image, data, t):
    """Transparent cards retain real imagery / geographic context behind the graphs."""
    overlay = Image.new('RGBA', image.size)
    d = ImageDraw.Draw(overlay)
    charts = data['charts']
    u = easing(min(1, t * 3))
    # Two distinct charts share units only within each panel.
    label(d, (95, 145), data['title'].upper()[:60], 36, '#65e1d1')
    for i, chart in enumerate(charts):
        top = 220 + i * 340
        d.rounded_rectangle((80, top, 1230, top + 310), radius=22, fill=(6, 23, 36, 238), outline='#3d7885', width=2)
        label(d, (115, top + 20), chart['name'].upper() + ' / ' + chart['unit'], 30, '#a8c4d0')
        pts = chart['points']
        latest = pts[-1]['value']
        if chart.get('range'):
            values=chart['range'];maximum=max(values)*1.4 or 1
            shown='–'.join(f'{v:g}' for v in values)
            label(d,(870,top+85),shown,65,'#65e1d1')
            label(d,(115,top+85),chart['qualifier'].upper(),27,'#a8c4d0')
            d.rectangle((120,top+160,800,top+195),fill='#233e4d')
            lo=values[0] if len(values)>1 else 0
            d.rectangle((120+680*lo/maximum*u,top+160,120+680*values[-1]/maximum*u,top+195),fill='#65e1d1')
            label(d,(115,top+235),'SOURCE RANGE / '+datetime.fromisoformat(pts[0]['issued_at']).strftime('%d %b %Y / %H:%M UTC'),22,'#a8c4d0')
            continue
        label(d, (920, top + 90), f'{latest:g}', 85, '#65e1d1')
        if chart.get('bars'):
            maximum = max(b['value'] for b in chart['bars']) or 1
            for j, bar in enumerate(chart['bars']):
                y = top + 95 + j * 65
                label(d, (115,y), bar['label'], 24, '#a8c4d0')
                width = 420 * bar['value'] / maximum * u
                d.rectangle((360,y,360+width,y+30),fill='#65e1d1' if j == 0 else '#ffc887')
                label(d, (800,y), f"{bar['value']:g}", 28)
            label(d,(115,top+235),'Wind and storm motion are different reported speeds / mph',23,'#a8c4d0')
            continue
        if len(pts) == 1:
            label(d, (125, top + 100), 'ONE REPORTED MEASUREMENT', 28)
            label(d, (125, top + 160), datetime.fromisoformat(pts[0]['issued_at']).strftime('%d %b %Y / %H:%M UTC'), 30, '#a8c4d0')
            label(d, (125, top + 225), 'Trend needs an earlier source observation', 25, '#a8c4d0')
            continue
        values = [p['value'] for p in pts]
        lo, hi = min(values), max(values)
        pad = max((hi - lo) * .3, 1)
        lo, hi = (0, max(values) + pad) if chart['field'] == 'wind_mph' else (lo - pad, hi + pad)
        x0, x1, y0, y1 = 215, 800, top + 100, top + 225
        label(d, (110, y0 - 12), f'{hi:g}', 22, '#a8c4d0')
        label(d, (110, y1 - 12), f'{lo:g}', 22, '#a8c4d0')
        d.line((200, y0, 200, y1, 820, y1), fill='#5c7b86', width=2)
        timestamps = [datetime.fromisoformat(p['issued_at']).timestamp() for p in pts]
        span = timestamps[-1] - timestamps[0]
        coords = [(x0 + (stamp - timestamps[0]) / span * (x1 - x0), y1 - (p['value'] - lo) / (hi - lo) * (y1 - y0)) for stamp, p in zip(timestamps, pts)]
        count = max(1, math.ceil(len(pts) * u))
        if chart['field'] == 'wind_mph':
            for x, y in coords[:count]:
                d.rounded_rectangle((x-18,y,x+18,y1),radius=5,fill='#65e1d1')
        elif count > 1:
            d.line(coords[:count], fill='#ffc887', width=6)
        for (x, y), p in zip(coords[:count], pts[:count]):
            d.ellipse((x-7, y-7, x+7, y+7), fill='#ffffff')
            label(d, (x-25, y-35), f"{p['value']:g}", 26)
        for x, p in ((x0, pts[0]), (x1, pts[-1])):
            label(d, (x-60, y1+18), datetime.fromisoformat(p['issued_at']).strftime('%d %b %H:%M'), 20, '#a8c4d0')
        label(d, (940, top + 220), f"{latest-pts[0]['value']:+g} {chart['unit']}", 32, '#ffc887')
    label(d, (95, 925), 'SOURCE VALUES / UTC · Separate scales · No forecast interpolation', 24, '#a8c4d0')
    result = Image.alpha_composite(image.convert('RGBA'), overlay)
    image.paste(result.convert(image.mode))
