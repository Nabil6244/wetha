import {useEffect, useState} from 'react';
import {ArrowDown, ArrowUp, Copy, FileText, LoaderCircle, Save} from 'lucide-react';
import {api} from '../api';
import type {Dashboard, Script} from '../contracts';
import ScriptEditor from './ScriptEditor';
import PolishedNarration from './PolishedNarration';

const KEY = 'wetha-bulletin-builder-v1';
function saved() {try {return JSON.parse(localStorage.getItem(KEY) || '{}');} catch {return {};}}
function narrationText(value:string) {return value.split('\n\n').map(part=>part.trim()).filter(Boolean).join('\n\n');}
interface PreparedPlan {id:string;script_id:string;script_revision:number;source_label:string;superseded_script_revision:boolean;scenes:{id:string;type:string;script_segment:string;target_seconds:number;transition:string}[]}
export default function BulletinBuilder({data, disabled, onReady, onRefresh, onBusyChange,onDraftChange}: {data:Dashboard;disabled:boolean;onReady:(script:Script,plan:PreparedPlan)=>void;onRefresh?:()=>Promise<void>;onBusyChange?:(label:string)=>void;onDraftChange?:(dirty:boolean)=>void}) {
  const [initial] = useState(saved);
  const [ids,setIds] = useState<string[]>(initial.ids ?? []);
  const [minutes,setMinutes] = useState<number>(initial.minutes ?? 30);
  const [search,setSearch] = useState('');
  const [script,setScript] = useState<Script|null>(null);
  const [text,setText] = useState<string>(initial.unsavedText ?? '');
  const [baseRevision,setBaseRevision] = useState<number>(initial.baseRevision ?? 1);
  const [editing,setEditing] = useState(!!initial.editing);
  const [editor,setEditor] = useState<string>(initial.editor ?? '');
  const [note,setNote] = useState<string>(initial.note ?? '');
  const [working,setWorking] = useState('');
  const [message,setMessage] = useState('');
  const [error,setError] = useState('');
  const locked=disabled || !!working;
  const selected=ids.flatMap(id=>{const a=data.advisories.find(a=>a.id===id);return a?[a]:[];});
  const [showOlder,setShowOlder]=useState(false);
  const matching=data.advisories.filter(a=>`${a.title} ${a.area} ${a.provider} ${a.issued_at}`.toLowerCase().includes(search.toLowerCase()));
  const byNewest=(a:{issued_at:string},b:{issued_at:string})=>Date.parse(b.issued_at)-Date.parse(a.issued_at);
  const isLatest=(a:{freshness:string;id:string})=>a.freshness==='current'||ids.includes(a.id);
  const choices=[...matching].filter(a=>showOlder||isLatest(a)).sort(byNewest);
  const olderCount=matching.length-matching.filter(isLatest).length;
  async function refreshLatest() {
    await Promise.allSettled([api('/providers/nws/refresh',{}),api('/providers/nhc/refresh',{})]);
    await onRefresh?.();
  }
  useEffect(()=>{if (!initial.scriptId) return; let cancel=false;
    void api<Script>(`/scripts/${initial.scriptId}`).then(s=>{if (!cancel) {setScript(s);if (!initial.editing) {setText(s.text);setBaseRevision(s.revision);}}}).catch(()=>{if(!cancel)setError('The saved bulletin is unavailable. Choose stories and rebuild it.');});
    return()=>{cancel=true;};
  },[initial]);
  useEffect(()=>{try {localStorage.setItem(KEY,JSON.stringify({ids,minutes,scriptId:script?.id ?? initial.scriptId,unsavedText:text,editing,editor,note,baseRevision}));}catch{/* Browser storage may be disabled. Backend drafts remain saved. */}},[ids,minutes,script,text,editing,editor,note,baseRevision,initial]);
  async function prepare(s:Script) {
    const plan=await api<PreparedPlan>('/visuals/plans',{script_id:s.id,expected_revision:s.revision});
    onReady(s,plan); await onRefresh?.();
  }
  async function run(label:string,action:()=>Promise<void>) {setWorking(label);onBusyChange?.(label);setError('');setMessage('');try{await action();}catch(e){setError(e instanceof Error?e.message:'Bulletin operation failed');}finally{setWorking('');onBusyChange?.('');}}
  async function saveNarration() {
    if (!script) return;
    const finalText=narrationText(text);
    if (script.revision!==baseRevision) throw new Error('The saved narration has changed. Your draft is preserved; review the latest revision before saving.');
    if (finalText===narrationText(script.text)) {
      setText(script.text);setEditing(false);
      setMessage(`Narration is already saved as revision ${script.revision}. Upload its matching voiceover below.`);
      return;
    }
    if (finalText.length<50 || finalText.length>60000) throw new Error('Narration must contain between 50 and 60,000 characters. Your draft is preserved.');
    if (editor.trim().length<2) {document.querySelector<HTMLInputElement>('[aria-label="Bulletin editor name"]')?.focus();throw new Error('Enter your editor name before saving.');}
    const s=await api<Script>(`/scripts/${script.id}/polished`,{expected_revision:baseRevision,text:finalText,editor:editor.trim(),note:note.trim() || 'Narration edited',sources:[]});
    setScript(s);setText(s.text);setBaseRevision(s.revision);setEditing(false);
    setMessage(`Narration saved as revision ${s.revision}. Upload its matching voiceover below.`);
    try {await prepare(s);} catch(e) {throw new Error(`Narration saved as revision ${s.revision}, but scenes could not be prepared: ${e instanceof Error?e.message:String(e)}. Use “Use this narration for video” to retry.`);}
  }
  function move(index:number,delta:number) {setIds(old=>{const next=[...old];[next[index],next[index+delta]]=[next[index+delta],next[index]];return next;});}
  return <section className="panel bulletin-builder" id="bulletin-stories"><div className="panel-header"><h2><FileText size={17}/>1. Choose stories &amp; build narration</h2><span className="pill">Local writer · no paid API</span></div><div className="detail-body">
    <p>Select several reports, arrange the flow, and build one script here. Your choices and unfinished narration are saved on this computer.</p>
    <div className="production-fields"><label>FIND STORIES<input aria-label="Search bulletin stories" type="search" placeholder="Location, storm, warning…" value={search} onChange={e=>setSearch(e.target.value)}/></label><label>TARGET VIDEO LENGTH<select aria-label="Bulletin target length" value={minutes} disabled={locked} onChange={e=>setMinutes(Number(e.target.value))}>{[10,20,30,60].map(n=><option key={n} value={n}>{n} minutes</option>)}</select></label></div>
    {minutes===30&&<div aria-label="30-minute bulletin brief"><strong>30-minute bulletin</strong><p>Start with 6–8 related, substantive stories and about 4,350 sourced words. Aim for 300–400 visual shots, about 12 minutes of varied footage, maps no longer than 10 seconds, and graphs wherever the sources provide measurements.</p><p className="muted">Build and review the script first. Copy it for recording, upload your complete voiceover, match its duration, then build the mixed bulletin edit below. Missing material and footage are shown before export.</p></div>}
    <div className="production-actions"><strong>{showOlder?'All stories, newest first':'Latest current stories, newest first'}</strong><button className="text-button" disabled={locked} onClick={()=>{void run('Collecting the latest official alerts',refreshLatest);}}>Refresh latest alerts</button>{olderCount>0&&<button className="text-button" onClick={()=>setShowOlder(v=>!v)}>{showOlder?'Hide older stories':`Show ${olderCount} older or expired`}</button>}</div>
    <div className="newsroom-topic-list" role="group" aria-label="Bulletin stories">{choices.map(a=><label className="newsroom-topic" key={a.id}><input type="checkbox" aria-label={`Bulletin story ${a.title} · ${a.area} · ${a.id}`} checked={ids.includes(a.id)} disabled={locked || (!ids.includes(a.id) && ids.length>=12)} onChange={e=>setIds(old=>e.target.checked?[...old,a.id]:old.filter(id=>id!==a.id))}/><span><strong>{a.title}</strong><span>{a.area || 'Location not specified'}</span><small>{a.provider} · {a.freshness.replaceAll('_',' ')} · {a.issued_at}</small></span></label>)}{!choices.length&&<p>No reports match. Use Refresh sources or Import advisory above to add evidence.</p>}</div>
    <div className="production-actions"><strong>{selected.length} of 12 stories selected</strong><button className="text-button" disabled={locked||!ids.length} onClick={()=>setIds([])}>Clear stories</button></div>
    {selected.length>0&&<ol className="bulletin-order" aria-label="Bulletin story order">{selected.map((a,i)=><li key={a.id}><span><strong>{i+1}. {a.title}</strong><small>{a.area}</small></span><button className="button secondary" aria-label={`Move story ${i+1} up`} disabled={locked||i===0} onClick={()=>move(ids.indexOf(a.id),-1)}><ArrowUp size={15}/></button><button className="button secondary" aria-label={`Move story ${i+1} down`} disabled={locked||i===selected.length-1} onClick={()=>move(ids.indexOf(a.id),1)}><ArrowDown size={15}/></button></li>)}</ol>}
    {ids.length!==selected.length&&<p role="alert">Some saved stories are no longer available. Clear the selection and choose available reports.</p>}
    <button className="button primary" disabled={locked||!selected.length||selected.length!==ids.length||editing} onClick={()=>{void run('Building connected narration',async()=>{
      const s=await api<Script>('/newsroom/runs',{advisory_id:selected[0].id,advisory_ids:selected.map(a=>a.id),engine:'deterministic',refresh_sources:false,bulletin:true,target_minutes:minutes});
      setScript(s);setText(s.text);setBaseRevision(s.revision);setEditing(false);await prepare(s);setMessage('Connected narration and matching scenes are ready. Upload your voiceover below.');
    });}}>Build flowing bulletin ({selected.length} stories)</button>
    {!script&&<>{working&&<p role="status"><LoaderCircle size={15} className="spin"/>{working}…</p>}{error&&<p role="alert" className="feed-error">{error}</p>}{message&&<p role="status">{message}</p>}</>}
    {script&&<div className="bulletin-narration" id="bulletin-narration"><PolishedNarration key={script.id} script={script} disabled={locked||editing} onDraftChange={onDraftChange} onSaved={async s=>{setScript(s);setText(s.text);setBaseRevision(s.revision);setEditing(false);await prepare(s);}}/><h3>Your complete narration</h3><p>{script.title} · revision {script.revision} · {(script.estimated_seconds/60).toFixed(1)} minutes estimated · {script.label.replaceAll('_',' ')}</p>
      {script.bulletin&&<p className="review-note">Target: {script.bulletin.target_minutes} minutes · supported draft: {script.bulletin.word_count.toLocaleString()} words.{script.bulletin.coverage==='needs_more_material'?` About ${script.bulletin.remaining_words.toLocaleString()} more words of source-backed coverage are needed. Add more substantive reports; this draft is not padded to the target length.`:' Selected sources provide enough material for this target.'} Actual audio determines final duration.</p>}
      {editing&&script.revision!==baseRevision&&<p role="alert">The saved narration has a newer revision. Your unfinished text is preserved; copy it before discarding edits and reviewing the latest version.</p>}
      {editing?<><label className="field-label" htmlFor="bulletin-text">EDIT COMPLETE NARRATION</label><textarea id="bulletin-text" rows={18} disabled={locked} value={text} onChange={e=>setText(e.target.value)}/><div className="production-fields"><label>EDITOR NAME<input aria-label="Bulletin editor name" disabled={locked} value={editor} onChange={e=>setEditor(e.target.value)}/></label><label>REVISION NOTE (OPTIONAL)<input aria-label="Bulletin revision note" disabled={locked} value={note} onChange={e=>setNote(e.target.value)}/></label></div><p className="muted">Save before copying or recording. Sources are matched automatically; changes prepare new scenes and clear the previous voiceover confirmation.</p>{narrationText(text)===narrationText(script.text)&&<p role="status">No unsaved text changes. This narration is saved as revision {script.revision}.</p>}<button className="button primary" disabled={locked||script.revision!==baseRevision} onClick={()=>{void run('Saving narration revision',saveNarration);}}><Save size={15}/>Save narration</button><button className="button secondary" disabled={locked} onClick={()=>{setEditing(false);setText(script.text);setBaseRevision(script.revision);}}>Discard edits</button></>:<><article className="script-text bulletin-text">{script.text.split('\n\n').map((p,i)=><p key={i}>{p}</p>)}</article><div className="production-actions"><button className="button secondary" disabled={locked} onClick={()=>{void navigator.clipboard.writeText(script.text).then(()=>setMessage('Complete narration copied. Record it and upload your audio below.')).catch(()=>setMessage('Select the narration above and copy it manually.'));}}><Copy size={15}/>Copy complete narration</button><button className="button secondary" disabled={locked} onClick={()=>{setText(script.text);setBaseRevision(script.revision);setEditing(true);}}>Edit narration</button><button className="button secondary" disabled={locked} onClick={()=>{void run('Preparing bulletin scenes',()=>prepare(script));}}>Use this narration for video</button></div></>}
      <div aria-label="Narration save status" aria-live="polite">{working&&<p role="status"><LoaderCircle size={15} className="spin"/>{working}…</p>}{error&&<p role="alert" className="feed-error">{error}</p>}{message&&<p role="status">{message}</p>}</div>
      <details><summary>Sources, revisions &amp; editorial review</summary><ScriptEditor script={script} scripts={[script]} busy={locked} onSelect={()=>{}} onMutation={async(path,body)=>{let result:Script|undefined;await run('Saving editorial work',async()=>{result=await api<Script>(path,body);setScript(result);setText(result.text);setBaseRevision(result.revision);await onRefresh?.();});return result;}}/></details>
    </div>}
  </div></section>;
}
