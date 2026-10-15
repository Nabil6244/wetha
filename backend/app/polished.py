"""Reviewable source mapping for externally written narration."""
import copy
import re
from .editorial import edited, normalized

STOP = set('the a an and or of to in is it for with on at from this that as by be are was were will'.split())
def terms(text):
    return set(re.findall(r'[a-z]{3,}', text.lower())) - STOP


def source_pack(document, evidence):
    selected = document.get('selected_advisory_ids', [document['advisory_id']])
    rows = [{'id':a.id, 'title':a.title, 'area':a.area, 'issued_at':a.issued_at.isoformat(),
             'url':a.source_url, 'checksum':a.checksum, 'text':a.text} for a in evidence if a.id in selected]
    text = '\n\n'.join(f"STORY {i+1}: {a['title']}\nSOURCE ID: {a['id']}\nAREA: {a['area']}\nISSUED: {a['issued_at']}\nSOURCE: {a['url']}\n\n{a['text']}" for i,a in enumerate(rows))
    return {'sources':rows, 'text':text, 'instruction':'Rewrite for spoken narration. Keep locations, values, issue times and forecast uncertainty tied to their source. Separate paragraphs by story; do not invent facts or pad duration.'}


def suggest(text, evidence):
    result=[]
    for paragraph in re.split(r'\n\s*\n',text.strip()):
        if not paragraph.strip():continue
        wanted=terms(paragraph)
        candidates=[]
        for a in evidence:
            shared=wanted & terms(a.title+' '+a.area+' '+a.text)
            # Lexical suggestion only. Never upgrades an edited claim's support status.
            score=len(shared)/max(1,len(wanted))
            candidates.append({'advisory_id':a.id,'score':round(score,3)})
        candidates.sort(key=lambda c:-c['score'])
        result.append({'text':paragraph.strip(),'candidates':candidates[:3],
                       'advisory_id':candidates[0]['advisory_id'] if candidates and candidates[0]['score']>=.25 else ''})
    return {'paragraphs':result,'note':'Suggested sources are word matches. Review meaning, numbers, locations and forecast qualifiers against the source.'}


def save(document, body, evidence):
    # Unchanged text may still be saved once, to mark a generated bulletin as the final narration.
    result=edited(document,body.text,evidence,allow_same=not document.get('polished_narration'))
    identities=body.sources
    if not identities:
        from .preview_audit import audit
        identities=[row['primary_advisory_id'] for row in audit(result,evidence)['claims']]
    if len(identities)!=len(result['claims']):raise ValueError('Choose a source for every paragraph, in narration order.')
    by_id={a.id:a for a in evidence}
    for claim,identity in zip(result['claims'],identities):
        if identity not in by_id:raise ValueError('Choose a preserved source for every paragraph.')
        # Changed mappings invalidate prior attestations, including exact unchanged text.
        if identity not in claim['source_advisory_ids']:
            claim.update(status='requires_verification',support=None)
        claim.update(source_advisory_ids=[identity],primary_advisory_id=identity)
        if normalized(claim['text']) in normalized(by_id[identity].text):
            claim.update(status='source_quote',support=None)
    result['polished_narration']=True
    # Keep the original source pack and evidence immutable; templates remain source-linked.
    from .editorial import rebuild_scenes
    rebuild_scenes(result)
    return result
