import {useEffect, useState} from 'react';
import {RefreshCw} from 'lucide-react';
import {api} from '../api';

interface Row {key: string; clips: number; seconds: number; cuts: number}
interface Gap {regions: string[]; topics: string[]; beats: number; seconds: number; matching_clips: number; available_cuts: number; wanted_cuts: number; short_by: number; status: string}
interface Coverage {
  clips: number; videos: number; seconds: number; usable_cuts: number; needs_location_review: number; needs_shot_analysis: number; off_ratio: number;
  by_topic: Row[]; by_region: Row[]; by_context: Row[]; by_event: Row[]; gaps: Gap[];
}

function Table({title, rows}: {title: string; rows: Row[]}) {
  return <div><h3>{title}</h3><table className="library-table"><thead><tr><th>Category</th><th>Clips</th><th>Minutes</th><th>Usable cuts</th></tr></thead>
    <tbody>{rows.slice(0, 12).map(r => <tr key={r.key}><td>{r.key}</td><td>{r.clips}</td><td>{(r.seconds / 60).toFixed(1)}</td><td>{r.cuts}</td></tr>)}</tbody></table></div>;
}

export default function FootageLibrary({plans}: {plans: {id: string; script_id: string}[]}) {
  const [planId, setPlanId] = useState('');
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  async function refresh(plan = planId) {
    setBusy('Reading library');setError('');
    try {setCoverage(await api<Coverage>('/production/footage-coverage' + (plan ? `?plan_id=${encodeURIComponent(plan)}` : '')));}
    catch (e) {setError(e instanceof Error ? e.message : 'Unable to read the footage library.');}
    finally {setBusy('');}
  }
  async function analyze() {
    setBusy('Finding camera cuts inside clips');setError('');
    try {const result = await api<{analyzed: number; failed: string[]}>('/production/media/analyze-shots', {});
      if (result.failed.length) setError(`Could not analyse: ${result.failed.join(', ')}`);
      await refresh();}
    catch (e) {setError(e instanceof Error ? e.message : 'Shot analysis failed.');setBusy('');}
  }
  useEffect(() => {void refresh('');}, []);
  return <section className="panel" aria-label="Footage library"><div className="panel-header"><h2>Footage library</h2><span className="pill">{coverage ? `${coverage.videos} videos · ${coverage.usable_cuts} usable cuts` : 'Loading'}</span></div><div className="detail-body">
    <div className="production-actions">
      <label>COVERAGE FOR<select aria-label="Coverage for plan" value={planId} onChange={e => {setPlanId(e.target.value);void refresh(e.target.value);}}><option value="">Whole library</option>{plans.map(p => <option key={p.id} value={p.id}>Plan {p.id.slice(0, 8)}</option>)}</select></label>
      <button className="button secondary" disabled={!!busy} onClick={() => {void refresh();}}><RefreshCw size={15}/>Refresh</button>
      <button className="button secondary" disabled={!!busy || !coverage?.needs_shot_analysis} onClick={() => {void analyze();}}>Analyze shots{coverage?.needs_shot_analysis ? ` (${coverage.needs_shot_analysis})` : ''}</button>
    </div>
    {busy && <p role="status">{busy}…</p>}
    {error && <p role="alert" className="production-error">{error}</p>}
    {coverage && <>
      <p>{(coverage.seconds / 60).toFixed(1)} minutes of video · {coverage.needs_location_review} clips need location review · {coverage.off_ratio} off-ratio clips (filled with a blurred frame) · {coverage.needs_shot_analysis} without shot analysis</p>
      {coverage.gaps.length > 0 && <div><h3>Gaps for this plan</h3><table className="library-table"><thead><tr><th>Need</th><th>Beats</th><th>Matching clips</th><th>Usable cuts</th><th>Status</th></tr></thead>
        <tbody>{coverage.gaps.map((g, i) => <tr key={i} className={`gap-${g.status}`}><td>{[...g.regions, ...g.topics].join(' · ')}</td><td>{g.beats}</td><td>{g.matching_clips}</td><td>{g.available_cuts} / {g.wanted_cuts} wanted</td><td>{g.status}</td></tr>)}</tbody></table></div>}
      <div className="library-grid"><Table title="By weather and impact" rows={coverage.by_topic}/><Table title="By reviewed region" rows={coverage.by_region}/><Table title="By context" rows={coverage.by_context}/><Table title="By declared event" rows={coverage.by_event}/></div>
    </>}
  </div></section>;
}
