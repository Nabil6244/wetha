"""Broadcast-style presentation of pinned facts; never generate weather observations."""
import math
import re
import textwrap
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

FPS = 8


def beats(timeline, scene):
    """Create readable beats from preserved source text and measured advisory values."""
    text = scene['script_segment']
    facts = timeline.get('reported_facts', {})
    title = timeline.get('report_title', timeline['title'])
    def card(label, value, detail='', kind='headline', **extra):
        return dict(label=label, value=str(value), detail=detail, kind=kind, **extra)
    if scene['type'] == 'news_intro':
        return [card('WEATHER BRIEF', title.upper(), 'NHC advisory · prerecorded report')] + ([card('REPORTED SUSTAINED WINDS', facts['wind_mph'], 'The headline measurement', 'stat', unit='mph')] if isinstance(facts.get('wind_mph'), (int, float)) else [])
    if text.startswith('According to'):
        stamp = datetime.fromisoformat(timeline['source_issued_at'])
        return [card('THE LATEST ADVISORY', stamp.strftime('%H:%M UTC'), stamp.strftime('%d %b %Y').upper(), 'stat'),
                card('THE STORY IN NUMBERS', title.upper(), 'Reported wind · pressure · movement')]
    if text.startswith('The advisory reports'):
        result = []
        for field, label, unit, detail in [('wind_mph', 'MAXIMUM SUSTAINED WINDS', 'mph', 'Reported by the National Hurricane Center'),
                                         ('pressure_mb', 'MINIMUM CENTRAL PRESSURE', 'mb', 'Reported advisory measurement'),
                                         ('movement_mph', 'REPORTED MOVEMENT', 'mph', 'Direction ' + str(facts.get('movement_degrees', 'unavailable')) + '°')]:
            if isinstance(facts.get(field), (int, float)):
                result.append(card(label, facts[field], detail, 'stat', unit=unit))
        if all(isinstance(facts.get(k), (int, float)) for k in ('latitude', 'longitude')):
            result.append(card('REPORTED CENTER', f"{abs(facts['latitude']):g}°{'N' if facts['latitude']>=0 else 'S'} / {abs(facts['longitude']):g}°{'E' if facts['longitude']>=0 else 'W'}", 'An advisory position, not a forecast track'))
        return result or [card('SOURCE REPORT', text)]
    if scene['type'] == 'what_changed':
        result = []
        for change in scene.get('parameters', {}).get('changes', []):
            if change['field'] not in ('wind_mph', 'pressure_mb') or not all(isinstance(change.get(k), (int, float)) for k in ('previous', 'current')):
                continue
            unit = 'mph' if change['field'] == 'wind_mph' else 'mb'
            delta = change['current'] - change['previous']
            result.extend([card('WHAT CHANGED / ' + ('WIND' if unit == 'mph' else 'PRESSURE'), f"{change['previous']:g} to {change['current']:g}", 'Previous advisory / this advisory', 'compare', unit=unit, previous=change['previous'], current=change['current']),
                           card(('WIND' if unit == 'mph' else 'PRESSURE') + ' CHANGE', f'{delta:+g}', 'Difference between reported measurements', 'stat', unit=unit)])
        positions = [c for c in scene.get('parameters', {}).get('changes', []) if c['field'] in ('latitude', 'longitude')]
        for change in positions:
            result.append(card('REPORTED POSITION / ' + change['field'].upper(), f"{change['previous']:g}° to {change['current']:g}°", 'Reported centers at separate advisory times'))
        result.append(card('WHAT CHANGED', 'GUIDANCE UPDATED', 'See the forecast section for the official wording'))
        return result
    if text.startswith('Official watch and warning coverage:'):
        result = []
        for line in text.splitlines()[1:]:
            label, separator, area = line.partition(' is in effect for:')
            if separator:
                clean = re.sub(r'^A ', '', label).upper()
                result.extend([card('OFFICIAL WATCH / WARNING', clean, 'Coverage listed in this NHC advisory', 'warning'), card(clean, area.strip(), 'Area named in the source advisory', 'warning')])
        return result or [card('OFFICIAL WARNINGS', text)]
    if text.startswith('Official forecast guidance'):
        raw = text.split(':', 1)[1].strip()
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', ' '.join(raw.split()))
        result = []
        for sentence in sentences:
            if not sentence.strip():
                continue
            reported = any(word in sentence for word in ('was located', 'is moving', 'winds are near', 'winds extend', 'central pressure is'))
            result.append(card('REPORTED CONDITIONS' if reported else 'NHC FORECAST GUIDANCE', sentence, 'Quoted from the issued advisory', 'forecast'))
        return result
    if text.startswith('Follow official local guidance'):
        return [card('STAY INFORMED', 'FOLLOW OFFICIAL\nLOCAL GUIDANCE', 'Recheck the latest advisory before broadcast'),
                card('WEATHER BRIEF', 'SOURCE: NOAA / NHC', 'Advisory issue time ' + timeline['source_issued_at'])]
    return [card('SOURCE REPORT', page) for page in textwrap.wrap(' '.join(text.split()), 145)]


