"""Continuous documentary composition: moving imagery, geography and overlays."""
import asyncio,copy,math,textwrap
from PIL import Image,ImageDraw,ImageOps
from .broadcast import Composer,SIZE,easing,label,map_base,map_point,project,fit_bounds,encoder_args


def viewport(start,end,t):
    """Interpolate the camera in projected space, keeping a consistent aspect."""
    a=fit_bounds(tuple(start));b=fit_bounds(tuple(end));u=easing(t)
    corners=[]
    for lon_a,lat_a,lon_b,lat_b in [(a[0],a[3],b[0],b[3]),(a[2],a[1],b[2],b[1])]:
        x0,y0=project(lon_a,lat_a);x1,y1=project(lon_b,lat_b)
        x=x0+(x1-x0)*u;y=y0+(y1-y0)*u
        corners.append((x*360-180,math.degrees(math.atan(math.sinh(math.pi*(1-2*y))))))
    return (corners[0][0],corners[1][1],corners[1][0],corners[0][1])


def overlay(image,row,t):
    """Brief overlays stay on live visuals; there are no full-screen text cards."""
    wash=Image.new('RGBA',SIZE);d=ImageDraw.Draw(wash)
    for y in range(0,230,4):d.rectangle((0,y,1920,y+3),fill=(3,14,23,round(175*(1-y/230))))
    for y in range(980,1080,4):d.rectangle((0,y,1920,y+3),fill=(3,14,23,round(160*(y-980)/100)))
    if row.get('stat'):
        # Feathered shading keeps measurements readable over bright live footage.
        for x in range(0,900,20):
            for y in range(600,970,10):
                edge=max(0,min(1,(y-600)/65,(970-y)/65))
                d.rectangle((x,y,x+19,y+9),fill=(3,14,23,round(205*(1-x/900)*edge)))
    image=Image.alpha_composite(image.convert('RGBA'),wash).convert('RGB');d=ImageDraw.Draw(image)
    label(d,(55,35),row.get('header','ISAIAS / AUGUST 2020'),24,'#ffffff')
    label(d,(1230,35),row['context'],24,'#ffffff')
    x=55 if row.get('static_title') else 55+round(35*(1-easing(min(1,t*3))))
    lines=textwrap.wrap(row['text'],width=51)
    if len(lines)>2:raise ValueError('Documentary caption exceeds two lines.')
    for i,line in enumerate(lines):
        d.text((x,108+i*50),line,font=__import__('app.broadcast',fromlist=['font']).font(41),fill='#ffffff',stroke_width=2,stroke_fill='#081d2c')
    stat=row.get('stat')
    if stat:
        label(d,(65,690),stat['label'],26,'#82efdc')
        value=stat['value'];label(d,(60,735),value,100)
        label(d,(65,862),stat['detail'],25,'#ffffff')
        d.line((65,912,65+660*easing(min(1,t*2)),912),fill='#82efdc',width=5)
    # Exact shot source and context are always visible, without a boxed footer.
    label(d,(55,1032),row['credit'][:140],23,'#ffffff')
    return image


