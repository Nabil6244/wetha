"""Distinct statistical treatments for an immutable NWS/NHC bulletin snapshot."""
import math, textwrap
from collections import Counter
from PIL import Image, ImageDraw
from .broadcast import SIZE, label, easing
from .forecast_news import stamp

TEAL='#82efdc'; AMBER='#ffb06c'; PINK='#ff6375'; MUTED='#89a8b2'; WHITE='#f2f8fb'
STAT_MODES={'storm-facts','forecast-window','forecast-scope','surge-height','rainfall-range','alert-counts',
 'rain-ranking','rain-contrast','rain-matrix','wind-ranges','forecast-timeline','wind-ladder','wind-direction',
 'temperature-strip','south-cards','rain-lollipops','temperature-heat','rain-dots','wind-checkpoints','takeaways','source-clock'}


def points(snapshot,hours):
    return next(s['points'] for s in snapshot['snapshots'] if s['hours']==hours)


def rain_ranking(snapshot,hours):
    """Null is missing, never a dry forecast; tied ranks preserve source order."""
    return sorted(points(snapshot,hours),key=lambda p:(p['forecast']['rain_probability'] is None,
                  -(p['forecast']['rain_probability'] or 0)))


def rain_gap(snapshot,hours,first='panama-city',second='miami'):
    by_id={p['id']:p for p in points(snapshot,hours)}
    a=by_id[first]['forecast']['rain_probability']; b=by_id[second]['forecast']['rain_probability']
    return None if a is None or b is None else a-b


def alert_counts(snapshot):
    # Records may overlap. This is not a count of cities, people, or unique areas.
    return Counter(a['event'] for a in snapshot['alerts'])


def fade(t,index=0,count=1):
    return easing(max(0,min(1,(t-.035*index)*2.8)))


def background():
    im=Image.new('RGB',SIZE,'#071722');d=ImageDraw.Draw(im)
    for y in range(235,985,8):
        u=(y-235)/750;d.rectangle((0,y,1920,y+7),fill=(7+int(u*5),23+int(u*12),34+int(u*17)))
    return im


def title(d,text,sub):
    label(d,(80,260),text,37,WHITE);label(d,(80,317),sub,25,MUTED)


def note(d,text):label(d,(80,945),text,24,MUTED)


def grid(d,x0,x1,y0,y1,maximum,unit):
    for i in range(5):
        x=x0+(x1-x0)*i/4;d.line((x,y0,x,y1),fill='#24404e',width=1)
        label(d,(x-15,y1+12),f'{maximum*i/4:g}{unit}',22,MUTED)


def pct(v):return 'N/A' if v is None else f'{v:g}%'


