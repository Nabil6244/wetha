import subprocess
from types import SimpleNamespace
from PIL import Image
from app import footage_library, media_selection
from app.bulletin_edit import draft


def clip(**extra):
    return {'id': 'c', 'kind': 'video', 'name': 'Storm winds and rain', 'seconds': 20, 'rights_confirmed': True,
            'context': 'illustrative', 'attribution': 'Fixture', 'source': 'Fixture', 'catalog': {'tags': ['storm', 'rain', 'wind']}, **extra}


def test_cuts_start_on_a_new_shot_instead_of_straddling_one():
    asset = clip(shot_starts=[2.0, 5.0, 12.0])
    assert footage_library.place(asset, 0, 3.5) == 5.0      # 0-3.5 crosses 2.0; 2.0-5.5 crosses 5.0
    assert footage_library.place(asset, 5.0, 3.5) == 5.0    # stays inside the 5-12 shot
    assert footage_library.place(asset, 10, 3.5) == 12.0
    assert footage_library.place(clip(), 3, 3.5) == 3       # no analysis: plain start
    assert footage_library.place(asset, 17, 3.5) is None    # never runs past the recording
    # No single shot is long enough: keep the plain start rather than lose the clip.
    assert footage_library.place(clip(seconds=6, shot_starts=[1.5, 3.0, 4.5]), 0, 3.5) == 0


def test_cuts_never_show_black_or_frozen_ranges():
    # A NASA livestream recording: a "starting soon" slate, a fade to black, then the camera feed.
    asset = clip(seconds=600, shot_starts=[117.7], unusable_ranges=[[0, 0.8], [0.8, 2.8]])
    assert footage_library.place(asset, 0, 3.1) == 4       # opening skipped even though the first camera change is late
    asset = clip(seconds=724, shot_starts=[], unusable_ranges=[[0, 2.5], [2.97, 5.6], [6.6, 61.0]])
    assert footage_library.place(asset, 0, 3.6) == 61.2    # skips black at 3-5.6 and a static telemetry display
    assert footage_library.place(asset, 7.6, 2.8) == 61.2
    # Moving to the next camera shot must not land on unusable picture either.
    asset = clip(seconds=20, shot_starts=[10.0], unusable_ranges=[[12.0, 13.0]])
    assert footage_library.place(asset, 8, 3) == 8         # 10-13 would show the black at 12; keep the clean straddle
    assert footage_library.place(clip(seconds=20, unusable_ranges=[[10.0, 12.0]]), 8, 3) == 12.2
    assert footage_library.place(clip(seconds=10, unusable_ranges=[[0, 9]]), 0, 3) is None


def test_analysis_marks_black_and_frozen_picture(tmp_path):
    path = tmp_path / 'slate-black-feed.mp4'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=320x180:d=2:r=30',
                    '-f', 'lavfi', '-i', 'color=c=black:s=320x180:d=1:r=30', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:d=3:r=30',
                    '-filter_complex', '[0][1][2]concat=n=3:v=1', '-pix_fmt', 'yuv420p', str(path)], check=True)
    result = footage_library.analyse(path, 6)
    assert len(result['unusable_ranges']) == 1
    start, end = result['unusable_ranges'][0]
    assert start < .1 and 2.9 < end < 3.2                   # slate and black merge; the moving feed is usable
    assert footage_library.place({**clip(seconds=6), **result}, 0, 2.5) >= end
    assert footage_library.detect_shots(path, 6) == result['shot_starts']


def test_shot_detection_finds_camera_cuts(tmp_path):
    path = tmp_path / 'two-shots.mp4'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=320x180:d=2:r=30',
                    '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:d=2:r=30', '-filter_complex', '[0][1]concat=n=2:v=1',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    shots = footage_library.detect_shots(path, 4)
    assert len(shots) == 1 and abs(shots[0] - 2) < .1


