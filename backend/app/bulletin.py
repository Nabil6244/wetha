"""Local multi-story narration with neutral, source-linked chapter transitions."""
import copy
from .editorial import claim_id, rebuild_scenes, normalized


def assemble(document, parts, advisories, target_minutes):
    result = copy.deepcopy(document)
    result['claims'] = []
    result['grounded_scenes'] = []
    seen = {}
    sections = []

    def add(claim, template):
        key = claim['text']
        if key in seen:
            seen[key]['source_advisory_ids'] = list(dict.fromkeys(seen[key]['source_advisory_ids'] + claim['source_advisory_ids']))
            return
        saved = copy.deepcopy(claim)
        seen[key] = saved
        result['claims'].append(saved)
        scene = copy.deepcopy(template)
        scene['script_segment'] = saved['text']
        scene['parameters']['source_advisory_id'] = saved['primary_advisory_id']
        result['grounded_scenes'].append(scene)

    def transition(text, item, template):
        add({'id':claim_id(text),'text':text,'status':'generated_grounded','support':None,
             'source_advisory_ids':[item.id],'primary_advisory_id':item.id,'editorial_transition':True},template)

    opening = parts[0]['claims'][0]
    add(opening, parts[0]['grounded_scenes'][0])
    transition('In this weather bulletin, we will review the selected reports in order, including their source times, reported conditions, and official guidance.', advisories[0], parts[0]['grounded_scenes'][0])
    for index, (part, item) in enumerate(zip(parts, advisories)):
        template = part['grounded_scenes'][0]
        start = len(result['claims'])
        prefix = 'We begin with' if index == 0 else 'Next, we turn to' if index < len(parts)-1 else 'Our final report covers'
        region = f" The affected area listed by the source is {item.area}." if item.area else ''
        transition(f'{prefix} {item.title}.{region}', item, template)
        # Retain different per-source restrictions, but repeat neither identical
        # safety warnings nor generic closings between stories.
        # A source scene can contain multiple paragraphs (notably NWS alerts
        # and NHC forecast excerpts). Claims track paragraphs, not scene indexes.
        templates = {normalized(paragraph): scene
                     for scene in part['grounded_scenes']
                     for paragraph in scene['script_segment'].split('\n\n') if paragraph.strip()}
        for n, claim in enumerate(part['claims']):
            if n == len(part['claims'])-1:
                continue
            source_scene = templates.get(normalized(claim['text']))
            if source_scene is None:
                raise ValueError('A bulletin paragraph is missing its source-linked scene. Rebuild the source draft.')
            add(claim, source_scene)
        sections.append({'advisory_id':item.id,'title':item.title,'area':item.area,
                         'claim_ids':[c['id'] for c in result['claims'][start:]]})
    transition('That completes this weather bulletin. Follow official local guidance and recheck the latest advisories before broadcast.', advisories[-1], parts[-1]['grounded_scenes'][-1])
    result['title'] = f'Weather bulletin · {len(parts)} stories'
    result['selected_advisory_ids'] = [a.id for a in advisories]
    result['chapters'] = sections
    result['text'] = '\n\n'.join(c['text'] for c in result['claims'])
    rebuild_scenes(result)
    target = target_minutes * 60
    words = len(result['text'].split())
    result['bulletin'] = {'target_minutes':target_minutes,'word_count':words,
        'estimated_seconds':result['estimated_seconds'],'target_words':target_minutes*145,
        'remaining_words':max(0,target_minutes*145-words),
        'coverage':'enough_material' if result['estimated_seconds'] >= target*.9 else 'needs_more_material',
        'note':'Length is an estimate at 145 words/minute. Short sources are not repeated or padded; uploaded audio determines final timing.'}
    return result
