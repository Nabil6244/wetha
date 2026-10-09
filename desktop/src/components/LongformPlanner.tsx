import {useEffect, useState} from 'react';
import {api} from '../api';

interface Chapter {id:string;title:string;question:string;seconds:number;start_seconds:number;graphics:string[];needs:string[];minimum_shots:number}
interface Blueprint {chapters:Chapter[];library:{independent_video_sources:number;total_video_seconds:number;footage_seconds_target:number};rules:{target_script_words:number[]}}
interface Audit {ready:boolean;seconds:number;shots:number;script_words:number;issues:{chapter_id?:string;code:string;message:string}[]}
interface Timeline {id:string;title:string;seconds:number;superseded:boolean}
const stamp=(n:number)=>`${Math.floor(n/60).toString().padStart(2,'0')}:${(n%60).toString().padStart(2,'0')}`;

export default function LongformPlanner({timelines}:{timelines:Timeline[]}) {
  const [plan,setPlan]=useState<Blueprint|null>(null);
  const [selected,setSelected]=useState<Record<string,string>>({});
  const [audit,setAudit]=useState<Audit|null>(null);
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  useEffect(()=>{void api<Blueprint>('/production/longform').then(setPlan).catch(e=>setError(e.message));},[]);
  return <section className="panel" aria-label="One-hour storm deep dive"><div className="panel-header"><h2>One-hour storm deep dive</h2><span className="pill">12 chapters · 60 minutes</span></div><div className="detail-body">
    <p>A different question in every chapter. Rotate maps, footage, timelines, comparisons and explainers; answer each question before moving on.</p>
    <p className="muted">Footage cuts: 3–4 seconds. Graphic holds: 4–9 seconds. At least four visual families per chapter. Each recording needs unused ranges and a two-minute gap before returning.</p>
    {error && <p role="alert" className="production-error">{error}</p>}
    {plan && <><p><strong>Content target:</strong> {plan.rules.target_script_words.join('–')} original sourced words, around 600 visual beats and 15 minutes of varied footage. Library: {plan.library.independent_video_sources} recordings / {plan.library.total_video_seconds}s before trimming. Local voiceover stays off.</p>
      <details><summary>Open chapter structure and content assignments</summary><div className="production-scene-list">{plan.chapters.map((chapter,i)=><article className="production-scene" key={chapter.id}><div className="production-scene-heading"><span>{String(i+1).padStart(2,'0')}</span><strong>{chapter.title}</strong><small>{stamp(chapter.start_seconds)}–{stamp(chapter.start_seconds+chapter.seconds)}</small></div><p>{chapter.question}</p><p className="muted">Visual treatments: {chapter.graphics.map(g=>g.replaceAll('_',' ')).join(' · ')}. Minimum {chapter.minimum_shots} shots.</p><p className="muted">Needed: {chapter.needs.join(' · ')}</p><label>CHAPTER TIMELINE<select aria-label={`Chapter ${i+1} timeline`} value={selected[chapter.id]??''} onChange={e=>{setSelected(old=>({...old,[chapter.id]:e.target.value}));setAudit(null);}}><option value="">Content not assigned yet</option>{timelines.filter(t=>!t.superseded).map(t=><option key={t.id} value={t.id}>{t.title} · {t.seconds}s</option>)}</select></label></article>)}</div></details>
      <div className="production-actions"><a className="button secondary" href="/api/production/longform" download="one-hour-storm-structure.json">Download chapter blueprint</a><button className="button secondary" disabled={busy} onClick={()=>{setBusy(true);setError('');void api<Audit>('/production/longform/check',{chapters:plan.chapters.map(c=>({chapter_id:c.id,timeline_ids:selected[c.id]?[selected[c.id]]:[]}))}).then(setAudit).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}>{busy?'Checking…':'Check hour content & repetition'}</button></div>
      {audit && <div role="region" aria-label="Hour content audit"><p><strong>{audit.ready?'Content audit passed':'More chapter content needed'}</strong> · {audit.seconds}s / 3600s · {audit.shots} shots · {audit.script_words} distinct edited words</p>{audit.issues.map((issue,i)=><p className="production-error" key={i}>{issue.message}</p>)}</div>}
      <p className="muted">This is the hour’s editorial structure. A short preview does not become an hour by replaying it. Complete chapter scripts and assets before the final program assembly.</p>
    </>}
  </div></section>;
}
