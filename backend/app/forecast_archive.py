"""Bounded reader for official NHC archived geographic-degree SHP/DBF bundles."""
import io,math,re,struct,zipfile
from datetime import datetime,timedelta,timezone


def local_stamp(value,format):
    """Honor the timezone actually printed on NHC's geographic product."""
    zones={'AST':-4,'EDT':-4,'EST':-5,'CDT':-5,'CST':-6,'MDT':-6,'MST':-7,'PDT':-7,'PST':-8}
    matches=list(re.finditer(r'\b(AST|EDT|EST|CDT|CST|MDT|MST|PDT|PST)\b',value))
    if len(matches)!=1:raise ValueError('Forecast timestamp needs one explicit timezone.')
    match=matches[0];clean=' '.join((value[:match.start()]+value[match.end():]).split())
    return datetime.strptime(clean,format).replace(tzinfo=timezone(timedelta(hours=zones[match.group()])))


def dbf(raw):
    if len(raw)<33:raise ValueError('Truncated DBF')
    count,header,size=struct.unpack_from('<IHH',raw,4)
    if count>10000 or header<33 or size<1 or header>len(raw) or header+count*size>len(raw):raise ValueError('Invalid DBF limits')
    fields=[];offset=32
    while offset+32<=header and raw[offset]!=13:
        fields.append((raw[offset:offset+11].split(b'\0')[0].decode('ascii'),raw[offset+16]));offset+=32
    rows=[]
    for i in range(count):
        record=raw[header+i*size:header+(i+1)*size]
        if record[0]!=32:raise ValueError('Deleted DBF records are unsupported')
        pos=1;row={}
        for name,length in fields:row[name]=record[pos:pos+length].decode('ascii').strip();pos+=length
        if pos!=size:raise ValueError('DBF field sizes do not match')
        rows.append(row)
    return rows


def shp(raw):
    if len(raw)<100 or struct.unpack_from('>i',raw)[0]!=9994 or struct.unpack_from('>i',raw,24)[0]*2!=len(raw):raise ValueError('Invalid SHP header')
    result=[];offset=100;points_total=0
    def coordinate(x,y):
        if not math.isfinite(x+y) or not -180<=x<=180 or not -85<=y<=85:raise ValueError('Invalid geographic-degree coordinate')
        return [x,y]
    while offset<len(raw):
        if offset+8>len(raw):raise ValueError('Truncated SHP record header')
        length=struct.unpack_from('>i',raw,offset+4)[0]*2;offset+=8
        if length<4 or offset+length>len(raw):raise ValueError('Invalid SHP record length')
        b=raw[offset:offset+length];offset+=length
        if len(b)!=length:raise ValueError('Truncated SHP record')
        typ=struct.unpack_from('<i',b)[0]
        if typ==1:
            if len(b)!=20:raise ValueError('Invalid SHP point record')
            result.append({'type':'Point','coordinates':coordinate(*struct.unpack_from('<dd',b,4))});continue
        if typ not in (3,5):raise ValueError('Unsupported SHP geometry')
        if len(b)<44:raise ValueError('Truncated SHP parts record')
        parts,count=struct.unpack_from('<ii',b,36)
        if not 1<=parts<=10000 or not 1<=count<=100000 or len(b)!=44+parts*4+count*16:raise ValueError('Invalid SHP parts')
        starts=list(struct.unpack_from('<'+'i'*parts,b,44))+[count]
        if starts[0]!=0 or any(a>=c for a,c in zip(starts,starts[1:])):raise ValueError('Invalid SHP offsets')
        points=[coordinate(*struct.unpack_from('<dd',b,44+parts*4+i*16)) for i in range(count)]
        points_total+=count
        if points_total>200000:raise ValueError('SHP point limit')
        rings=[points[a:c] for a,c in zip(starts,starts[1:])]
        if typ==5 and any(len(r)<4 or r[0]!=r[-1] for r in rings):raise ValueError('Unclosed cone ring')
        result.append({'type':'Polygon' if typ==5 else 'MultiLineString','coordinates':rings})
    return result


def parse(raw,advisory):
    if len(raw)>32000000:raise ValueError('Archive too large')
    number=str(advisory.facts['advisory_number']);prefix=f'{advisory.event_key.lower()}-{int(number):03}'
    features=[];future=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.infolist())>50 or sum(f.file_size for f in z.infolist())>32000000:raise ValueError('Archive expansion limit')
        for suffix,kind in [('5day_pgn','forecast_cone'),('5day_pts','forecast_point'),('ww_wwlin','warning_coast')]:
            base=prefix+'_'+suffix
            projection=z.read(base+'.prj').decode()
            if 'GEOGCS' not in projection or 'UNIT["Degree"' not in projection or not ('WGS' in projection or 'GCS_Sphere' in projection):raise ValueError('Unsupported archive geographic projection')
            rows=dbf(z.read(base+'.dbf'));geometry=shp(z.read(base+'.shp'))
            if len(rows)!=len(geometry):raise ValueError('SHP/DBF mismatch')
            for row,g in zip(rows,geometry):
                if row['ADVISNUM']!=number or row['BASIN']!=advisory.event_key[:2] or int(float(row['STORMNUM']))!=int(advisory.event_key[2:4]):raise ValueError('Unrelated forecast archive')
                stamp=local_stamp(row['ADVDATE'],'%I%M %p %a %b %d %Y').astimezone(timezone.utc)
                if stamp!=advisory.issued_at:raise ValueError('Forecast issue time does not match')
                properties={**row,'kind':kind,'issued_at':stamp.isoformat()}
                if kind=='forecast_point':
                    local=local_stamp(row['FLDATELBL'],'%Y-%m-%d %I:%M %p %a')
                    valid=local.astimezone(timezone.utc);properties['valid_time']=valid.isoformat()
                    if valid<=advisory.issued_at:continue
                    future.append(valid)
                features.append({'type':'Feature','properties':properties,'geometry':g})
    if not future:raise ValueError('No explicit future valid times')
    return {'type':'FeatureCollection','features':features,'issued_at':advisory.issued_at.isoformat(),'valid_until':max(future).isoformat()}
