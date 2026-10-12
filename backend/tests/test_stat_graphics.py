"""Source-backed stat shots (warning timeline, zone comparison) and fewer repeated camera moves over one map."""
from datetime import datetime, timezone
from types import SimpleNamespace
from app import broadcast
from app.report_graphs import peak_wind
from app.visual_states import CAMERA_ONLY, assign

ISSUED = datetime(2026, 10, 10, 6, 7, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 10, 10, 14, 15, tzinfo=timezone.utc)
AREA = {'type': 'Feature', 'properties': {'kind': 'alert_area'},
        'geometry': {'type': 'Polygon', 'coordinates': [[[-83.4, 29.3], [-83.0, 29.3], [-83.0, 29.7], [-83.4, 29.7], [-83.4, 29.3]]]}}


def surge(identity, area, wind=None, expires=EXPIRES):
    text = 'STORM SURGE WARNING. * WIND - LATEST LOCAL FORECAST: Equivalent Tropical Storm force wind - '
    text += (f'Peak Wind Forecast: {wind} mph with gusts to 45 mph - ' if wind else '')
    text += 'POTENTIAL IMPACTS: potential for wind 58 to 73 mph'
    return SimpleNamespace(id=identity, title='Storm Surge Warning issued October 10', event_key='urn:' + identity, forecast_excerpt='', warnings=[],
                           provider='NWS', area=area, text=text, issued_at=ISSUED, expires_at=expires, facts={},
                           source_payload={'properties': {'senderName': 'NWS Tallahassee FL'}})


def shots(texts, story='dixie'):
    scenes = []
    for i, text in enumerate(texts):
        scene = {'id': f's{i}', 'type': 'region_focus', 'script_segment': text, 'seconds': 4, 'media_id': None, 'cuts': [], 'map_mode': 'auto',
                 'graphic_style': 'auto', 'parameters': {'source_advisory_id': story if isinstance(story, str) else story[i],
                                                         'geojson': {'features': [AREA]}, 'credit': 'NWS'}}
        scene['direction'] = broadcast.director(scene, 'urn:x', 4)
        scenes.append(scene)
    return scenes


def test_peak_wind_is_quoted_exactly_and_threat_ranges_are_ignored():
    value = peak_wind(surge('a', 'Coastal Bay', '30-40'))
    assert value['range'] == [30, 40] and value['unit'] == 'mph' and value['quote'] == 'peak wind forecast: 30-40 mph'
    assert peak_wind(surge('b', 'Coastal Bay')) is None   # "potential for wind 58 to 73 mph" is a threat category, not a forecast


def test_warning_timeline_needs_real_times_and_a_timing_beat():
    stories = {'dixie': surge('dixie', 'Coastal Dixie')}
    scenes = shots(['The warning remains in effect until 10:15 a.m.'])
    assert assign(scenes, stories.get) == ['warning_timeline']
    data = scenes[0]['parameters']['graphic_data']
    assert (data['issued_at'], data['expires_at']) == (ISSUED.isoformat(), EXPIRES.isoformat()) and data['office'] == 'NWS Tallahassee FL'
    assert broadcast.Composer(scenes[0]['direction'], scenes[0]['parameters']).frame(.6).size == (1920, 1080)
    assert 'warning_timeline' not in assign(shots(['Water kept rising along the coast.']), stories.get)   # no timing in the words
    no_expiry = {'dixie': surge('dixie', 'Coastal Dixie', expires=None)}
    assert 'warning_timeline' not in assign(shots(['The warning remains in effect until 10:15 a.m.']), no_expiry.get)


