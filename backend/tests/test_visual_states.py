import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from app import broadcast
from app.visual_states import assign, candidates, STATES, WINDOW


ADVISORY = SimpleNamespace(provider='NHC', title='Hurricane Test Advisory 12', event_key='AL092024',
    issued_at=datetime(2024, 9, 26, 15, tzinfo=timezone.utc),
    forecast_excerpt='The center is expected to reach the coast tonight. Hurricane conditions are expected within the warning area this evening.',
    warnings=['A Hurricane Warning is in effect for the Florida Big Bend coast'])


def scene(i, text='The storm is moving north toward Tampa with 120 mph winds.', **extra):
    features = [{'type': 'Feature', 'properties': {'kind': 'reported_center', 'issued_at': f'2024-09-26T0{n}:00:00+00:00'},
                 'geometry': {'type': 'Point', 'coordinates': [-86 + n, 24 + n]}} for n in range(3)]
    row = {'id': f's{i}', 'type': 'storm_track', 'script_segment': text, 'seconds': 4, 'media_id': None, 'cuts': [],
           'map_mode': 'auto', 'graphic_style': 'auto',
           'parameters': {'source_advisory_id': 'al', 'geojson': {'type': 'FeatureCollection', 'features': features},
                          'facts': {'wind_mph': 120, 'pressure_mb': 950, 'latitude': 26, 'longitude': -84},
                          'changes': [{'field': 'wind_mph', 'previous': 100, 'current': 120}],
                          'places': [('Tampa', [-82.46, 27.95]), ('Cedar Key', [-83.03, 29.14])],
                          'credit': 'NHC'}, **extra}
    row['direction'] = broadcast.director(row, 'AL092024', 4)
    return row


def test_long_sequences_never_repeat_a_state_within_the_window_or_stack_cards():
    scenes = [scene(i) for i in range(60)]
    states = assign(scenes, lambda _: ADVISORY)
    assert len(set(states)) >= 8
    for i, state in enumerate(states):
        assert state not in states[max(0, i - WINDOW):i]
    families = [STATES[s][0] for s in states]
    assert not any(a in ('card', 'split') and b in ('card', 'split') for a, b in zip(families, families[1:]))


def test_footage_charts_and_manual_choices_are_kept_and_count_toward_rhythm():
    scenes = [scene(i) for i in range(6)]
    scenes[1]['cuts'] = [{'media_id': 'clip', 'seconds': 4, 'trim_start': 0}]
    scenes[2]['map_mode'] = 'warnings'
    scenes[3]['parameters']['report_graphs'] = {'charts': []}
    before = copy.deepcopy(scenes)
    states = assign(scenes, lambda _: ADVISORY)
    assert states[1:4] == ['footage', 'map', 'chart']
    assert [s['parameters'] for s in scenes[1:4]] == [s['parameters'] for s in before[1:4]]
    # A card never follows a chart.
    assert STATES[states[4]][0] not in ('card', 'split')


def test_states_are_only_offered_when_their_source_data_exists():
    bare = scene(0, text='Conditions remain uncertain.')
    bare['parameters'].update(facts={}, changes=[], places=[], geojson={'features': []})
    quiet = SimpleNamespace(**{**vars(ADVISORY), 'forecast_excerpt': None, 'warnings': []})
    offered = {state for state, _, _ in candidates(bare, quiet)}
    assert offered == {'wide', 'pan', 'pull_out', 'source_card'}


def test_every_state_renders_frames_from_pinned_data():
    scenes = [scene(i) for i in range(40)]
    assign(scenes, lambda _: ADVISORY)
    seen = set()
    for row in scenes:
        state = row['parameters'].get('visual_state')
        if state in seen:
            continue
        seen.add(state)
        composer = broadcast.Composer(row['direction'], row['parameters'])
        for t in (0, .5, 1):
            assert composer.frame(t).size == (1920, 1080)
    assert {'stat_card', 'quote_card', 'place_callout', 'push_in'} <= seen
