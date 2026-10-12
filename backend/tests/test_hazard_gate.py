"""Footage must show the beat's own hazard; when nothing fits, the beat keeps its map or graphic."""
from datetime import datetime, timezone
from types import SimpleNamespace
from app import media_selection
from app.bulletin_edit import draft

ISSUED = datetime(2026, 10, 11, 18, 25, tzinfo=timezone.utc)


def story(title, area=''):
    return SimpleNamespace(id='story', provider='NWS', title=title, event_key='urn:story', issued_at=ISSUED, forecast_excerpt='', area=area)


def clip(identity, tags, name=None, **catalog):
    return {'id': identity, 'kind': 'video', 'name': name or identity + '.mp4', 'seconds': 60, 'rights_confirmed': True, 'context': 'archival',
            'attribution': 'Fixture', 'source': 'https://example.org/' + identity, 'width': 1920, 'catalog': {'tags': tags, **catalog}}


def beat(text, identity='s'):
    return {'id': identity, 'script_segment': text, 'parameters': {'source_advisory_id': 'story'}}


# From the real Oct 11 render: hurricane cleanup and rough seas were placed on the Montana winter storm.
HURRICANE_CLEANUP = clip('cleanup', ['cleanup', 'damage', 'debris'], name='Fort Myers Beach debris clearance — archive.mp4', event_id='AL092022')
ROUGH_SEAS = clip('seas', ['waves', 'storm', 'wind'], name='storm-sea-1879456.mp4')
WILDFIRE_AFTERMATH = clip('burn', ['wildfire', 'aftermath', 'damage'])
SNOW_PLOW = clip('plow', ['snow', 'cleanup', 'traffic'], setting_cleared=True)   # reviewer cleared the setting (existing geo gate)


def test_a_different_hazard_is_never_placed_however_plausible():
    winter = story('Winter Storm Warning', 'Crazy Mountains')
    text = 'Crews cleared debris and damage on roads after heavy snow and strong wind.'
    excluded = []
    ranked = media_selection.rank(beat(text), [HURRICANE_CLEANUP, ROUGH_SEAS, WILDFIRE_AFTERMATH, SNOW_PLOW], winter,
                                  limit=None, allow_unverified=True, excluded=excluded)
    assert [r['media_id'] for r in ranked] == ['plow']
    reasons = {row['media_id']: row for row in excluded if row['compatibility'] == 'hazard_mismatch'}
    assert set(reasons) == {'cleanup', 'seas', 'burn'}
    assert 'tropical cyclone' in reasons['cleanup']['reason'] and 'wildfire' in reasons['burn']['reason']
    # Generic damage tags never carry a clip across hazards: wildfire aftermath is not hurricane damage.
    hurricane = story('Hurricane Warning')
    ranked = media_selection.rank(beat('The hurricane left damage and debris across the coast.'), [WILDFIRE_AFTERMATH, HURRICANE_CLEANUP],
                                  hurricane, limit=None, allow_unverified=True)
    assert [r['media_id'] for r in ranked] == ['cleanup']


def test_same_hazard_footage_from_a_comparable_region_is_a_labelled_fallback():
    flood = story('Flash Flood Warning')
    florida = clip('florida', ['flood', 'rain', 'storm'], location='Bradenton, Florida', region_codes=['FL'], location_reviewed=True,
                   reference='https://example.org/fl')
    ranked = media_selection.rank(beat('Heavy rain flooded roads across Alabama.'), [florida, SNOW_PLOW], flood, limit=None, allow_unverified=True)
    assert [r['media_id'] for r in ranked] == ['florida']
    assert ranked[0]['location_status'] == 'nearby' and 'Filmed in Bradenton, Florida' in ranked[0]['reasons'][0]
    # Hurricane surge flooding illustrates coastal flooding only, never a flash flood or a river rising inland.
    surge = clip('surge', ['flood', 'waves'], name='hurricane surge flooding.mp4')
    coastal = story('Coastal Flood Warning')
    assert [r['media_id'] for r in media_selection.rank(beat('Flooding covered streets.'), [surge], coastal, limit=None, allow_unverified=True)] == ['surge']
    assert media_selection.rank(beat('Flooding covered streets.'), [surge], flood, limit=None, allow_unverified=True) == []


