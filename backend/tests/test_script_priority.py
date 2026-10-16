"""The script is rendered as written: values the cited alerts do not state are warnings, never a reason to stop."""
from app import production_report
from app.production import source_warnings


def test_values_not_in_the_sources_are_reported_and_kept_as_written():
    audit = {'ready': False, 'claims': [
        {'status': 'source_matched', 'unsupported_numbers': [], 'conflicts': []},
        {'status': 'needs_attention', 'unsupported_numbers': ['26'], 'conflicts': ['30–40 knots']}]}
    script = {'preview_audit': audit, 'editorial': {'issues': [{'code': 'missing_context', 'blocking': True}]}}
    warnings = source_warnings(script)
    assert warnings[0] == 'Paragraph 2: 26, 30–40 knots not found in the cited NWS alerts; kept as written.'
    assert 'opening' in warnings[1]
    report = production_report.build({'id': 'r'}, {'title': 't', 'seconds': 10, 'scenes': [], 'preview_audit': audit}, {}, '', '', lambda i: None, {})
    rows = [f for f in report['findings'] if f['code'] == 'source_mismatch']
    assert rows and rows[0]['severity'] == 'warning' and report['errors'] == 0
