import {useEffect, useState} from 'react';
import {Activity, ArrowRight, CheckCheck, Clock3, FileText, Sparkles} from 'lucide-react';
import {api} from '../api';
import type {Advisory, Dashboard, RunDetail} from '../contracts';

const descriptions = [
  'Snapshot preserved source evidence, checksums and collection health. Refresh the selected provider when requested.',
  'Compare position, intensity, pressure, warnings and source forecast wording with the linked previous advisory.',
  'Rank severity, recency, geography and verified changes with explicit editorial reasons.',
  'Check official provenance, source validity and unambiguous versions. Preserve evidence for each claim.',
  'Write source-backed English narration. Optional models compose approved blocks without adding facts.',
  'Flag unsupported edits, repetition, timing and forecast uncertainty. Require named human approval.',
];
const nice = (value: string) => value.replaceAll('_', ' ');

export default function Newsroom({data, busy, onRun, onOpen}: {data: Dashboard; busy: boolean; onRun:(advisory: Advisory, engine: string, refresh: boolean) => void; onOpen:(id: string) => void}) {
  const [selected, setSelected] = useState('');
  const [engine, setEngine] = useState('deterministic');
  const [refresh, setRefresh] = useState(false);
  const [runId, setRunId] = useState('');
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState('');
  const advisory = data.advisories.find(item => item.id === selected) ?? data.advisories[0];
  const activeRun = runId || data.newsroom.runs[0]?.id;
  const runStatus = data.newsroom.runs.find(run => run.id === activeRun)?.status;
  useEffect(() => {
    if (!activeRun) return;
    let cancelled = false;
    setDetail(null); setError('');
    void api<RunDetail>(`/newsroom/runs/${activeRun}`).then(value => {if (!cancelled) setDetail(value);}).catch(e => {if (!cancelled) setError(e.message);});
    return () => {cancelled = true;};
  }, [activeRun, runStatus]);
  return <>
    <section className="panel newsroom-launch"><div className="panel-header"><h2><Sparkles size={17}/>Build a newsroom draft</h2><span className="pill">Six recorded roles</span></div><div className="detail-body newsroom-controls">
      <div><label className="field-label" htmlFor="newsroom-evidence">SOURCE EVIDENCE</label><select id="newsroom-evidence" value={advisory?.id ?? ''} onChange={e => setSelected(e.target.value)} disabled={busy || !advisory}>{!advisory && <option>No stored evidence</option>}{data.advisories.map(item => <option key={item.id} value={item.id}>{item.title} · {item.provider} · {nice(item.freshness)} · {item.issued_at}</option>)}</select></div>
      <div><label className="field-label" htmlFor="writer-engine">WRITER</label><select id="writer-engine" value={engine} onChange={e => setEngine(e.target.value)} disabled={busy}>{data.newsroom.engines.map(value => <option key={value.id} value={value.id} disabled={!value.configured}>{value.name}{!value.configured && ' · not configured'}</option>)}</select><small className="muted">{data.newsroom.engines.find(value => value.id === engine)?.mode}</small></div>
      <label className="refresh-choice"><input type="checkbox" checked={refresh} onChange={e => setRefresh(e.target.checked)} disabled={busy || advisory?.provider === 'TRAINING'}/>Check the selected official feed before writing</label>
      <button className="button primary" disabled={busy || !advisory} onClick={() => advisory && onRun(advisory, engine, refresh && advisory.provider !== 'TRAINING')}><Sparkles size={16}/>Run newsroom</button>
      <p className="muted newsroom-context">{advisory?.freshness === 'current' ? 'Current evidence still requires human review. A source refresh can reveal a newer advisory.' : 'Restricted evidence produces a labeled reference draft and cannot pass current-news review.'}</p>
    </div></section>
    <div className="role-cards">{data.agents.map((agent, i) => <section className="panel role-card" key={agent.name}><span className="agent-number">0{i+1}</span><h3>{agent.name}</h3><span className={'pill ' + (agent.status === 'failed' ? 'amber' : 'green')}>{nice(agent.status)}</span><p>{descriptions[i]}</p></section>)}</div>
    <div className="newsroom-activity"><section className="panel"><div className="panel-header"><h2><Activity size={17}/>Newsroom runs</h2><span className="pill">{data.newsroom.runs.length} recent</span></div>{data.newsroom.runs.length ? <div className="run-list">{data.newsroom.runs.map(run => <button key={run.id} className={activeRun === run.id ? 'selected' : ''} onClick={() => setRunId(run.id)}><span className={'dot ' + (run.status === 'succeeded' ? 'green' : 'amber')}/><span><strong>{data.advisories.find(item => item.id === run.advisory_id)?.title ?? run.advisory_id}</strong><small>{run.engine} · {new Date(run.created_at).toISOString().slice(0,19).replace('T',' ')} UTC</small></span><span className="pill">{run.status}</span></button>)}</div> : <div className="empty"><FileText size={28}/><h3>No newsroom runs yet</h3><p>Each run records its source package and all six JSON handoffs.</p></div>}</section>
    <section className="panel"><div className="panel-header"><h2>Agent handoffs</h2>{detail?.script_id && <button className="text-button" onClick={() => onOpen(detail.script_id!)}>Open draft<ArrowRight size={14}/></button>}</div><div className="detail-body">{error && <p role="alert">{error}</p>}{detail ? <><p className="muted small">Run {detail.id.slice(0,8)} · {detail.status}</p>{detail.error && <p className="feed-error">{detail.error}</p>}{detail.steps.map(step => <details className="agent-handoff" key={step.sequence}><summary>{step.status === 'succeeded' ? <CheckCheck size={15} className="teal"/> : <Clock3 size={15} className="amber"/>}<strong>{step.sequence.toString().padStart(2,'0')} · {step.agent}</strong><span>{step.status}</span></summary><small>{step.finished_at ? 'Completed ' + step.finished_at : 'Started ' + step.started_at}</small>{step.error && <p className="feed-error">{step.error}</p>}<label className="field-label">OUTPUT CONTRACT</label><pre>{JSON.stringify(step.output, null, 2)}</pre><details><summary>Input package</summary><pre>{JSON.stringify(step.input, null, 2)}</pre></details></details>)}</> : <p className="muted">Select a run to inspect preserved inputs and outputs.</p>}</div></section></div>
    <section className="panel collection-log"><div className="panel-header"><h2>Operation log</h2></div><div className="job-list">{data.jobs.map(job => <div key={job.id}><span className={'dot ' + (job.status === 'succeeded' ? 'green' : 'amber')}/><div><strong>{nice(job.kind)}</strong><p>{job.detail || 'Working…'}</p></div><span className="pill">{job.status}</span></div>)}</div></section>
  </>;
}