def test_when_no_footage_fits_the_beat_keeps_its_map_or_graphic():
    def scene(identity, text):
        return {'id': identity, 'type': 'region_focus', 'script_segment': text, 'seconds': 4, 'media_id': None, 'trim_start': 0, 'transition': 'cut',
                'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto', 'regional_focus': 'auto', 'parameters': {'source_advisory_id': 'story'}}
    timeline = {'scenes': [scene('a', 'Finally, Montana.'), scene('b', 'Heavy snow and wind left debris and damage on mountain roads.')],
                'unverified_location_footage': True}
    winter = story('Winter Storm Warning', 'Crazy Mountains')
    mixed = draft(timeline, [HURRICANE_CLEANUP, ROUGH_SEAS, WILDFIRE_AFTERMATH], lambda identity: winter)
    second = mixed['scenes'][1]
    assert second['cuts'] == [] and second['media_id'] is None            # the graphic stays; nothing misleading is forced in
    assert any(i['code'] == 'footage_gap' and i.get('scene_id') == 'b' for i in mixed['issues'])
    assert {r['media_id'] for r in mixed['excluded_footage'] if r['compatibility'] == 'hazard_mismatch'} == {'cleanup', 'seas', 'burn'}
    # With fitting footage in the library, the same beat gets it.
    mixed = draft(timeline, [HURRICANE_CLEANUP, SNOW_PLOW], lambda identity: winter)
    assert [c['media_id'] for c in mixed['scenes'][1]['cuts']] == ['plow']


def test_hazard_footage_outranks_neutral_weather_and_tropical_rain_stays_off_ice_storms():
    ice = story('Ice Storm Warning')
    glaze = clip('glaze', ['ice', 'freezing', 'traffic'], setting_cleared=True)
    tropical_rain = clip('palms', ['rain', 'wind'], name='tropical rainstorm palms.mp4')
    ranked = media_selection.rank(beat('Freezing rain coated trees and roads in Michigan.'), [tropical_rain, glaze], ice, limit=None, allow_unverified=True)
    assert [r['media_id'] for r in ranked] == ['glaze']
    severe = story('Severe Thunderstorm Warning')
    hail = clip('hail', ['hail', 'wind'])
    palms = clip('palms', ['wind'], name='swaying palms.mp4')
    ranked = media_selection.rank(beat('Large hail and damaging winds hit Kansas.'), [palms, hail], severe, limit=None, allow_unverified=True)
    assert [r['media_id'] for r in ranked] == ['hail']   # palms are a tropical setting: excluded outside tropical states


def test_specific_hazard_footage_outranks_same_category_and_generic_storm_footage():
    severe = story('Severe Thunderstorm Warning')
    hail = clip('hail', ['hail', 'hailstorm', 'storm'])
    clouds = clip('clouds', ['thunderstorm', 'storm', 'clouds', 'wind'], name='storm clouds rolling.mp4')
    ranked = media_selection.rank(beat('Large hail and damaging winds hit Kansas.'), [clouds, hail], severe, limit=None, allow_unverified=True)
    assert ranked[0]['media_id'] == 'hail' and ranked[0]['score'] > ranked[1]['score']
    ice = story('Ice Storm Warning')
    glaze = clip('glaze', ['ice', 'icy', 'frozen'], setting_cleared=True)
    snow = clip('snow', ['snow', 'snowfall', 'winter', 'storm', 'traffic'], setting_cleared=True)
    ranked = media_selection.rank(beat('An ice storm left roads glazed across Missouri.'), [snow, glaze], ice, limit=None, allow_unverified=True)
    assert ranked[0]['media_id'] == 'glaze' and ranked[0]['score'] > ranked[1]['score']


def test_winter_storm_story_beats_that_never_say_snow_still_keep_their_hazard():
    from app.visual_director import classify, story_text
    winter = story('Winter Storm Warning', 'Crazy Mountains')
    # From the Oct 11 script: neither beat names snow, so the hazard must come from the alert title.
    for text in ('Finally, Montana. The National Weather Service in Billings issued a warning until noon on Monday.',
                 'If you must travel, keep an extra flashlight, food and water in your vehicle.'):
        assert classify(text, story_text(winter))['hazard'] == 'winter'
    ranked = media_selection.rank(beat('If you must travel, keep an extra flashlight, food and water in your vehicle on the road.'),
                                  [HURRICANE_CLEANUP, ROUGH_SEAS, SNOW_PLOW], winter, limit=None, allow_unverified=True)
    assert [r['media_id'] for r in ranked] == ['plow']
