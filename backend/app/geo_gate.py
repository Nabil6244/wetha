"""Geographic gate for placing library footage into a story.

One rule for every path that can put a clip into a video (automatic edits, template edits, manual timelines
and the pre-render check):

* conflict: the clip's own metadata names a non-US place or a vehicle not found on US streets, and the story
  is a US story -> never placed, whatever its relevance, even after review.
* possible conflict: a people-and-street beat, a clip whose metadata describes a dense urban street scene and
  whose location is unknown -> not placed until a reviewer clears the setting.
* story region unknown but the clip names a foreign place -> not placed until cleared (the existing protection).
* everything else, including location-neutral waves, rain, clouds and palms -> unchanged.

Evidence comes only from metadata the provider or editor wrote (file name, source page slug, catalogue tags
and location). Never from ethnicity, skin colour, architecture or stereotypes. Media is never modified.
"""
import re
from urllib.parse import urlsplit, unquote
from . import visual_concepts as vc


def story_region(advisory):
    return 'US' if getattr(advisory, 'provider', None) in ('NWS', 'NHC') else None


def metadata_text(asset):
    """Words the provider or editor attached to the clip: name, source page slug, catalogue tags and location."""
    catalog = asset.get('catalog', {})
    source = asset.get('source', '') or ''
    slug = ''
    try:
        path = unquote(urlsplit(source).path)
        slug = re.sub(r'[-_/]+', ' ', re.sub(r'\d+', ' ', path))
    except ValueError:
        pass
    name = re.sub(r'[-_.]+', ' ', asset.get('name', ''))
    return ' '.join([name, slug, ' '.join(catalog.get('tags', [])), catalog.get('location', ''), catalog.get('title', '')])


def cleared(asset):
    """A reviewer explicitly cleared the setting, or reviewed a capture region (location verified)."""
    catalog = asset.get('catalog', {})
    return bool(catalog.get('setting_cleared')) or bool(catalog.get('location_reviewed') and catalog.get('region_codes'))


def placement(asset, scene_text, advisory):
    """{'allowed', 'compatibility', 'reason'} for placing this library clip on this beat."""
    concept = vc.beat_need(scene_text or '')
    text = metadata_text(asset)
    region = story_region(advisory)
    candidate = {'title': text, 'description': '', 'tags': []}
    if region == 'US':
        geo = vc.geography(candidate, 'US', concept)
        if geo['compatibility'] == 'conflict':
            return {'allowed': False, 'compatibility': 'conflict', 'reason': geo['reason'] + '. Excluded from this US story even if reviewed.'}
        if geo['compatibility'] == 'possible_conflict' and not cleared(asset):
            return {'allowed': False, 'compatibility': 'possible_conflict',
                    'reason': geo['reason'] + '. Excluded until a reviewer clears the setting in Media Library.'}
        return {'allowed': True, 'compatibility': geo['compatibility'], 'reason': geo['reason']}
    named = vc.ABROAD.search(text) or vc.NON_US_VEHICLES.search(text)
    if named and not cleared(asset):
        return {'allowed': False, 'compatibility': 'possible_conflict',
                'reason': f'Clip metadata names {named.group(0)} and the story region is unknown. Excluded until a reviewer clears the setting.'}
    return {'allowed': True, 'compatibility': 'not_assessed', 'reason': 'Story region is not a US story; only named foreign places are checked'}
