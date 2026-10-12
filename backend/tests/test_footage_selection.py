"""Footage is chosen for the words on each shot and the story's real hazard and severity; the editor's footage folder
feeds the same library and safeguards."""
import os
import subprocess
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import media_selection
from app.bulletin_edit import draft
from app.main import create_app

ISSUED = datetime(2026, 10, 12, 6, 50, tzinfo=timezone.utc)


def story(title, area='', text=''):
    return SimpleNamespace(id='story', provider='NWS', title=title, event_key='urn:story', issued_at=ISSUED, forecast_excerpt='', area=area, text=text)


def clip(identity, tags, name=None, **catalog):
    return {'id': identity, 'kind': 'video', 'name': name or identity + '.mp4', 'seconds': 60, 'rights_confirmed': True, 'context': 'illustrative',
            'attribution': 'Fixture', 'source': 'https://example.org/' + identity, 'width': 1920, 'catalog': {'tags': tags, **catalog}}


def shot(text, paragraph=None):
    scene = {'id': 's', 'script_segment': text, 'parameters': {'source_advisory_id': 'story'}}
    if paragraph:
        scene['source_claim_text'] = paragraph
    return scene


def picked(scene, assets, advisory, excluded=None):
    return [r['media_id'] for r in media_selection.rank(scene, assets, advisory, limit=None, allow_unverified=True, excluded=excluded)]


# Clips modelled on the ones the real Oct 12 bulletin misplaced.
PALMS = clip('palms', ['clouds', 'palms', 'storm', 'wind'], name='pexels-37203610.mp4')
SHELF_CLOUD = clip('shelf', ['clouds', 'shelf cloud', 'storm', 'thunderstorm', 'wind'])
WIND_GRASS = clip('grass', ['wind', 'grass', 'plains'], name='wind-swept-prairie.mp4')
SEAWALL = clip('seawall', ['seawall', 'storm', 'surge', 'waves'])
OCEAN = clip('ocean', ['waves', 'wind'], name='ocean-waves-crashing.mp4')
HURRICANE_FROM_SPACE = clip('iss', ['storm', 'waves', 'wind'], name='jsc2019m000804_Hurricane_Dorian_190831.mp4')
RIVER = clip('river', ['flood', 'river', 'rushing water'])
DESTROYED_HOMES = clip('destroyed', ['aerial', 'damage', 'debris', 'destroyed', 'homes'], name='pexels-4196206.mp4')
HURRICANE_CLEANUP = clip('cleanup', ['cleanup', 'debris', 'recovery'], name='Fort Myers Beach debris clearance — archive.mp4', event_id='AL092022')
FLOODED_DESTRUCTION = clip('flooded-ruins', ['flood', 'damage', 'destroyed', 'homes'])

RIVER_STORY = story('Flood Warning', 'Henderson, NC; Transylvania, NC',
                    'Flood Warning for the French Broad River at Blantyre. Minor flooding is occurring. Flood stage is 16.0 feet. '
                    'At 17.0 feet, farmland and boat access areas flood.')


def test_a_wyoming_high_wind_warning_gets_wind_footage_not_tropical_palms_or_thunderstorms():
    wind = story('High Wind Warning', 'Ferris/Seminoe/Shirley Mountains; Central Carbon County')
    excluded = []
    for text in ('Those crosswinds could make travel dangerous for campers in Wyoming.', '12:50 a.m. Mountain Daylight Time on October 12,'):
        assert picked(shot(text), [PALMS, SHELF_CLOUD, WIND_GRASS], wind, excluded) == ['grass'], text
    reasons = {row['media_id']: row['reason'] for row in excluded if row['compatibility'] == 'hazard_mismatch'}
    assert 'tropical setting' in reasons['palms'] and 'severe storm' in reasons['shelf']


def test_a_mountain_river_flood_never_gets_ocean_waves_seawalls_or_hurricanes():
    assert picked(shot('At 10:30 p.m. Sunday, the river measured 17.7 feet and was slowly rising.'),
                  [SEAWALL, OCEAN, HURRICANE_FROM_SPACE, RIVER], RIVER_STORY) == ['river']
    # "Storm" in the narration does not let surge or hurricane footage onto a river flood: the hazard gate refuses them.
    excluded = []
    assert picked(shot('Widespread storm rainfall of 4 to 6 inches is keeping the river high.'),
                  [SEAWALL, OCEAN, HURRICANE_FROM_SPACE, RIVER], RIVER_STORY, excluded) == ['river']
    assert {r['media_id'] for r in excluded if r['compatibility'] == 'hazard_mismatch'} >= {'seawall', 'iss'}
    # Surge footage still serves a coastal surge story.
    surge = story('Storm Surge Warning', 'Coastal Dixie', 'Storm surge of 2 to 4 feet above ground is possible.')
    assert 'seawall' in picked(shot('Water could rise along the coast with the surge.'), [SEAWALL, RIVER], surge)


def test_minor_river_flooding_never_gets_destruction_or_disaster_cleanup_footage():
    excluded = []
    assert picked(shot('At 18 feet, several riverside homes flood and water covers the overlook.'),
                  [DESTROYED_HOMES, HURRICANE_CLEANUP, FLOODED_DESTRUCTION, RIVER], RIVER_STORY, excluded) == ['river']
    assert {r['media_id'] for r in excluded} >= {'destroyed', 'flooded-ruins'}   # the cleanup clip shares no topic with this line at all


