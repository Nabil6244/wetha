"""Local preview audit. Evidence matching never grants human or broadcast approval."""
import re
from .polished import terms

WORDS = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety'.split(), list(range(20))+list(range(20,100,10))))

def canonical(text):
    text = text.lower().replace('’', "'").replace('–','-')
    text = re.sub(r'\b(miles per hour|mph)\b', 'mph', text)
    text = re.sub(r'\bnautical miles?\b', 'nm', text)
    text = re.sub(r'\bfeet\b','ft',text)
    text = re.sub(r'\binches\b','in',text)
    text = re.sub(r'\b('+'|'.join(WORDS)+r')\b',lambda m:str(WORDS[m[0]]),text)
    text = re.sub(r'\b([2-9]0)[ -]([1-9])\b',lambda m:str(int(m[1])+int(m[2])),text)
    return re.sub(r'\s+',' ',text)

def numeric_tokens(text):
    return set(re.findall(r'(?<!\w)\d+(?:\.\d+)?',canonical(text)))

def audit(document, evidence):
    selected = set(document.get('selected_advisory_ids', [document['advisory_id']]))
    sources = [a for a in evidence if a.id in selected]
    # Externally refined bulletins often use fewer stories than the raw source pack.
    # Prefer preserved reports whose distinctive affected places occur in the narration.
    generic={'coastal','waters','county','counties','sound','beach','out','portions','parts','north','south','east','west','gulf','florida','alabama','georgia','mississippi'}
    spoken_places=terms(document.get('text',' '.join(c['text'] for c in document.get('claims',[]))))
    mentioned=[a for a in sources if (terms(a.area)-generic)&spoken_places]
    if mentioned:sources=mentioned
    rows=[]; context=None
    chapter_words={a.id:terms(a.area.replace(", AL", " Alabama").replace(" GA", " Georgia").replace(" FL", " Florida")) for a in sources}
    for index,claim in enumerate(document.get('claims', [])):
        text=claim['text']; wanted=terms(text)
        ranked=[]
        for a in sources:
            area=chapter_words[a.id]; content=terms(a.text+' '+a.title+' '+a.area)
            score=len(wanted&content)/max(1,len(wanted))
            # Named affected places establish a chapter; continue it through short connective beats.
            anchors=wanted&(area-{'coastal','waters','county','counties','sound','beach','out','portions','parts','north','south','east','west','florida','georgia','alabama','mississippi'})
            if anchors:score+=min(2,len(anchors)*.8)
            score += min(.9,len(anchors)*.3)
            if any(state in wanted and state in area for state in ('alabama','florida','georgia','mississippi')):score+=.65
            if a.id==context:score+=.35 if not numeric_tokens(text) else .12
            if any(w in text.lower() for w in ('move into','head offshore')) and index+1<len(document['claims']):
                score+=len(terms(document['claims'][index+1]['text'])&content)/max(1,len(terms(document['claims'][index+1]['text'])))
            ranked.append((score,a))
        ranked.sort(key=lambda pair:-pair[0])
        best=ranked[0][1] if ranked else None
        if context and not any(wanted&(chapter_words[a.id]-{'coastal','waters','county','counties','sound','beach','out','portions','parts','north','south','east','west','florida','georgia','alabama','mississippi'}) for a in sources) and not wanted&{'alabama','florida','georgia','mississippi'} and not any(w in text.lower() for w in ('move into','head offshore')):
            best=next(a for a in sources if a.id==context)
        if best and (wanted&(chapter_words[best.id]-{'coastal','waters','county','counties','sound','beach','out','portions','parts','north','south','east','west'}) or any(w in text.lower() for w in ('move into','head offshore'))):context=best.id
        identities=[best.id] if best else []
        multi=sum(bool(wanted&chapter_words[a.id]) for a in sources)>1 and any(w in text.lower() for w in ('across','along','offshore','reports','bulletin'))
        if multi:identities=[a.id for _,a in ranked if wanted&chapter_words[a.id]]
        matching=[a for a in sources if a.id in identities]
        combined=' '.join(a.text+' '+a.issued_at.isoformat() for a in matching)
        unsupported=sorted(numeric_tokens(text)-numeric_tokens(combined))
        # A date contextualising the package is not a weather measurement.
        if re.search(r'\b(expired|dated|not current)\b',text.lower()):
            unsupported=[n for n in unsupported if n not in numeric_tokens(' '.join(a.issued_at.isoformat() for a in sources))]
        conflicts=[]
        for low,high,unit in re.findall(r'(\d+)\s*(?:to|-)\s*(\d+)\s*(mph|knots|ft|in|mb|nm)\b',canonical(text)):
            if not any(re.search(r'\b'+low+r'\s*(?:to|and|-)\s*'+high+r'\s*'+unit+r'\b',canonical(a.text)) for a in matching):
                conflicts.append(f'{low}–{high} {unit}')
        for value,unit in re.findall(r'(\d+(?:\.\d+)?)\s*(mph|knots|ft|in|mb|nm)\b',canonical(text)):
            if not any(re.search(r'\b'+re.escape(value)+r'\s*'+unit+r'\b',canonical(a.text)) for a in matching):
                conflicts.append(f'{value} {unit}')
        if re.search(r'\b(guaranteed|certain to|definitely will)\b',text.lower()):conflicts.append('Forecast certainty is not supported by source wording')
        blocked=bool(unsupported or conflicts or not sources)
        editorial=not numeric_tokens(text) and (len(wanted)<7 or text.lower().startswith(('subscribe','for current conditions','once again','before we get')))
        quotes=[]
        for a in matching:
            chunks=re.split(r'\n\s*\n',a.text)
            chunks.sort(key=lambda q:-len(wanted&terms(q)))
            quotes.append({'advisory_id':a.id,'checksum':a.checksum,'quote':chunks[0].strip() if chunks else a.text})
        rows.append({'claim_id':claim['id'],'source_advisory_ids':identities,'primary_advisory_id':best.id if best else None,
                     'status':'needs_attention' if blocked else 'editorial' if editorial else 'source_matched',
                     'unsupported_numbers':unsupported,'conflicts':conflicts,'evidence':quotes,
                     'note':'Automatic source/number/unit matching; wording and implications have not received semantic or human verification.'})
    return {'ready':bool(rows) and all(r['status']!='needs_attention' for r in rows),'claims':rows,
            'mode':'local_preview_only','human_review_required':True,
            'note':'Checks preserved evidence and numerical presence. Source matching is not proof of meaning. Local preview only; broadcast approval is unchanged.'}
