"""Local, evidence-linked editorial story drafts; no models or invented forecasts."""
from copy import deepcopy
from uuid import uuid4


def build(plan, advisory):
    result = deepcopy(plan)
    result.update(id=str(uuid4()), parent_plan_id=plan['id'], story_version=1,
                  story_review_required=True, review_valid_at_creation=False,
                  story_note='Editorial preview: review this rewritten script against its source claims before publishing. No forecast paths or impacts are invented.')
    scenes = result['scenes']
    # Open with the source comparison, retaining every original claim exactly once.
    comparison = next((i for i,s in enumerate(scenes) if s['type']=='what_changed'), None)
    if comparison is not None:
        scenes.insert(0, scenes.pop(comparison))
    facts = advisory.facts
    for index, scene in enumerate(scenes):
        original = scene['script_segment']
        text = original
        beat, headline = 'context', 'THE SOURCE RECORD'
        if scene['type']=='what_changed':
            numeric = [c for c in scene['parameters'].get('changes',[]) if c['field'] in ('pressure_mb','wind_mph') and isinstance(c.get('previous'),(int,float)) and isinstance(c.get('current'),(int,float))]
            if numeric:
                c = next((c for c in numeric if c['field']=='pressure_mb'),numeric[0])
                name, unit = ('Central pressure','mb') if c['field']=='pressure_mb' else ('Sustained wind','mph')
                verb = 'fell' if c['current'] < c['previous'] else 'rose' if c['current'] > c['previous'] else 'held steady'
                text = f"{name} {verb}: {c['previous']} → {c['current']} {unit}. What else does the source report?"
                headline = 'ONE CHANGE. THE BIGGER PICTURE.'
            else:
                text = 'The source comparison is ready. Which reported details changed?'
                headline = 'WHAT CHANGED?'
            beat = 'hook'
        elif scene['type']=='news_intro':
            text = f"{advisory.title}. Source issued {advisory.issued_at.strftime('%d %b %Y, %H:%M UTC')}. Source status: {plan['source_label']}. This is a prerecorded source review."
            beat, headline = 'context', 'HERE IS THE CONTEXT'
        elif scene['type'] in ('storm_track','cinematic_weather_map') and 'latitude' in original.lower() and 'Official forecast guidance' not in original:
            text = f"Reported center: {facts.get('latitude')}°, {facts.get('longitude')}°. Sustained wind: {facts.get('wind_mph')} mph. These are reported positions, not a predicted path."
            beat, headline = 'evidence', 'WHERE THE SOURCE PLACES IT'
        elif 'Official watch and warning coverage:' in original:
            # Keep named geography available in the original claim and subtitle source manifest.
            area = advisory.warnings[0].strip() if advisory.warnings else 'See the complete advisory.'
            text = f'The source lists: {area}. Prerecorded coverage; check the current official warning.'
            beat, headline = 'stakes', 'CHECK THE NAMED WARNING AREAS'
        elif 'Official forecast guidance' in original or 'Forecast guidance was not extracted' in original:
            import re
            sentences = re.split(r'(?<=[.!?]) +',' '.join(advisory.forecast_excerpt.split())) if advisory.forecast_excerpt else []
            prediction = next((s for s in sentences if 'expected' in s.lower()),None)
            text = f'What was forecast? {prediction} This was the source forecast at issue time; check the latest advisory.' if prediction and len(prediction)<220 else 'What was forecast? Read the complete official forecast. Its issue time matters; this video adds no prediction.'
            beat, headline = 'question', 'WHAT DOES THE FORECAST SAY?'
        elif index == len(scenes)-1:
            text = 'The takeaway: compare the measurements, location and warning coverage together. Watch the next official advisory for changes. Follow official local guidance.'
            beat, headline = 'payoff', 'WHAT TO WATCH NEXT'
        elif 'was issued on' in original:
            text = f"The source is {advisory.provider}, issued {advisory.issued_at.strftime('%d %b %Y at %H:%M UTC')}. Check the full advisory for the complete storm context."
            beat, headline = 'reveal', 'CHECK THE TIME AND SOURCE'
        scene.update(source_claim_text=original, script_segment=text, story_beat=beat,
                     story_headline=headline, target_seconds=max(3,round(len(text.split())/145*60,1)))
        scene['parameters']['story']={'source_label':plan['source_label'],'beat':beat,'headline':headline,'text':text,
                                     'position':index+1,'total':len(scenes)}
        from .regional import named_regions
        scene['regional_targets'] = named_regions(text)
        scene['visual_instructions'] = f'{headline}: show concise story captions, source-linked graphics and contextual footage. Preserve timestamps and uncertainty.'
    result['story_script']='\n\n'.join(s['script_segment'] for s in scenes)
    result['estimated_seconds']=sum(s['target_seconds'] for s in scenes)
    return result
