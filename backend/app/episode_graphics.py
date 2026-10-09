"""Editorial treatments for a source-pinned historical episode."""
import math
import copy
import textwrap
from PIL import Image, ImageDraw, ImageOps
from .broadcast import Composer, SIZE, easing, label, map_point


def caption(image, text, beat, t=1):
    d = ImageDraw.Draw(image)
    lines = textwrap.wrap(text, width=77)
    if len(lines) > 2:
        raise ValueError('Episode captions must fit two lines.')
    bottom = 156 + len(lines) * 45
    d.rectangle((40, 105, 1880, bottom), fill='#061724')
    label(d, (62, 119), beat.upper(), 22, '#65e1d1')
    for i, line in enumerate(lines):
        label(d, (62, 156+i*45), line, 38)
    d.rectangle((40, bottom, 40+max(1, 1840*t), bottom+4), fill='#65e1d1')


class EpisodeComposer(Composer):
    def __init__(self, direction, parameters, load_asset=None):
        super().__init__(direction, copy.deepcopy(parameters), load_asset)
        kind = parameters.get('episode_map')
        if kind in ('forecast', 'warnings'):
            # Forecast points are predictions, never reported observations.
            self.records = []
        frame_range = parameters.get('observation_frame_range')
        if frame_range:
            a, b = frame_range
            if not 0 <= a < b <= len(self.sources):
                raise ValueError('Invalid genuine observation frame range.')
            self.sources = self.sources[a:b]

    def frame(self, t):
        image = super().frame(t)
        p = self.parameters
        kind = p.get('episode_map')
        if kind == 'rainfall':
            # Retain the complete native legend and city labels.
            native = ImageOps.contain(self.sources[0], (1720, 680))
            ImageDraw.Draw(image).rectangle((0, 82, 1920, 970), fill='#081d2c')
            image.paste(native, ((1920-native.width)//2, 267))
            d = ImageDraw.Draw(image)
            d.rounded_rectangle((55,365,435,660),radius=18,fill='#0d2937')
            label(d,(80,388),'GAUGE OBSERVATION',25,'#65e1d1')
            label(d,(80,430),'6.80',105)
            label(d,(82,550),'INCHES',34,'#65e1d1')
            label(d,(80,608),'SC-GT-42 / NWS',24,'#a8c4d0')
        if kind in ('forecast', 'warnings'):
            layer = Image.new('RGBA', SIZE)
            d = ImageDraw.Draw(layer)
            features = p['geojson']['features']
            if kind == 'warnings':
                colors = {'HWR': '#ff697b', 'TWR': '#ffae63', 'HWA': '#ffe889', 'TWA': '#ffe889'}
                for f in features:
                    if f['properties']['kind'] != 'warning_coast': continue
                    color = colors.get(f['properties']['TCWW'])
                    if not color: raise ValueError('Unknown official warning code.')
                    for line in f['geometry']['coordinates']:
                        points = [map_point(c, self.bounds) for c in line]
                        count = max(2, math.ceil(len(points)*easing(min(1, t*2))))
                        d.line(points[:count], fill=color, width=9)
                d.rectangle((60, 780, 570, 940), fill='#061724')
                for i, (title, color) in enumerate([('Hurricane warning', '#ff697b'), ('Tropical storm warning', '#ffae63'), ('Watch', '#ffe889')]):
                    d.line((80, 806+i*43, 125, 806+i*43), fill=color, width=8)
                    label(d, (143, 790+i*43), title, 27, color)
            else:
                for f in features:
                    if f['properties']['kind'] == 'forecast_cone':
                        for ring in f['geometry']['coordinates']:
                            points = [map_point(c, self.bounds) for c in ring]
                            d.polygon(points, fill=(159, 112, 239, round(65*easing(min(1,t*2)))))
                            d.line(points, fill='#cab7e4', width=3)
                points = [f for f in features if f['properties']['kind'] == 'forecast_point']
                points.sort(key=lambda f: f['properties']['valid_time'])
                revealed = points[:max(1, math.ceil(len(points)*min(1,t*1.6)))]
                xy = [map_point(f['geometry']['coordinates'], self.bounds) for f in revealed]
                if len(xy)>1: d.line(xy, fill='#cab7e4', width=5)
                for f, (x,y) in zip(revealed,xy):
                    d.ellipse((x-9,y-9,x+9,y+9),fill='#e5d7ff')
                    stamp=f['properties']['valid_time']
                    label(d,(x+16,y-12), stamp[8:10]+' AUG '+stamp[11:16]+' UTC',23,'#e5d7ff')
                d.rectangle((60,805,1110,938),fill='#061724')
                label(d,(82,822),'AS ISSUED: 04 AUG 2020 / 03 UTC',27,'#cab7e4')
                label(d,(82,861),'Cone = possible center positions, not total impact area',25)
                label(d,(82,901),'Future points through 06 AUG / 12 UTC',23,'#a8c4d0')
            # Geographic features outside the presentation viewport must not
            # overwrite the channel header, narrative banner or source footer.
            alpha=layer.getchannel('A')
            mask=Image.new('L',SIZE);mask.paste(alpha.crop((0,260,1920,970)),(0,260))
            layer.putalpha(mask)
            image = Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB')
        if p.get('episode_caption'):
            caption(image,p['episode_caption'],p['episode_beat'],t)
        return image