class DocumentaryComposer(Composer):
    def __init__(self,row,load_asset):
        self.row=copy.deepcopy(row)
        super().__init__(row['direction'],copy.deepcopy(row['parameters']),load_asset)
        frame_range=row.get('frame_range')
        if frame_range:
            a,b=frame_range
            if not 0<=a<b<=len(self.sources):raise ValueError('Invalid genuine observation frame range.')
            self.sources=self.sources[a:b]

    def frame(self,t):
        row=self.row;p=self.parameters
        if self.sources:
            src=self.sources[min(len(self.sources)-1,int(t*len(self.sources)))]
            main=src.crop(tuple(p['native_crop'])) if p.get('native_crop') else src
            # Camera movement is presentation only; original observation pixels
            # remain in order, and legends/UTC strips are pasted separately.
            z=1.025+.035*easing(t);main=ImageOps.fit(main,SIZE)
            w,h=1920/z,1080/z;cx=960+14*math.sin(math.pi*t);cy=540-10*math.sin(math.pi*t)
            image=main.crop((int(cx-w/2),int(cy-h/2),int(cx+w/2),int(cy+h/2))).resize(SIZE,Image.Resampling.BILINEAR)
            strip=ImageOps.contain(src.crop(tuple(p['source_strip'])),tuple(p['strip_size']))
            image.paste(strip,(1920-strip.width-40,1000-strip.height))
        else:
            bounds=viewport(row['camera_start'],row['camera_end'],t)
            image=map_base(bounds).copy();layer=Image.new('RGBA',SIZE);d=ImageDraw.Draw(layer)
            mode=row['map_kind']
            features=p.get('geojson',{}).get('features',[])
            if mode=='track':
                pts=[map_point(r['coordinates'],bounds) for r in p['records']]
                count=max(1,math.ceil(len(pts)*min(1,t*1.8)))
                if count>1:d.line(pts[:count],fill='#82efdc',width=6)
                for record,(x,y) in zip(p['records'][:count],pts[:count]):
                    d.ellipse((x-9,y-9,x+9,y+9),fill='#ffffff')
                    stamp=record['issued_at'];label(d,(x+16,y+8),stamp[8:10]+' AUG '+stamp[11:16]+' UTC',25)
                for name,coord in [('CHARLESTON',(-79.93,32.78)),('WILMINGTON',(-77.95,34.23)),('RALEIGH',(-78.64,35.78))]:
                    x,y=map_point(coord,bounds);label(d,(x+12,y),name,27,'#b6d2dc')
            elif mode=='warnings':
                colors={'HWR':'#ff6375','TWR':'#ffb06c','TWA':'#ffe388','HWA':'#ffe388'}
                for f in features:
                    if f['properties']['kind']!='warning_coast':continue
                    for line in f['geometry']['coordinates']:
                        pts=[map_point(c,bounds) for c in line]
                        count=max(2,math.ceil(len(pts)*easing(min(1,t*1.8))))
                        d.line(pts[:count],fill=colors[f['properties']['TCWW']],width=8)
                for i,(name,color) in enumerate([('Hurricane warning','#ff6375'),('Tropical storm warning','#ffb06c'),('Watch','#ffe388')]):
                    label(d,(60,730+i*45),name,29,color)
                label(d,(60,935),'ISSUED 04 AUG 2020 / 03 UTC',25)
            elif mode=='forecast':
                for f in features:
                    if f['properties']['kind']=='forecast_cone':
                        for ring in f['geometry']['coordinates']:
                            points=[map_point(c,bounds) for c in ring]
                            d.polygon(points,fill=(174,125,238,60));d.line(points,fill='#dcc4ff',width=3)
                predicted=sorted([f for f in features if f['properties']['kind']=='forecast_point'],key=lambda f:f['properties']['valid_time'])
                predicted=predicted[:max(1,math.ceil(len(predicted)*min(1,t*1.7)))]
                pts=[map_point(f['geometry']['coordinates'],bounds) for f in predicted]
                if len(pts)>1:d.line(pts,fill='#dcc4ff',width=5)
                for f,(x,y) in zip(predicted,pts):
                    d.ellipse((x-8,y-8,x+8,y+8),fill='#ffffff')
                    stamp=f['properties']['valid_time'];label(d,(x+16,y),stamp[8:10]+' AUG '+stamp[11:16]+' UTC',23)
                label(d,(60,860),'Forecast center positions / not the full impact area',28,'#dcc4ff')
                label(d,(60,925),'ISSUED 04 AUG 2020 / 03 UTC',25)
            else:raise ValueError('Unknown documentary map mode.')
            # Geographic features outside the camera are clipped before captions.
            alpha=layer.getchannel('A');mask=Image.new('L',SIZE);mask.paste(alpha.crop((0,235,1920,985)),(0,235));layer.putalpha(mask)
            image=Image.alpha_composite(image.convert('RGBA'),layer).convert('RGB')
        return overlay(image,row,t)


async def render(row,output,load_asset,footage_path=None,composer=None):
    count=round(row['seconds']*30);decoder=None
    composer=None if footage_path else (composer or DocumentaryComposer(row,load_asset))
    with output.with_suffix('.log').open('wb') as errors:
        if footage_path:
            decoder=await asyncio.create_subprocess_exec('ffmpeg','-v','error','-ss',str(row['trim_start']),'-i',str(footage_path),'-vf',
                'scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,setsar=1',
                '-frames:v',str(count),'-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1',stdout=asyncio.subprocess.PIPE,stderr=errors)
        encoder=await asyncio.create_subprocess_exec('ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0',
            '-frames:v',str(count),'-an',*encoder_args(),'-pix_fmt','yuv420p','-threads','2',str(output),stdin=asyncio.subprocess.PIPE,stderr=errors)
        try:
            for i in range(count):
                t=i/max(1,count-1)
                if decoder:
                    raw=await decoder.stdout.readexactly(1920*1080*3)
                    frame=await asyncio.to_thread(overlay,Image.frombytes('RGB',SIZE,raw),row,t)
                else:frame=await asyncio.to_thread(composer.frame,t)
                encoder.stdin.write(frame.tobytes());await encoder.stdin.drain()
            encoder.stdin.close();await asyncio.wait_for(encoder.wait(),120)
            if decoder:await asyncio.wait_for(decoder.wait(),30)
            if encoder.returncode or (decoder and decoder.returncode):raise ValueError('Documentary encoding failed; inspect shot log.')
        finally:
            for process in (encoder,decoder):
                if process and process.returncode is None:
                    process.terminate()
                    try:await asyncio.wait_for(process.wait(),5)
                    except asyncio.TimeoutError:process.kill();await process.wait()
