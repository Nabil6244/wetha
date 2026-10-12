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

interface Candidate {candidate_id: string; title: string; provider: string; licence: string; attribution: string; source: string; height: number | null; seconds: number | null; score: number; reasons: string[]; recommended: boolean; tier?: string;
  visual?: {confidence: string; concept: string}; provenance?: {status: string; claimed_event: string | null}; location?: {certainty: string; named_place: string | null}}
interface Review {id: string; beats: {scene_id: string; narration: string; needs?: string; best_medium?: string; status?: string; status_note?: string; fallback?: {queries: string[]; note?: string | null} | null; candidates: Candidate[]}[]; warnings: string[]; recommended: number; auto?: number; unresolved?: {scene_id: string}[]; searches?: {searches: number; extra_searches: number; cache_hits: number}}

export default function FootageLibrary({plans}: {plans: {id: string; script_id: string}[]}) {
  const [review, setReview] = useState<Review | null>(null);
  const [imported, setImported] = useState<Record<string, string>>({});
  async function runReview() {
    if (!planId) {setError('Choose a plan to review footage for.'); return;}
    setBusy('Searching each beat and building the contact sheet');setError('');
    try {setReview(await api<Review>('/production/footage-review', {plan_id: planId}));}
    catch (e) {setError(e instanceof Error ? e.message : 'Footage review failed.');}
    finally {setBusy('');}
  }
  async function importAuto() {
    if (!review?.auto) return;
    if (!window.confirm(`Import ${Math.min(8, review.auto)} high-confidence illustrative clips? Download limits and licence checks still apply.`)) return;
    setBusy('Importing high-confidence clips');setError('');
    try {const result = await api<{results: {title: string; status: string}[]}>(`/production/footage-reviews/${review.id}/import`, {confirm: true, max_clips: 8});
      setImported(old => ({...old, ...Object.fromEntries(result.results.map(r => [r.title, r.status]))})); await refresh();}
    catch (e) {setError(e instanceof Error ? e.message : 'Batch import failed.');setBusy('');}
  }
  async function importCandidate(candidate: Candidate) {
    setBusy('Importing ' + candidate.title);setError('');
    try {await api('/production/discovery/import', {candidate_id: candidate.candidate_id, rights_confirmed: true}); setImported(old => ({...old, [candidate.candidate_id]: 'Imported'})); await refresh();}
    catch (e) {setImported(old => ({...old, [candidate.candidate_id]: e instanceof Error ? e.message : 'Import failed'}));setBusy('');}
  }
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
      <button className="button secondary" disabled={!!busy || !planId} onClick={() => {void runReview();}}>Review footage for this plan</button>
      <button className="button secondary" disabled={!!busy || !coverage?.needs_shot_analysis} onClick={() => {void analyze();}}>Analyze shots{coverage?.needs_shot_analysis ? ` (${coverage.needs_shot_analysis})` : ''}</button>
    </div>
    {busy && <p role="status">{busy}…</p>}
    {error && <p role="alert" className="production-error">{error}</p>}
    {review && <div aria-label="Footage review"><h3>Footage review · {review.auto ?? 0} high confidence · {review.recommended} recommended · nothing imported yet</h3>
      {!!review.auto && <button className="button primary" disabled={!!busy} onClick={() => {void importAuto();}}>Import {Math.min(8, review.auto)} high-confidence clips</button>}
      {review.searches && <p className="muted">{review.searches.searches} searches ({review.searches.extra_searches} alternative, {review.searches.cache_hits} from cache) · {review.unresolved?.length ?? 0} beats need review or attention · screening never clears a clip's setting</p>}
      {review.warnings.map((w, i) => <p className="review-note" key={i}>{w}</p>)}
      <img src={`/api/production/footage-reviews/${review.id}/sheet`} alt="Footage review contact sheet" style={{width: '100%', borderRadius: 8}}/>
      {review.beats.map(beat => <details key={beat.scene_id}><summary>{beat.narration.slice(0, 90)} · {beat.candidates.length} candidates{beat.status && beat.status !== 'ready' ? ` · ${beat.status === 'graphics' ? 'maps and radar' : beat.status === 'review' ? 'check setting' : 'needs attention'}` : ''}</summary>
        {beat.status_note && <p className="muted">{beat.status_note}{beat.fallback?.queries.length ? ` · also searched: ${beat.fallback.queries.join(', ')}` : ''}{beat.fallback?.note ? ` · ${beat.fallback.note}` : ''}</p>}
        {beat.candidates.map(c => <div key={c.candidate_id} className="production-actions"><span className="pill">{c.tier === 'auto' ? 'High confidence' : c.recommended ? 'Recommended' : 'Weak match'}</span>
          <span>{c.title} · {c.provider} · {c.height ?? '?'}p · {c.seconds ? Math.round(c.seconds) + ' s' : '?'} · score {c.score}<br/><small className="muted">{c.licence.split(' http')[0]} · {c.attribution} · {c.provenance?.claimed_event ? `claims ${c.provenance.claimed_event} (unverified)` : 'illustrative'} · location {c.location?.certainty ?? 'unknown'} · {c.reasons.join(' · ')}</small></span>
          <a href={c.source} target="_blank" rel="noreferrer">Source</a>
          {imported[c.candidate_id] ? <span>{imported[c.candidate_id]}</span> : <button className="button secondary" disabled={!!busy} onClick={() => {void importCandidate(c);}}>Import</button>}</div>)}
      </details>)}</div>}
    {coverage && <>
      <p>{(coverage.seconds / 60).toFixed(1)} minutes of video · {coverage.needs_location_review} clips need location review · {coverage.off_ratio} off-ratio clips (filled with a blurred frame) · {coverage.needs_shot_analysis} without shot analysis</p>
      {coverage.gaps.length > 0 && <div><h3>Gaps for this plan</h3><table className="library-table"><thead><tr><th>Need</th><th>Beats</th><th>Matching clips</th><th>Usable cuts</th><th>Status</th></tr></thead>
        <tbody>{coverage.gaps.map((g, i) => <tr key={i} className={`gap-${g.status}`}><td>{[...g.regions, ...g.topics].join(' · ')}</td><td>{g.beats}</td><td>{g.matching_clips}</td><td>{g.available_cuts} / {g.wanted_cuts} wanted</td><td>{g.status}</td></tr>)}</tbody></table></div>}
      <div className="library-grid"><Table title="By weather and impact" rows={coverage.by_topic}/><Table title="By reviewed region" rows={coverage.by_region}/><Table title="By context" rows={coverage.by_context}/><Table title="By declared event" rows={coverage.by_event}/></div>
    </>}
  </div></section>;
}