def test_zone_comparison_uses_only_quoted_ranges_from_the_same_issuance():
    stories = {'dixie': surge('dixie', 'Coastal Dixie', '10-15'), 'bay': surge('bay', 'Coastal Bay', '30-40'),
               'walton': surge('walton', 'South Walton', '35-45'), 'gulf': surge('gulf', 'Coastal Gulf')}
    # The comparison spans the stories in this video: Dixie's beat plus beats from the other zones.
    scenes = shots(['Peak winds were lighter in Dixie than in Bay.', 'Surge reached South Walton.', 'Surge reached Bay.', 'Surge reached Gulf.'],
                   story=['dixie', 'walton', 'bay', 'gulf'])
    assert assign(scenes, stories.get)[0] == 'zone_compare'
    rows = scenes[0]['parameters']['graphic_data']['rows']
    assert [(r['label'], r['range'], r['own']) for r in rows] == [('South Walton', [35, 45], False), ('Coastal Bay', [30, 40], False), ('Coastal Dixie', [10, 15], True)]
    assert all(r['quote'] in stories[r['advisory_id']].text.lower() for r in rows)   # every bar quotes its own warning
    assert broadcast.Composer(scenes[0]['direction'], scenes[0]['parameters']).frame(.8).size == (1920, 1080)
    others = ['Surge reached South Walton.', 'Surge reached Bay.']
    assert assign(shots(['Surge reached homes in Dixie.'] + others, story=['dixie', 'walton', 'bay']), stories.get)[0] != 'zone_compare'   # not a wind beat
    assert assign(shots(['Peak winds in Dixie were light.']), stories.get)[0] != 'zone_compare'   # no other zone in this video


def test_camera_moves_are_capped_when_other_pictures_exist_and_fall_back_instead_of_freezing():
    story = surge('dixie', 'Coastal Dixie')
    story.facts = {'description': 'HAZARD...Storm surge of 2 to 4 ft. SOURCE...NWS. IMPACT...Flooding of low-lying roads.'}
    texts = ['Water kept rising along the coast.', 'The warning remains in effect until 10:15 a.m.', 'Roads flooded near the shore.',
             'Officials issued the alert early.', 'Water kept rising along the coast.', 'It stays in effect until mid-morning, 10 a.m.',
             'Roads flooded near the shore.', 'Officials issued the alert early.']
    scenes = shots(texts)
    for scene in scenes:
        scene['parameters']['facts'] = story.facts   # as the timeline attaches the warning's own facts
    states = assign(scenes, {'dixie': story}.get)
    assert 'warning_timeline' in states
    moves = 0
    for i, (scene, state) in enumerate(zip(scenes, states)):
        if state not in CAMERA_ONLY:
            continue
        if moves >= 2 or (i and states[i - 1] in CAMERA_ONLY):
            # Past the cap or back to back only as a fallback: no non-camera picture was allowed for this shot.
            assert all(a['state'] in CAMERA_ONLY for a in scene['parameters']['state_meta']['alternatives']), (i, state)
        moves += 1
    # With nothing else new to show, the cap gives way to a camera move instead of blocking the shot.
    bare = assign(shots(['Conditions continued along the coast.'] * 2), {'dixie': surge('dixie', 'Coastal Dixie')}.get)
    assert bare[1] != 'hold'


def test_back_to_back_outlines_of_the_same_state_are_avoided_but_new_places_keep_their_shot():
    stories = {'dixie': surge('dixie', 'Coastal Dixie')}
    # From the real bulletin: "…Altamaha Sound, Georgia…" then "…Fernandina Beach, Florida…" drew two near-identical outlines.
    same = assign(shots(['Waters from Georgia and northeast Florida were covered.', 'It reached Fernandina Beach, Florida, offshore.']), stories.get)
    assert same[0] == 'place_focus' and same[1] != 'place_focus'
    different = assign(shots(['Along Florida’s Gulf Coast, surge was the threat.', 'Across parts of Alabama, heavy rain fell.']), stories.get)
    assert different == ['place_focus', 'place_focus']


def test_story_headlines_stay_inside_the_renderers_word_budget():
    # From a real bulletin: a Special Marine Warning area made the headline nine words and failed the storyboard.
    from app.visual_states import story_headline
    marine = SimpleNamespace(title='Special Marine Warning issued October 10', area='Coastal waters from Altamaha Sound to Fernandina Beach FL out 20 NM')
    headline = story_headline(marine)
    assert len(headline.split()) <= 8 and headline.startswith('SPECIAL MARINE WARNING · COASTAL WATERS')
    broadcast.SceneDirection(scene_type='region_focus', event_id='urn:x', duration=3, headline=headline, layers=[], sources=[], fallback='No layer')
