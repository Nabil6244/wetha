"""Source-named coastal labels from official NOAA breakpoint coordinates."""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def catalogue():
    return json.loads((Path(__file__).parent/'data/coastal-places.json').read_text())

def apply(parameters, advisory, text):
    mentioned = text + '\n' + '\n'.join(advisory.warnings)
    places = [(p['name'],p['coordinates']) for p in catalogue()['places'] if p['name'].casefold() in mentioned.casefold()]
    if places:
        parameters.setdefault('places',places)
        parameters['place_source_url'] = catalogue()['source_url']
    # A context viewport includes the named coast; it makes no forecast boundary.
    lat,lon=advisory.facts.get('latitude'),advisory.facts.get('longitude')
    if isinstance(lat,(int,float)) and isinstance(lon,(int,float)) and 16<=lat<=31 and -98<=lon<=-82 and places:
        parameters.setdefault('bounds',[-98,16,-78,33])
    parameters['location_label'] = advisory.area or advisory.title
    return parameters


def locator(parameters):
    """Small separately projected locator; never pin coordinates on native satellite pixels."""
    from PIL import Image,ImageDraw
    from .broadcast import map_base,map_point,font
    places=parameters.get('places',[])[:4]
    if not places:return None
    bounds=tuple(parameters.get('bounds',[-98,16,-78,33]))
    image=Image.new('RGBA',(600,340),'#071c29');d=ImageDraw.Draw(image)
    image.paste(map_base(bounds).resize((330,300)),(10,30))
    d.text((15,7),'LOCATION CONTEXT / SEPARATE MAP',font=font(17),fill='#82efdc')
    for i,(name,coord) in enumerate(places):
        x,y=map_point(coord,bounds,size=(330,300));x+=10;y+=30
        if not 10<=x<=340 or not 30<=y<=330:continue
        d.ellipse((x-9,y-9,x+9,y+9),fill='#ffd089')
        tag=chr(65+i);d.text((x+12,y-10),tag,font=font(18),fill='white')
        import textwrap
        for j,line in enumerate(textwrap.wrap(tag+'  '+name,23)):
            d.text((355,43+i*69+j*21),line,font=font(18),fill='#ffd089')
    return image
