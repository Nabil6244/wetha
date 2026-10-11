"""Animation is a presentation reveal, never simulated meteorology."""
import math,re,textwrap
from PIL import Image,ImageDraw
from .broadcast import label,map_point,easing

COLORS={'track':'#65e1d1','warnings':'#ffc887','radar':'#73b9ff','forecast':'#cab7e4'}


def geometry(image,parameters,bounds,t):
    mode=parameters.get('map_mode');color=COLORS.get(mode,'#65e1d1')
    wanted='alert_area' if mode=='warnings' else 'forecast_cone' if mode=='forecast' and parameters.get('map_has_layer') else None
    if not wanted:return
    overlay=Image.new('RGBA',image.size);d=ImageDraw.Draw(overlay)
    for f in parameters.get('geojson',{}).get('features',[]):
        if f.get('properties',{}).get('kind')!=wanted:continue
        g=f['geometry']
        if g['type'] not in ('Polygon','MultiPolygon'):continue
        for poly in g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]:
            pts=[map_point(c,bounds) for c in poly[0]]
            rgb=tuple(int(color[i:i+2],16) for i in (1,3,5));alpha=int(35+25*easing(t))
            d.polygon(pts,fill=(*rgb,alpha))
            for hole in poly[1:]:d.polygon([map_point(c,bounds) for c in hole],fill=(0,0,0,0))
            count=max(2,int(len(pts)*easing(min(1,t*1.5))))
            for i in range(count-1):
                if mode!='forecast' or i%2==0:d.line((pts[i],pts[i+1]),fill=(*rgb,235),width=6)
    image.paste(Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB'))


def hud(draw,p,t):
    mode=p['map_mode'];color=COLORS[mode]
    if mode=='radar' and p.get('map_observations'):
        # Radar fills the picture; text needs its own backing to stay legible over the echo.
        for box in ((45,98,560,146),(1405,98,1880,146),(45,250,720,384),(45,735,915,795)):
            draw.rounded_rectangle(box,radius=10,fill='#061724')
    label(draw,(60,108),{'track':'OBSERVED / REPORTED','warnings':'SOURCE WARNING COVERAGE','radar':'OBSERVATIONS · NOT A FORECAST','forecast':'EXPECTED · NOT OBSERVED'}[mode],28,color)
    label(draw,(1420,108),p.get('map_source_label','SOURCE RECORD'),25,color)
    if mode=='forecast':label(draw,(1150,260),'Dots: reported centers, not future positions',23,color)
    if mode=='track':
        f=p.get('facts',{});bearing=f.get('movement_degrees');speed=f.get('movement_mph')
        draw.rounded_rectangle((1310,215,1840,575),radius=18,fill='#061724',outline=color,width=2)
        label(draw,(1340,240),'REPORTED MOTION',28,color)
        if isinstance(bearing,(int,float)):
            cx,cy=1550,390;a=math.radians(bearing)
            end=(cx+85*math.sin(a),cy-85*math.cos(a))
            draw.ellipse((cx-95,cy-95,cx+95,cy+95),outline='#365666',width=2)
            draw.line((cx,cy,*end),fill=color,width=7)
            for delta in (-.55,.55):
                x=end[0]-22*math.sin(a+delta);y=end[1]+22*math.cos(a+delta)
                draw.line((*end,x,y),fill=color,width=5)
            label(draw,(1335,510),f'{bearing}° bearing · {speed} mph',29)
        else:label(draw,(1340,340),'Bearing unavailable',28)
        label(draw,(1315,595),'Arrow shows bearing, not a forecast route',23,color)
    elif mode=='warnings':
        lines=p.get('map_warning_text',[])[:2]
        if not lines:lines=['No warning coverage extracted from this source.']
        panel(draw,'NAMED COVERAGE',lines,color)
    elif mode=='forecast':
        raw=p.get('map_forecast_text','');sentences=re.split(r'(?<=[.!?]) +',raw)
        wording=next((s for s in sentences if 'expected' in s.lower()),'Forecast wording unavailable; consult the original source.')
        panel(draw,'SOURCE FORECAST WORDING',[wording,'Issue: '+p.get('map_issue_time','unknown'), 'Valid: '+p.get('map_valid_time','geometry valid time unavailable')],color)
    elif mode=='radar':
        obs=p.get('map_observations',[])
        if obs:
            current=obs[min(len(obs)-1,int(t*len(obs)))]['observed_at']
            label(draw,(60,260),'OBSERVED '+current[:16].replace('T',' ')+' UTC',29,color)
            label(draw,(60,305),'Reflectivity (dBZ) · regional context',25)
            label(draw,(60,344),'Not rainfall totals or predicted rain',23,color)
        else:panel(draw,'RADAR LAYER UNAVAILABLE',['No source observations close to this advisory.','No precipitation intensity or future rain inferred.'],color)
    # A playback indicator describes the animation, not weather movement.
    draw.rectangle((60,775,900,783),fill='#365666')
    draw.rectangle((60,775,60+max(1,840*max(0,min(1,t))),783),fill=color)
    label(draw,(60,744),'MAP SCENE PLAYBACK',19,color)


def panel(draw,title,paragraphs,color):
    draw.rounded_rectangle((60,285,1080,710),radius=18,fill='#061724',outline=color,width=2)
    label(draw,(85,310),title,28,color)
    y=362
    for text in paragraphs:
        for line in textwrap.wrap(text,width=59)[:4]:
            if y>663:return
            label(draw,(85,y),line,28);y+=38
        y+=14