def test_off_ratio_footage_fills_the_frame_without_black_bars(tmp_path):
    source = tmp_path / 'square.mp4';frame = tmp_path / 'frame.png'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x3366aa:s=640x480:d=1:r=30', '-pix_fmt', 'yuv420p', str(source)], check=True)
    graph = footage_library.fill_filter({'width': 640, 'height': 480})
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-filter_complex', graph, '-map', '[base]', '-frames:v', '1', str(frame)], check=True)
    image = Image.open(frame).convert('L')
    assert image.size == (1920, 1080)
    assert image.getpixel((40, 540)) > 8 and image.getpixel((1880, 540)) > 8
    assert 'pad=' in footage_library.fill_filter({'width': 1920, 'height': 1080})


def test_concepts_and_story_topics_widen_matching_without_dropping_weather_priority():
    advisory = SimpleNamespace(event_key='x', title='Hurricane Test', forecast_excerpt='Hurricane winds expected.')
    power = clip(id='power', name='Downed utility lines', catalog={'tags': ['power', 'outage']})
    storm = clip(id='storm')
    outage = {'id': 's', 'script_segment': 'Outages left residents without electricity for days.', 'parameters': {}}
    assert [c['media_id'] for c in media_selection.rank(outage, [power, storm], advisory)] == ['power']
    plain = {'id': 's', 'script_segment': 'Officials will update the public at noon.', 'parameters': {}}
    ranked = media_selection.rank(plain, [power, storm], advisory)
    assert [c['media_id'] for c in ranked] == ['storm'] and ranked[0]['reasons'][-1].startswith('Story topics')
    windy = {'id': 's', 'script_segment': 'Strong winds damaged homes.', 'parameters': {}}
    both = clip(id='both', catalog={'tags': ['wind', 'damage']})
    scores = {c['media_id']: c['score'] for c in media_selection.rank(windy, [both, storm], advisory)}
    assert scores['both'] > scores['storm']


def test_bulletin_cuts_stay_inside_camera_shots():
    rows = [{'id': str(i), 'type': 'lower_third', 'seconds': 7, 'script_segment': 'Storm winds and rain.',
             'parameters': {'source_advisory_id': 'source'}, 'media_id': None, 'trim_start': 0, 'transition': 'cut',
             'cuts': [], 'map_mode': 'auto', 'graphic_style': 'auto', 'regional_focus': 'auto'} for i in range(30)]
    assets = [clip(id=str(i), seconds=60, shot_starts=[4.0 * n + 1 for n in range(1, 15)]) for i in range(10)]
    result = draft({'scenes': rows}, assets, lambda _: SimpleNamespace(event_key='test'))
    cuts = [c for s in result['scenes'] for c in s['cuts']]
    assert cuts
    for cut in cuts:
        changes = next(a for a in assets if a['id'] == cut['media_id'])['shot_starts']
        assert not any(cut['trim_start'] + .05 < t < cut['trim_start'] + cut['seconds'] - .05 for t in changes)


def test_coverage_reports_library_mix_and_plan_gaps():
    media = [clip(id='a', seconds=35), clip(id='b', kind='image', seconds=None, name='Flooded street', catalog={'tags': ['flood']}),
             {**clip(id='n'), 'kind': 'audio'}]
    plan = {'scenes': [{'id': '1', 'script_segment': 'Wind and rain spread inland.', 'parameters': {'source_advisory_id': 'x'}},
                       {'id': '2', 'script_segment': 'Snow will fall in the mountains.', 'parameters': {'source_advisory_id': 'x'}}]}
    report = footage_library.coverage(media, plan, lambda _: SimpleNamespace(event_key='x', title='', forecast_excerpt=''))
    assert report['clips'] == 2 and report['videos'] == 1 and report['usable_cuts'] == 11
    assert report['needs_shot_analysis'] == 1
    assert {r['key'] for r in report['by_topic']} >= {'storm', 'flood'}
    status = {tuple(g['topics']): g['status'] for g in report['gaps']}
    assert status[('snow',)] == 'missing' and status[('rain', 'wind')] in ('thin', 'covered')