def test_a_time_or_county_line_never_inherits_its_paragraphs_damage_words():
    damaged = story('Flood Warning', 'Lake, FL', 'Several homes were destroyed and debris covers roads after flooding.')
    paragraph = 'Several homes were destroyed and debris covers roads. The warning was issued at 10:01 p.m. for Lake County.'
    for line in ('issued this warning at 10:01 p.m. Eastern Daylight Time on October 11,', 'for Lake and Volusia counties, until further notice.'):
        assert 'flooded-ruins' not in picked(shot(line, paragraph), [FLOODED_DESTRUCTION, RIVER], damaged), line
    # The damage beat itself, in a story that reports damage as having happened, may show it.
    assert 'flooded-ruins' in picked(shot('Several homes were destroyed by the flooding.', paragraph), [FLOODED_DESTRUCTION, RIVER], damaged)


def scene(identity, text):
    return {'id': identity, 'type': 'region_focus', 'script_segment': text, 'seconds': 4, 'media_id': None, 'trim_start': 0, 'transition': 'cut',
            'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto', 'regional_focus': 'auto', 'parameters': {'source_advisory_id': 'story'}}


def test_no_compatible_clip_keeps_the_graphic_and_diversity_never_brings_in_unrelated_footage():
    lines = ['In North Carolina, the river keeps rising.', 'The river measured 17.7 feet on Sunday.', 'Flood stage is 16 feet at the river gauge.',
             'The river crest is expected after midnight.', 'The river will fall below flood stage Monday.', 'Farmland floods along the river.']
    timeline = {'scenes': [scene(str(i), t) for i, t in enumerate(lines)], 'unverified_location_footage': True}
    mixed = draft(timeline, [SEAWALL, OCEAN, HURRICANE_FROM_SPACE, DESTROYED_HOMES], lambda identity: RIVER_STORY)
    assert not any(s['cuts'] for s in mixed['scenes'])                     # nothing fits: every beat keeps its map or graphic
    assert any(i['code'] == 'footage_gap' for i in mixed['issues'])
    # One fitting clip: it is used once, and the remaining beats keep graphics rather than repeating it or taking a bad clip.
    mixed = draft(timeline, [SEAWALL, OCEAN, HURRICANE_FROM_SPACE, DESTROYED_HOMES, RIVER], lambda identity: RIVER_STORY)
    used = [c['media_id'] for s in mixed['scenes'] for c in s['cuts']]
    assert used == ['river']


def video(path, seconds=4):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'testsrc2=s=320x180:d={seconds}:r=30', '-pix_fmt', 'yuv420p', str(path)], check=True)
    past = time.time() - 60
    os.utime(path, (past, past))   # copied a minute ago: complete


def test_the_footage_folder_imports_once_keeps_existing_records_and_survives_a_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        state = client.get('/api/production').json()
        folder = state['manual_footage_folder']
        assert folder == str(tmp_path / 'manual-footage' / 'inbox')
        video(tmp_path / 'manual-footage' / 'inbox' / 'french-broad-river-flood.mp4')
        (tmp_path / 'manual-footage' / 'inbox' / 'notes.txt').write_text('not a video')
        assert client.post('/api/production/media/folder-import', json={}).status_code == 422   # rights must be confirmed
        result = client.post('/api/production/media/folder-import', json={'rights_confirmed': True}).json()
        statuses = {r['file']: r['status'] for r in result['results']}
        assert statuses == {'french-broad-river-flood.mp4': 'added', 'notes.txt': 'skipped'}
        identity = next(r['media_id'] for r in result['results'] if r['status'] == 'added')
        catalog = {'tags': ['flood', 'river'], 'location': 'Blantyre, North Carolina', 'region_codes': ['NC'], 'location_reviewed': False,
                   'setting_cleared': True, 'setting_note': 'Filmed by me at the French Broad River'}
        assert client.put(f'/api/production/media/{identity}/catalog', json=catalog).status_code == 200
        again = client.post('/api/production/media/folder-import', json={'rights_confirmed': True}).json()
        assert [r['status'] for r in again['results'] if r['file'].endswith('.mp4')] == ['duplicate']
        assert (tmp_path / 'manual-footage' / 'inbox' / 'french-broad-river-flood.mp4').exists()   # source files are never moved
    with TestClient(create_app(tmp_path)) as client:   # restart
        media = {m['id']: m for m in client.get('/api/production').json()['media']}
        assert media[identity]['catalog']['setting_cleared'] and media[identity]['catalog']['tags'] == ['flood', 'river']
        assert 'unusable_ranges' in media[identity]                       # same analysis as an upload
        ranked = media_selection.rank(shot('The river measured 17.7 feet in North Carolina.'), list(media.values()), RIVER_STORY,
                                      limit=None, allow_unverified=True)
        assert [r['media_id'] for r in ranked] == [identity]


def test_a_hazard_word_inside_a_place_name_is_not_the_hazard():
    from app.visual_director import classify
    wind = story('High Wind Warning', 'North Snowy Range Foothills; Ferris/Seminoe/Shirley Mountains')
    # From the real Oct 12 render: "Snowy Range" put a blizzard clip on a Wyoming high-wind story.
    line = 'It covers the North Snowy Range Foothills, Ferris, Seminoe and Shirley Mountains.'
    assert classify(line, 'High Wind Warning')['hazard'] == 'high_wind'
    blizzard = clip('blizzard', ['blizzard', 'snow', 'wind', 'winter'])
    assert 'blizzard' not in picked(shot(line), [blizzard, WIND_GRASS], wind)
    assert classify('Heavy snow fell across the Snowy Range overnight.', '')['hazard'] == 'winter'   # real snow still counts
