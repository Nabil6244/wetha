"""The source check accepts a number however it is written, and still blocks numbers the alerts never gave."""
from datetime import datetime, timezone
from types import SimpleNamespace
from app.preview_audit import audit

ISSUED = datetime(2026, 10, 12, 9, 3, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
# Wording from the real Oct 12 bulletin's alerts.
WINTER = ('Winter Storm Warning issued October 12 at 2:34AM MDT until October 12 at 6:00AM MDT by NWS Great Falls MT\n\n'
          '* WHERE...Cascade County below 5000ft, Eastern Pondera and Eastern Teton, Fergus County below 4500ft, and Judith Basin.')
CREEK = ('Flood Warning issued October 12 at 5:03AM EDT until October 12 at 8:00PM EDT by NWS Mount Holly NJ\n\n'
         '...The Flood Warning is extended for Chester Creek at Chester.\n'
         '* ADDITIONAL DETAILS... - At 447 AM EDT Monday the stage was 8.4 feet. - Flood stage is 8.0 feet. '
         '- Forecast...The river is expected to crest at 9.3 feet. - At 10.5 feet, flooding begins near the creek. '
         'Rainfall of 2 inches fell overnight.')
RIVER = ('Flood Warning issued October 11 at 10:01PM EDT until October 16 at 8:00AM EDT by NWS Tampa Bay Ruskin FL\n\n'
         '...for the Withlacoochee River at US 41 at Dunnellon. Flood stage is 28.0 feet. '
         'Excessive hydrilla growth along a 4.5 mile stretch of river.')


def alert(identity, area, text):
    return SimpleNamespace(id=identity, area=area, text=text, title='Flood Warning', issued_at=ISSUED, expires_at=EXPIRES, checksum='c' * 64)


SOURCES = [alert('winter', 'Eastern Pondera and Eastern Teton; Cascade County', WINTER),
           alert('creek', 'Delaware, PA', CREEK), alert('river', 'Citrus, FL; Levy, FL; Marion, FL', RIVER)]


def check(*paragraphs):
    document = {'advisory_id': 'winter', 'selected_advisory_ids': [a.id for a in SOURCES], 'text': '\n\n'.join(paragraphs),
                'claims': [{'id': f'c{i}', 'text': p} for i, p in enumerate(paragraphs)]}
    return audit(document, SOURCES)['claims']


def test_numbers_written_differently_from_the_alert_are_supported():
    rows = check('The warning covers Cascade County below 5,000 feet and Fergus County below 4,500 feet in Eastern Pondera and Eastern Teton.',
                 # The alert is filed under Delaware County, which the narration never names.
                 'Chester Creek at Chester measured 8.4 feet at 4:47 a.m., above its flood stage of 8 feet, with a crest of 9.3 feet. '
                 'The warning was issued at 5:03 a.m. on October 12 and runs until 8 p.m. Flooding begins at 10.5 feet.',
                 'The Withlacoochee River at U.S. 41 in Dunnellon is at its 28-foot flood stage, with hydrilla along a four-and-a-half-mile stretch '
                 'in Citrus County. It runs until 8 a.m. on October 16.')
    assert [r['status'] for r in rows] == ['source_matched'] * 3, [(r['unsupported_numbers'], r['conflicts']) for r in rows]
    assert rows[1]['primary_advisory_id'] == 'creek'


def test_numbers_the_alerts_never_gave_are_still_blocked():
    wrong = {
        '6,000 feet': 'The warning covers Cascade County below 6,000 feet in Eastern Pondera and Eastern Teton.',
        'rounded stage': 'Chester Creek at Chester measured 8 feet at 4:47 a.m. and will crest near 9 feet.',
        'wrong time': 'Chester Creek at Chester measured 8.4 feet at 4:48 a.m.',
        'wrong date': 'Chester Creek at Chester measured 8.4 feet at 4:47 a.m. on October 19.',
        'wrong rainfall': 'Chester Creek at Chester rose after 3 inches of rain fell overnight.',
    }
    for case, text in wrong.items():
        row = check(text)[0]
        assert row['status'] == 'needs_attention', case
    assert '6000' in check(wrong['6,000 feet'])[0]['unsupported_numbers']


def test_marine_winds_written_as_kt_support_narrated_knots():
    gale = SimpleNamespace(id='gale', area='Coastal waters from Cape Fear to Surf City NC out 20 nm', title='Gale Warning', checksum='g' * 64,
                           issued_at=ISSUED, expires_at=EXPIRES,
                           text='Gale Warning issued October 12 at 5:03AM EDT by NWS Wilmington NC\n\n'
                                '* WHAT...Northwest winds 30 to 40 kt with gusts up to 55 kt and seas 8 to 12 ft.')
    document = {'advisory_id': 'gale', 'selected_advisory_ids': ['gale'], 'text': 'x',
                'claims': [{'id': 'c', 'text': 'Off Cape Fear, northwest winds of 30 to 40 knots could gust to 55 knots, with seas of 8 to 12 feet.'},
                           {'id': 'w', 'text': 'Off Cape Fear, northwest winds of 30 to 45 knots are expected.'}]}
    rows = audit(document, [gale])['claims']
    assert rows[0]['status'] == 'source_matched', (rows[0]['unsupported_numbers'], rows[0]['conflicts'])
    assert rows[1]['status'] == 'needs_attention'   # a wind range the alert never gave is still blocked


def test_a_local_evening_date_matches_an_alert_stored_in_utc():
    late = SimpleNamespace(id='late', area='Cape Fear NC', title='Gale Warning', checksum='l' * 64, text='Gale Warning for coastal waters.',
                           issued_at=datetime(2026, 10, 27, 0, 15, tzinfo=timezone.utc), expires_at=None)   # 8:15 p.m. EDT on October 26
    document = {'advisory_id': 'late', 'selected_advisory_ids': ['late'], 'text': 'x',
                'claims': [{'id': 'a', 'text': 'This Gale Warning for Cape Fear was issued on the evening of October 26.'},
                           {'id': 'b', 'text': 'This Gale Warning for Cape Fear was issued on October 20.'}]}
    rows = audit(document, [late])['claims']
    assert rows[0]['status'] != 'needs_attention' and rows[1]['status'] == 'needs_attention'
