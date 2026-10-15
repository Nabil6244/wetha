import type {ReactElement} from 'react';
import {CheckCircle2, Circle, LoaderCircle, MinusCircle, XCircle} from 'lucide-react';

export interface AutoJob {
  id: string; status: string; stage: string; progress: number; error: string | null; render_id: string | null; timeline_id: string | null;
  data?: {collected:string[];unavailable:string[]};
  stages: {key: string; label: string; status: string; detail: string}[];
  issues: {code: string; message: string}[];
  report: {errors: number; warnings: number; timings_seconds: Record<string, number>; cache: {reused_scenes: number; cached_on_retry: number; total_scenes: number};
    checks: {loudness_lufs: number | null; captions: number; frozen_intervals: number}; findings: {severity: string; code: string; message: string}[]} | null;
}

const icons: Record<string, ReactElement> = {
  done: <CheckCircle2 size={16} color="#65e1d1"/>, running: <LoaderCircle size={16} className="spin"/>,
  failed: <XCircle size={16} color="#ff8a80"/>, skipped: <MinusCircle size={16} color="#8aa"/>, pending: <Circle size={16} color="#567"/>,
};

export default function AutoProduction({job, busy, onResume, onCancel}: {job: AutoJob; busy: boolean; onResume: () => void; onCancel: () => void}) {
  const active = ['queued', 'running'].includes(job.status);
  const base = job.render_id ? `/api/production/renders/${job.render_id}` : '';
  return <section className="panel" aria-label="Automatic production progress"><div className="panel-header"><h2>Automatic production</h2><span className="pill">{job.status} · {job.progress}%</span></div><div className="detail-body">
    <ol className="auto-stages">{job.stages.map(stage => <li key={stage.key} className={`auto-stage ${stage.status}`}>{icons[stage.status] ?? icons.pending}<strong>{stage.label}</strong>{stage.detail && <span className="muted"> · {stage.detail}</span>}</li>)}</ol>
    {job.data&&<details open={!job.data.collected.length}><summary>Weather layers · {job.data.collected.length} collected · {job.data.unavailable.length} availability notes</summary><ul>{job.data.collected.map((message,i)=><li key={'found'+i}>{message}</li>)}{job.data.unavailable.map((message,i)=><li key={'missing'+i}>{message}</li>)}</ul></details>}
    {job.error && <p role="alert" className="production-error">{job.error}</p>}
    <div className="production-actions">
      {active && <button className="button secondary" disabled={busy} onClick={onCancel}>Cancel</button>}
      {['failed', 'interrupted', 'cancelled'].includes(job.status) && <button className="button primary" disabled={busy} onClick={onResume}>Resume · reuses finished work</button>}
    </div>
    {job.report && <div className="auto-report">
      <p><strong>{job.report.errors} errors · {job.report.warnings} warnings</strong> · loudness {job.report.checks.loudness_lufs ?? 'n/a'} LUFS · {job.report.checks.captions} captions · {job.report.cache.reused_scenes + job.report.cache.cached_on_retry} of {job.report.cache.total_scenes} scenes reused</p>
      <p className="muted">{Object.entries(job.report.timings_seconds).map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}s`).join(' · ')}</p>
      {job.report.findings.length > 0 && <details><summary>Findings to review</summary><ul>{job.report.findings.slice(0, 20).map((f, i) => <li key={i}><strong>{f.severity}</strong> {f.message}</li>)}</ul></details>}
      {base && <p><a href={`${base}/report_md`} target="_blank" rel="noreferrer">Full production report</a> · <a href={`${base}/thumbnail`} target="_blank" rel="noreferrer">Thumbnail</a> · <a href={`${base}/metadata`} target="_blank" rel="noreferrer">Title &amp; description</a></p>}
    </div>}
    {job.issues.length > 0 && !job.report && <details><summary>{job.issues.length} notes from planning</summary><ul>{job.issues.slice(0, 15).map((issue, i) => <li key={i}>{issue.message}</li>)}</ul></details>}
  </div></section>;
}
