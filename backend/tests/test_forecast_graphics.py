"""Statistical semantics and visual variety, using synthetic forecast points only."""
import copy
from app.forecast_graphics import STAT_MODES, alert_counts, rain_gap, rain_ranking, render_stat


def sample():
    names=[('pensacola','Pensacola'),('panama-city','Panama City'),('tallahassee','Tallahassee'),('jacksonville','Jacksonville'),('orlando','Orlando'),('tampa','Tampa'),('west-palm','West Palm Beach'),('miami','Miami')]
    points=[{'id':key,'name':name,'forecast':{'rain_probability':value,'wind_mph':[10,20], 'wind_direction':'NE','temperature_f':75}} for (key,name),value in zip(names,[None,93,10,50,0,12,20,9])]
    return {'snapshots':[{'hours':h,'valid_at':'2026-01-01T08:00:00+00:00','points':copy.deepcopy(points)} for h in [0,6,12,24,48,72]],
        'alerts':[{'event':'Flood Warning'},{'event':'Flood Warning'},{'event':'Hurricane Warning'}],
        'collected_at':'2026-01-01T07:00:00+00:00',
        'nhc':[{'latest':{'issued_at':'2026-01-01T06:00:00+00:00','facts':{'wind_mph':100,'pressure_mb':980,'movement_mph':12}},'geometry':{'issued_at':'2026-01-01T03:00:00+00:00'}}]}


def test_ranking_and_contrast_preserve_missing_data_and_percentage_points():
    p=sample();before=copy.deepcopy(p)
    ranked=rain_ranking(p,6)
    assert ranked[0]['id']=='panama-city'
    assert ranked[-1]['id']=='pensacola'
    assert ranked[-2]['id']=='orlando'  # 0% is a supplied value, not missing.
    assert rain_gap(p,6)==84
    assert rain_gap(p,6,'pensacola','miami') is None
    assert p==before


def test_alert_counts_count_source_records_without_merging_coverage():
    assert alert_counts(sample())=={'Flood Warning':2,'Hurricane Warning':1}


def test_each_graphic_has_a_distinct_frame_and_reveals_without_mutating_evidence():
    p=sample();before=copy.deepcopy(p);final_frames=[]
    for mode in sorted(STAT_MODES):
        row={'kind':mode,'hours':12}
        first=render_stat(row,p,0);last=render_stat(row,p,1)
        assert first.size==last.size==(1920,1080)
        assert first.tobytes()!=last.tobytes(),mode
        final_frames.append(last.tobytes())
    assert len(set(final_frames))==len(STAT_MODES)
    assert p==before
