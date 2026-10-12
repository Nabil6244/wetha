"""Varied motion graphics drawn only from pinned scene facts and timestamps."""
import math
from datetime import datetime
from .broadcast import label, easing

STYLES={
    'change_gauge':'Change dial', 'comparison_split':'Before / after split',
    'advisory_timeline':'Advisory timeline', 'forecast_clock':'Forecast time ladder',
    'question_reveal':'Question / answer reveal', 'source_card':'Source spotlight',
}


def prepare(scene, advisory):
    style=scene['graphic_style'];p=scene['parameters']
    changes=[c for c in p.get('changes',[]) if c['field'] in ('wind_mph','pressure_mb') and all(isinstance(c.get(k),(int,float)) for k in ('previous','current'))]
    if style in ('change_gauge','comparison_split','question_reveal') and not changes:
        raise ValueError('This graphic needs two source-reported wind or pressure measurements. Choose a comparison scene.')
    records=[]
    for f in p.get('geojson',{}).get('features',[]):
        if f.get('properties',{}).get('kind')=='reported_center' and f['geometry']['type']=='Point':
            records.append({**f['properties'],'coordinates':f['geometry']['coordinates']})
    records.sort(key=lambda r:r.get('issued_at',''))
    if style=='advisory_timeline' and len(records)<2:
        raise ValueError('Advisory timeline needs at least two source-reported positions.')
    forecast=[s for s in scene['direction']['sources'] if s['data_type']=='forecast']
    if style=='forecast_clock' and not forecast:
        raise ValueError('Forecast time ladder needs a source layer with explicit issue and valid times. Select Forecast map first.')
    p['graphic_data']={'changes':changes,'records':records,'issued_at':advisory.issued_at.isoformat(),
        'provider':advisory.provider,'title':advisory.title,'valid_until':forecast[-1]['forecast_valid_time'] if forecast else None}
    p['graphic_style']=style
    p.pop('map_mode',None)
    scene['direction'].update(scene_type='region_focus',asset_ids=[],layers=[],fallback=None)
    scene['direction']['headline']=STYLES[style].upper()