def frames(timeline, scene, directory, observation_path):
    shots = beats(timeline, scene)
    from .location_labels import locator
    locator_image = locator(scene.get('parameters',{}))
    observations = scene['observations']
    # Full-frame native imagery crops are presentation crops, never map overlays.
    for index, observation in enumerate(observations):
        with Image.open(observation_path(observation)) as original:
            original = original.convert('RGB')
            image = ImageOps.fit(original, (1920, 1080), centering=(0.5, 0.48))
            wash = Image.new('RGBA', image.size, (2, 9, 18, 0))
            shade = ImageDraw.Draw(wash)
            for x in range(0, 1500, 10):
                alpha = int(210 * (1 - x/1500))
                shade.rectangle((x, 0, x+9, 1080), fill=(2, 9, 18, alpha))
            image = Image.alpha_composite(image.convert('RGBA'), wash)
            draw = ImageDraw.Draw(image)
            stamp = datetime.fromisoformat(observation['observed_at'])
            draw.text((1450, 105), 'GOES-19 / GEOCOLOR', font=ImageFont.load_default(size=22), fill='#ffffff')
            draw.text((1450, 138), stamp.strftime('%d %b · %H:%M UTC'), font=ImageFont.load_default(size=22), fill='#b5d5e4')
            image.convert('RGB').save(directory / f'observation-{index:03}.png')
    fonts = {n: ImageFont.load_default(size=n) for n in (18, 20, 24, 26, 30, 34, 38, 50, 68, 82, 180)}
    count = max(1, math.ceil(scene['seconds'] * FPS))
    for index in range(count):
        t = index / count * len(shots)
        shot_index = min(int(t), len(shots)-1)
        shot = shots[shot_index]
        local_seconds = (t - shot_index) * scene['seconds'] / len(shots)
        reveal = min(1, local_seconds / 0.7)
        ease = 1 - (1-reveal)**3
        x = round(90 - 55*(1-ease))
        image = Image.new('RGBA', (1920,1080), (0,0,0,0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1920, 78), fill=(2, 9, 18, 205))
        draw.text((90, 24), 'WEATHER / BRIEF', font=fonts[26], fill='#ffffff')
        draw.text((1330, 28), timeline['source_label'].upper().replace('_',' ') + ' · EDITORIAL PREVIEW', font=fonts[20], fill='#b5d5e4')
        draw.rectangle((x, 230, x+round(95*ease), 238), fill='#65f0df')
        color = '#ffc77b' if shot['kind']=='warning' else '#65f0df'
        draw.text((x, 268), shot['label'], font=fonts[30], fill=color)
        if shot['kind']=='stat':
            draw.text((x, 340), shot['value'], font=fonts[180], fill='#ffffff')
            if shot.get('unit'):
                width = draw.textlength(shot['value'], font=fonts[180])
                draw.text((x+width+26, 465), shot['unit'], font=fonts[50], fill=color)
            detail_y = 590
        elif shot['kind']=='compare':
            draw.text((x, 350), shot['value'], font=fonts[82], fill='#ffffff')
            draw.text((x, 465), shot['unit'].upper() + ' / MEASURED PRESSURE' if shot['unit']=='mb' else shot['unit'].upper() + ' / MEASURED WIND', font=fonts[30], fill=color)
            # Two actual measurements with a labeled numeric extent; the connector is not a measured continuous series.
            previous, current = shot['previous'], shot['current']
            lo, hi = min(previous,current), max(previous,current)
            span = max(hi-lo,1)
            left, right = x+240, x+760
            y0=670-(previous-lo)/span*130
            y1=670-(current-lo)/span*130
            draw.line((x+165,540,x+165,670),fill='#7fa3b5',width=2)
            draw.text((x,528), f'{hi:g}',font=fonts[24],fill='#b5d5e4')
            draw.text((x,660), f'{lo:g}',font=fonts[24],fill='#b5d5e4')
            draw.line((left,y0,left+(right-left)*ease,y0+(y1-y0)*ease),fill=color,width=5)
            for px,py,value in ((left,y0,previous),(right,y1,current)):
                draw.ellipse((px-9,py-9,px+9,py+9),fill='#ffffff')
                draw.text((px-35,py-40),f'{value:g}',font=fonts[26],fill='#ffffff')
            draw.text((left-45,700),'PREVIOUS',font=fonts[24],fill='#b5d5e4')
            draw.text((right-35,700),'LATEST',font=fonts[24],fill=color)
            detail_y=770
            shot = {**shot, 'detail': 'Two advisory measurements; line is a visual connector'}
        else:
            # Short headlines and warning areas replace long prose panels.
            size = (50 if len(shot['value']) > 145 else 68) if shot['kind'] in ('warning','forecast') else 82
            width = 43 if size == 50 else 32 if size == 68 else 26
            lines = '\n'.join(textwrap.wrap(shot['value'], width))
            draw.multiline_text((x, 345), lines, font=fonts[size], fill='#ffffff', spacing=12)
            detail_y = min(820, 355+len(lines.splitlines())*(size+12)+45)
        draw.multiline_text((x, detail_y), '\n'.join(textwrap.wrap(shot['detail'], 66)), font=fonts[26], fill='#b5d5e4', spacing=7)
        if locator_image is not None:
            image.alpha_composite(locator_image,(1280,575))
        # A restrained moving rail keeps timing visible without looking like app controls.
        y=925
        width=1260/len(shots)
        for j in range(len(shots)):
            draw.rectangle((90+j*width,y,90+(j+1)*width-8,y+4), fill=color if j==shot_index else '#526777')
        draw.rectangle((0, 985, 1920, 1080), fill=(2, 9, 18, 225))
        issued = datetime.fromisoformat(timeline['source_issued_at']).strftime('%d %b %Y · %H:%M UTC')
        draw.text((90, 1005), 'NHC ADVISORY  ' + issued, font=fonts[20], fill='#e7f1f8')
        draw.text((1100, 1005), 'NOAA / NESDIS / STAR imagery', font=fonts[20], fill='#e7f1f8')
        draw.text((90, 1037), 'Cropped regional satellite context · independent observation times · IR enhancement · no event attribution', font=fonts[18], fill='#b5d5e4')
        image.save(directory / f'overlay-{index:04}.png', compress_level=1)
    return shots, count


def score_filter(seconds):
    """Original locally synthesized instrumental pulse. No model, sample, or voice."""
    return ("aevalsrc=0.07*sin(2*PI*55*t)*(0.3+0.7*pow(max(0\\,sin(2*PI*t/0.75))\\,16))"
            "+0.018*(sin(2*PI*110*t)+sin(2*PI*130.8128*t)+sin(2*PI*164.8138*t))*(0.6+0.4*sin(2*PI*t/12))"
            "+0.012*sin(2*PI*880*t)*pow(max(0\\,sin(2*PI*t/0.375))\\,32):s=48000:d=" + str(seconds))