def render_stat(row,snapshot,t):
    mode=row['kind'];im=background();d=ImageDraw.Draw(im);h=row['hours'];ps=points(snapshot,h)
    storm=snapshot['nhc'][0];facts=storm['latest']['facts'];counts=alert_counts(snapshot)
    valid=stamp(next(s['valid_at'] for s in snapshot['snapshots'] if s['hours']==h)).strftime('%d OCT / %H:%M UTC')
    if mode=='storm-facts':
        title(d,'THREE STORM MEASUREMENTS','NHC public bulletin / reported storm values')
        for i,(value,unit,name) in enumerate([(facts['wind_mph'],'mph','MAXIMUM SUSTAINED WIND'),(facts['pressure_mb'],'mb','MINIMUM CENTRAL PRESSURE'),(facts['movement_mph'],'mph','FORWARD MOTION')]):
            x=85+i*610;y=430+35*(1-fade(t,i));label(d,(x,y),str(value),133,[PINK,TEAL,AMBER][i]);label(d,(x,y+162),unit,44)
            label(d,(x,y+245),name,26,MUTED);d.line((x,800,x+480*fade(t,i),800),fill=[PINK,TEAL,AMBER][i],width=5)
        note(d,'Different quantities / storm wind is not a city measurement or forward speed')
    elif mode=='forecast-window':
        title(d,'WHEN DOES THE BULLETIN EXPECT LANDFALL?','Qualitative forecast window from the public bulletin')
        d.line((160,630,1740,630),fill='#3b5364',width=5)
        for i,(text,x) in enumerate([('FRIDAY NIGHT',340),('EARLY SATURDAY',1240)]):
            if t>.12*i:
                d.ellipse((x-18,612,x+18,648),fill=AMBER);label(d,(x-130,500),text,42,WHITE)
        label(d,(210,735),'Tonight or early Saturday / within the warning area',40,AMBER)
        note(d,'The source does not give an exact landfall minute. This graphic does not invent one.')
    elif mode=='forecast-scope':
        title(d,'WHAT DOES THE CONE MEAN?','Center forecast and impact area answer different questions')
        for i,(head,body,color) in enumerate([('CENTER','Where the storm center may travel',TEAL),('COAST','Where official coastal warnings apply',PINK),('IMPACTS','Can extend outside the cone',AMBER)]):
            x=85+i*610;yy=440;d.line((x,yy,x,yy+320*fade(t,i)),fill=color,width=7)
            label(d,(x+30,yy),head,47,color)
            for line,text in enumerate(textwrap.wrap(body,width=24)):label(d,(x+30,yy+110+line*50),text,30)
        note(d,'Concept explanation / no additional hazard boundary is drawn')
    elif mode=='surge-height':
        title(d,'CONDITIONAL SURGE / 5–7 FEET ABOVE GROUND','Dauphin Island, AL → Indian Pass, FL / NHC public bulletin')
        y0=860;scale=52;d.line((220,y0,1670,y0),fill=MUTED,width=4)
        for v in range(0,9,2):
            y=y0-v*scale;d.line((220,y,260,y),fill=MUTED,width=2);label(d,(120,y-16),f'{v} ft',26,MUTED)
        u=fade(t);d.rectangle((500,y0-7*scale*u,1040,y0-5*scale*u),fill='#ba7950')
        d.rectangle((500,y0-5*scale*u,1040,y0),fill='#1b5264')
        label(d,(1110,520),'5–7 ft',108,AMBER);label(d,(1110,665),'IF PEAK SURGE COINCIDES',27);label(d,(1110,707),'WITH HIGH TIDE',27)
        note(d,'Source range / coastal conditions differ / not a prediction for every property')
    elif mode=='rainfall-range':
        title(d,'REGIONAL RAINFALL AMOUNT / THROUGH THE WEEKEND','Florida Panhandle & Big Bend / inches / NHC forecast')
        x0=180;width=1450;y=605
        for v in [0,4,8,12,16]:
            x=x0+width*v/16;d.line((x,y-30,x,y+100),fill='#35515e',width=2);label(d,(x-15,y+130),str(v),32,MUTED)
        d.line((x0+width*4/16,y,x0+width*(4+4*fade(t))/16,y),fill=TEAL,width=28)
        label(d,(540,445),'4–8 inches',85,TEAL)
        x=x0+width*15/16
        if t>.18:d.polygon([(x,y-18),(x+18,y),(x,y+18),(x-18,y)],fill=AMBER)
        label(d,(1190,795),'Localized: up to 15 in',35,AMBER)
        note(d,'Rainfall total over a period / separate from an hourly chance of precipitation')
    elif mode=='alert-counts':
        title(d,'ACTIVE FLORIDA ALERT RECORDS','NWS state feed at collection / four selected alert types')
        types=['Tropical Storm Warning','Storm Surge Warning','Hurricane Warning','Flood Warning']
        for i,name in enumerate(types):
            x=100+(i%2)*880;y=440+(i//2)*225
            label(d,(x,y),str(counts[name]),100,[AMBER,PINK,PINK,TEAL][i]);label(d,(x+160,y+45),name,34)
            d.line((x,y+145,x+650*fade(t,i),y+145),fill='#35515e',width=3)
        note(d,'Records can overlap and cover multiple zones / counts are not people or unique locations')
    elif mode=='rain-ranking':
        title(d,'WHICH POINTS HAVE THE HIGHEST RAIN CHANCE?',valid+' / eight hourly NWS grid points')
        ranked=rain_ranking(snapshot,h);grid(d,560,1640,390,880,100,'%')
        for i,p in enumerate(ranked):
            y=390+i*59;v=p['forecast']['rain_probability'];color=AMBER if i<3 else TEAL
            label(d,(80,y),p['name'].upper(),29,color)
            if v is not None:d.rectangle((560,y+5,560+1080*v/100*fade(t,i),y+33),fill=color)
            label(d,(1680,y),pct(v),31,color)
        note(d,'Ranking only these eight points / precipitation probability, not rainfall amount')
    elif mode=='rain-contrast':
        title(d,'SAME HOUR. VERY DIFFERENT RAIN CHANCES.',valid+' / Panama City and Miami point forecasts')
        selected=[next(p for p in ps if p['id']==city) for city in ['panama-city','miami']]
        for i,p in enumerate(selected):
            x=110+i*1080;v=p['forecast']['rain_probability'];label(d,(x,420),p['name'].upper(),45)
            label(d,(x,515),pct(v),147,[AMBER,TEAL][i]);d.line((x,740,x+580*fade(t,i),740),fill=[AMBER,TEAL][i],width=8)
        gap=rain_gap(snapshot,h);label(d,(780,555),'N/A' if gap is None else f'{gap:g}',87,WHITE);label(d,(730,665),'PERCENTAGE-POINT GAP',24,MUTED)
        note(d,'Derived subtraction at one common valid hour / not a statewide coverage percentage')
    elif mode=='rain-matrix':
        rain=mode=='rain-matrix';title(d,'HOW DO FORECAST CHECKPOINTS DIFFER?' if rain else 'WIND CHECKPOINTS / EIGHT LOCAL FORECASTS',
            'Precipitation chance (%) / +0 = '+stamp(snapshot['snapshots'][0]['valid_at']).strftime('%d OCT %H:%M UTC')+' / six discrete valid hours')
        for j,s in enumerate(snapshot['snapshots']):
            x=440+j*225;label(d,(x+40,374),f'+{s["hours"]}h',30,WHITE)
            for i,p in enumerate(s['points']):
                y=430+i*58;f=p['forecast'];v=f['rain_probability'] if rain else f['wind_mph'][1]
                if j==0:label(d,(80,y+12),p['name'],29)
                u=0 if v is None else min(1,v/(100 if rain else 40));color=(20+int(155*u),58+int(61*u),72+int(17*u))
                if t>.025*(j+i):
                    d.rounded_rectangle((x,y,x+205,y+49),radius=6,fill=color);label(d,(x+72,y+10),'N/A' if v is None else f'{v:g}',28)
        note(d,'Independent future-hour values from one edition / not forecast revisions or interpolated fields')
    elif mode=='wind-ranges':
        title(d,'WIND / PRESERVE THE SOURCE RANGE',valid+' / hourly grid wind, mph / not gusts')
        grid(d,570,1650,390,880,40,'')
        for i,p in enumerate(ps):
            y=402+i*59;lo,hi=p['forecast']['wind_mph'];label(d,(80,y-14),p['name'],29)
            x1=570+1080*lo/40;x2=570+1080*hi/40
            if t>.035*i:
                d.line((x1,y,x2,y),fill=TEAL,width=10)
                for x in [x1,x2]:d.ellipse((x-8,y-8,x+8,y+8),fill=TEAL)
                label(d,(1680,y-16),str(lo) if lo==hi else f'{lo}–{hi}',30,TEAL)
        note(d,'A single dot means the source gives one speed / ranges are not manufactured')
    elif mode=='forecast-timeline':
        title(d,'THE CLOCK ADVANCES / THE DATA STAYS DISCRETE','UTC valid hours / one saved forecast edition')
        for i,s in enumerate(snapshot['snapshots']):
            x=140+i*300;y=610;active=s['hours']<=h;color=TEAL if active else MUTED
            if i<5:d.line((x,y,x+300,y),fill='#35515e',width=3)
            if t>.035*i:
                d.ellipse((x-16,y-16,x+16,y+16),fill=color);label(d,(x-55,460),f'+{s["hours"]}h',49,color)
                label(d,(x-65,700),stamp(s['valid_at']).strftime('%d OCT'),26,color);label(d,(x-65,750),stamp(s['valid_at']).strftime('%H:%M'),32,color)
        note(d,'No simulated storm motion or invented minute-by-minute forecast between checkpoints')
    elif mode=='wind-ladder':
        title(d,'LOCAL WIND COMPARISON',valid+' / mph / upper end of supplied wind ranges')
        ordered=sorted(ps,key=lambda p:-p['forecast']['wind_mph'][1])
        for i,p in enumerate(ordered):
            x=130+i*215;v=p['forecast']['wind_mph'][1];bottom=810;top=bottom-v*10*fade(t,i)
            d.line((x,bottom,x,top),fill=TEAL if i>1 else AMBER,width=22);label(d,(x-27,top-65),str(v),46)
            name=p['name'].split();label(d,(x-65,850),name[0],24,MUTED)
            if len(name)>1:label(d,(x-65,888),' '.join(name[1:]),24,MUTED)
        note(d,'Hourly wind speeds / no gusts inferred / compare at the same valid hour')
    elif mode=='wind-direction':
        title(d,'LOCAL FORECAST WIND / DIRECTION MATTERS',valid+' / speeds and compass directions from the source')
        compass={'N':0,'NNE':22.5,'NE':45,'ENE':67.5,'E':90,'ESE':112.5,'SE':135,'SSE':157.5,'S':180,'SSW':202.5,'SW':225,'WSW':247.5,'W':270,'WNW':292.5,'NW':315,'NNW':337.5}
        for i,p in enumerate(ps[:4]):
            x=260+i*465;y=620;f=p['forecast'];angle=compass.get(f['wind_direction']);d.ellipse((x-105,y-105,x+105,y+105),outline='#35515e',width=3)
            label(d,(x-7,y-140),'N',27,MUTED)
            if angle is not None:
                rad=math.radians(angle);xx=x+78*math.sin(rad)*fade(t,i);yy=y-78*math.cos(rad)*fade(t,i);d.line((x,y,xx,yy),fill=AMBER,width=8);d.ellipse((xx-8,yy-8,xx+8,yy+8),fill=AMBER)
            label(d,(x-150,385),p['name'],32);label(d,(x-115,810),f'{f["wind_mph"][1]} mph / {f["wind_direction"]}',31,TEAL)
        note(d,'Compass marker indicates the direction the wind comes FROM / not storm travel')
    elif mode=='temperature-strip':
        title(d,'TEMPERATURE / EIGHT LOCAL THERMAL DIALS',valid+' / Fahrenheit / dial scale 60–95°F')
        for i,p in enumerate(ps):
            x=270+(i%4)*455;y=495+(i//4)*260;v=p['forecast']['temperature_f'];extent=270*max(0,min(1,(v-60)/35))*fade(t,i)
            box=(x-88,y-88,x+88,y+88);d.arc(box,135,405,fill='#35515e',width=17)
            if extent>0:d.arc(box,135,135+extent,fill=AMBER,width=17)
            label(d,(x-61,y-31),f'{v}°',61,WHITE);label(d,(x-150,y+115),p['name'],29,MUTED)
        note(d,'Dial colors represent supplied point values / no temperature field is interpolated')
    elif mode=='wind-checkpoints':
        title(d,'WIND THROUGH SIX FORECAST CHECKPOINTS','mph / upper end of supplied ranges / +0 = '+stamp(snapshot['snapshots'][0]['valid_at']).strftime('%d OCT %H:%M UTC'))
        selected=['pensacola','panama-city','west-palm','miami'];colors=[AMBER,PINK,TEAL,'#c8adff']
        for j,s in enumerate(snapshot['snapshots']):label(d,(490+j*225,372),f'+{s["hours"]}h',28,MUTED)
        for i,city in enumerate(selected):
            baseline=515+i*125;name=next(p['name'] for p in ps if p['id']==city);label(d,(80,baseline-35),name,34,colors[i])
            d.line((480,baseline,1660,baseline),fill='#294452',width=2)
            for j,s in enumerate(snapshot['snapshots']):
                value=next(p['forecast']['wind_mph'][1] for p in s['points'] if p['id']==city);x=530+j*225;y=baseline-value*1.8
                if t>.025*(i+j):d.line((x,baseline,x,y),fill=colors[i],width=3);d.ellipse((x-9,y-9,x+9,y+9),fill=colors[i]);label(d,(x+20,y-21),str(value),30,colors[i])
        note(d,'Separate forecast-hour markers / no continuous curve or storm travel is implied')
    elif mode=='south-cards':
        title(d,'SOUTH FLORIDA / TWO LOCAL FORECASTS',valid+' / source grid points')
        for i,city in enumerate(['miami','west-palm']):
            p=next(x for x in ps if x['id']==city);f=p['forecast'];x=110+i*950
            label(d,(x,410),p['name'].upper(),47,TEAL)
            for j,(value,name) in enumerate([(f'{f["temperature_f"]}°F','TEMPERATURE'),(pct(f['rain_probability']),'RAIN CHANCE'),(f'{f["wind_mph"][1]} mph','WIND')]):
                y=505+j*120
                if t>.06*j:label(d,(x,y),value,69,WHITE);label(d,(x+380,y+25),name,27,MUTED)
        note(d,'Three different quantities / hourly probability, temperature and wind')
    elif mode=='rain-lollipops':
        title(d,'48-HOUR RAIN CHANCE / A DIFFERENT REGIONAL PATTERN',valid+' / eight forecast points')
        grid(d,570,1650,390,880,100,'%')
        for i,p in enumerate(rain_ranking(snapshot,h)):
            y=405+i*59;v=p['forecast']['rain_probability'];label(d,(80,y-14),p['name'],29)
            if v is not None:
                x=570+1080*v/100;d.line((570,y,570+(x-570)*fade(t,i),y),fill='#638ca0',width=3)
                if t>.035*i:d.ellipse((x-11,y-11,x+11,y+11),fill=AMBER);label(d,(x+25,y-17),pct(v),29)
        note(d,'A later valid hour within the same edition / not an update from a newer forecast')
    elif mode=='temperature-heat':
        title(d,'48 HOURS / TEMPERATURE SNAPSHOT',valid+' / four pairs of Florida forecast grid points')
        for i,p in enumerate(ps):
            x=95+(i%4)*455;y=430+(i//4)*235;v=p['forecast']['temperature_f']
            if t>.03*i:
                d.rounded_rectangle((x,y,x+415,y+195),radius=15,fill=(42+int((v-60)*4),60,60));label(d,(x+25,y+20),p['name'],29);label(d,(x+25,y+78),f'{v}°F',70)
        note(d,'Color shows the displayed point temperature / not a gridded regional heat field')
    elif mode=='rain-dots':
        title(d,'72 HOURS / SMALLER CHANCES AT THESE EIGHT POINTS',valid+' / hourly precipitation probabilities')
        for i,p in enumerate(ps):
            x=120+(i%4)*460;y=440+(i//4)*215;v=p['forecast']['rain_probability'];label(d,(x,y),p['name'],29,MUTED)
            if t>.03*i:label(d,(x,y+60),pct(v),82,TEAL)
        note(d,'0% is a source value, not a promise of safe conditions / warnings answer another question')
    elif mode=='takeaways':
        title(d,'THREE QUESTIONS BEFORE YOU ACT','Use current official warnings and local guidance')
        for i,(head,body) in enumerate([('WHERE?','Your location and warning area'),('WHEN?','The forecast valid hour'),('WHICH THREAT?','Wind, surge, rain or flooding')]):
            y=430+i*150
            if t>.09*i:label(d,(100,y),f'{i+1:02}',70,TEAL);label(d,(270,y+8),head,48);label(d,(820,y+20),body,35,MUTED)
        note(d,'This is a recorded edition / check the latest bulletin before acting')
    elif mode=='source-clock':
        title(d,'SOURCE TIMES / KEEP THE EDITION ATTACHED','These timestamps refer to different source products')
        rows=[('NHC FULL ADVISORY MAP',storm['geometry']['issued_at']),('NHC PUBLIC BULLETIN',storm['latest']['issued_at']),('COLLECTION SNAPSHOT',snapshot['collected_at'])]
        for i,(name,value) in enumerate(rows):
            y=460+i*150
            if t>.09*i:label(d,(100,y),name,31,MUTED);label(d,(900,y-10),stamp(value).strftime('%d OCT / %H:%M UTC'),45,TEAL)
        note(d,'Rendering again does not make the original forecasts current')
    else:raise ValueError('Unknown statistical treatment: '+mode)
    return im