def draw(image,style,data,t):
    from PIL import ImageDraw
    d=ImageDraw.Draw(image);d.rectangle((0,82,1920,970),fill='#081d2c')
    u=easing(min(1,t*2))
    # Shapes reveal measured endpoints. Numbers never interpolate into fake observations.
    changes=data.get('changes',[])
    if style=='change_gauge':
        c=changes[0];delta=c['current']-c['previous'];unit='mph' if c['field']=='wind_mph' else 'mb'
        box=(1080,210,1710,840)
        d.arc(box,135,405,fill='#294957',width=28)
        d.arc(box,135,135+270*u,fill='#65e1d1',width=28)
        label(d,(180,245),'THE CHANGE',40,'#65e1d1')
        label(d,(180,345),f'{delta:+g}',180)
        label(d,(190,555),unit.upper()+' / REPORTED DIFFERENCE',32)
        label(d,(180,665),f"{c['previous']:g} → {c['current']:g} {unit}",64)
        label(d,(1195,430),f'{delta:+g}',125,'#65e1d1')
        label(d,(1260,590),unit,48)
        label(d,(1155,705),'TWO SOURCE MEASUREMENTS',23,'#a8c4d0')
    elif style=='comparison_split':
        for j,c in enumerate(changes[:2]):
            y=250+j*330;unit='mph' if c['field']=='wind_mph' else 'mb'
            label(d,(100,y),c['field'].replace('_',' ').upper(),30,'#a8c4d0')
            for x,value,tag,color in [(120,c['previous'],'BEFORE','#a8c4d0'),(1110,c['current'],'AFTER','#65e1d1')]:
                label(d,(x,y+55),f'{value:g}',120,color)
                label(d,(x+300,y+135),unit,37,color)
                label(d,(x,y+215),tag,26,color)
            d.line((920,y+55,920,y+240),fill='#365666',width=3)
            d.line((750,y+145,750+220*u,y+145),fill='#65e1d1',width=9)
    elif style=='advisory_timeline':
        records=data['records'][:6]
        label(d,(95,235),'THE STORM / ONE ADVISORY AT A TIME',44,'#65e1d1')
        count=max(1,math.ceil(len(records)*min(1,t*1.6)))
        d.line((170,510,170+1570*u,510),fill='#65e1d1',width=7)
        for i,r in enumerate(records[:count]):
            x=170+i*1570/max(1,len(records)-1)
            d.ellipse((x-14,496,x+14,524),fill='#ffffff')
            stamp=datetime.fromisoformat(r['issued_at'])
            label(d,(x-75,365),stamp.strftime('%d %b').upper(),28,'#a8c4d0')
            label(d,(x-80,415),stamp.strftime('%H:%M UTC'),30)
            coord=r['coordinates'];label(d,(x-85,580),f'{coord[1]:g}° / {coord[0]:g}°',26)
            if isinstance(r.get('wind_mph'),(int,float)):label(d,(x-70,645),f"{r['wind_mph']:g} mph",34,'#65e1d1')
        label(d,(95,815),'Separate reported measurements; connectors are presentation guides',28,'#a8c4d0')
    elif style=='forecast_clock':
        issue=datetime.fromisoformat(data['issued_at']);valid=datetime.fromisoformat(data['valid_until'])
        hours=(valid-issue).total_seconds()/3600
        label(d,(105,220),'WHEN WAS THIS FORECAST ISSUED?',42,'#cab7e4')
        for i,(tag,value) in enumerate([('ISSUED',issue.strftime('%d %b %Y / %H:%M UTC')),('LAST SOURCE POINT',valid.strftime('%d %b %Y / %H:%M UTC'))]):
            y=360+i*290
            d.rounded_rectangle((95,y-25,1810,y+155),radius=18,fill='#122f40')
            label(d,(125,y),tag,30,'#cab7e4');label(d,(125,y+55),value.upper(),65)
        label(d,(125,850),f'{hours:g} hours between these source timestamps / not an arrival-time prediction',27)
    elif style=='question_reveal':
        c=changes[0];delta=c['current']-c['previous'];name='Wind' if c['field']=='wind_mph' else 'Pressure';unit='mph' if name=='Wind' else 'mb'
        label(d,(110,225),'LOOK CLOSELY',33,'#65e1d1')
        label(d,(110,320),f'Did {name.lower()} rise or fall?',80)
        if t>.42:
            label(d,(110,495),'ROSE' if delta>0 else 'FELL' if delta<0 else 'HELD STEADY',115,'#65e1d1')
            label(d,(115,665),f"{c['previous']:g} → {c['current']:g} {unit}",65)
            label(d,(115,805),'The answer comes from the two archived advisories.',30,'#a8c4d0')
        else:
            d.line((115,565,115+1550*min(1,t/.42),565),fill='#65e1d1',width=8)
            label(d,(115,640),'ANSWER IN THE SOURCE RECORD',35,'#a8c4d0')
    elif style=='source_card':
        stamp=datetime.fromisoformat(data['issued_at'])
        d.rounded_rectangle((130,200,1790,900),radius=26,fill='#102d3d',outline='#365666',width=2)
        label(d,(200,250),'CHECK THE SOURCE',34,'#65e1d1')
        label(d,(200,345),data['provider'],130)
        label(d,(205,540),data['title'][:60],48)
        label(d,(205,650),stamp.strftime('%d %b %Y / %H:%M UTC').upper(),60)
        d.line((205,800,205+1490*u,800),fill='#65e1d1',width=7)
    elif style=='warning_timeline':
        issued=datetime.fromisoformat(data['issued_at']);expires=datetime.fromisoformat(data['expires_at'])
        minutes=round((expires-issued).total_seconds()/60)
        label(d,(105,215),data['event'].upper(),50,data['color'])
        label(d,(108,290),'ISSUED BY '+data['office'].upper(),28,'#a8c4d0')
        d.rounded_rectangle((150,470,1770,530),radius=30,fill='#1b3846')
        d.rounded_rectangle((150,470,150+max(60,1620*u),530),radius=30,fill=data['color'])
        for x,tag,stamp in ((150,'ISSUED',issued),(1770,'EXPIRES',expires)):
            anchor=x if tag=='ISSUED' else x-420
            label(d,(anchor,575),tag,28,'#a8c4d0');label(d,(anchor,620),stamp.strftime('%H:%M UTC'),78)
            label(d,(anchor,715),stamp.strftime('%d %b %Y'),30,'#a8c4d0')
        if t>.35:label(d,(150,780),f'In effect {minutes//60} h {minutes%60:02d} min, as issued · times from the NWS alert record',34,'#ffffff')
    elif style=='zone_compare':
        rows=data['rows'];top=max(r['range'][1] for r in rows)*1.15
        label(d,(105,205),data['title'].upper(),44,'#65e1d1')
        label(d,(108,268),data['subtitle'],26,'#a8c4d0')
        step=min(62,480/len(rows))
        for i,r in enumerate(rows):
            y=340+i*step;lo,hi=r['range'];own=r['own']
            label(d,(105,y),r['label'].upper()[:22],30 if own else 26,'#ffffff' if own else '#a8c4d0')
            d.rectangle((560,y+8,1560,y+40),fill='#16303d')
            reveal=easing(min(1,max(0,t*2.2-i*.08)))
            x0=560+1000*lo/top;x1=560+1000*hi/top
            d.rectangle((x0,y+8,x0+(x1-x0)*reveal,y+40),fill='#65e1d1' if own else '#3f8fa0')
            if reveal>.5:label(d,(1590,y+2),f'{lo:g}–{hi:g}',34,'#65e1d1' if own else '#ecf6fa')
        label(d,(105,845),'Each range quoted from its own warning: "peak wind forecast" · same issue time · not measured winds',24,'#a8c4d0')
    else:raise ValueError('Unknown graphic style.')
