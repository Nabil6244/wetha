import {useEffect, useState} from 'react';
import {Copy, Save} from 'lucide-react';
import {api} from '../api';
import type {Script} from '../contracts';
interface Source {id:string;title:string;area:string;text:string;issued_at:string;url:string}
interface Mapping {text:string;advisory_id:string}
export default function PolishedNarration({script,disabled,onSaved,onDraftChange}:{script:Script;disabled:boolean;onSaved:(s:Script)=>Promise<void>;onDraftChange?:(dirty:boolean)=>void}) {
  const key=`wetha-polished-${script.id}`;
  const [sources,setSources]=useState<Source[]>([]);
  const [sourceText,setSourceText]=useState('');
  const [text,setText]=useState(()=>localStorage.getItem(key)??'');
  const [mappings,setMappings]=useState<Mapping[]>(()=>{try{return JSON.parse(localStorage.getItem(key+'-review')??'{}').mappings??[];}catch{return [];}});
  const [mappedText,setMappedText]=useState(()=>{try{return JSON.parse(localStorage.getItem(key+'-review')??'{}').mappedText??'';}catch{return '';}});
  const [editor,setEditor]=useState(()=>{try{return JSON.parse(localStorage.getItem(key+'-review')??'{}').editor??'';}catch{return '';}});
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  useEffect(()=>{let cancelled=false;void api<{sources:Source[];text:string;instruction:string}>(`/scripts/${script.id}/source-pack`).then(pack=>{if(!cancelled){setSources(pack.sources);setSourceText(pack.instruction+'\n\n'+pack.text);}}).catch(e=>{if(!cancelled)setError(String(e));});return()=>{cancelled=true;};},[script.id]);
  useEffect(()=>{try{localStorage.setItem(key,text);}catch{/* backend source pack remains available */}},[text,key]);
  useEffect(()=>{onDraftChange?.(!!text.trim()&&text.trim()!==script.text.trim());},[text,script.text,onDraftChange]);
  useEffect(()=>{try{localStorage.setItem(key+'-review',JSON.stringify({mappings,mappedText,editor}));}catch{/* Keep the narration available even if storage is full. */}},[key,mappings,mappedText,editor]);
  async function run(action:()=>Promise<void>){setBusy(true);setError('');setMessage('');try{await action();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  const locked=disabled||busy;
  return <section id="polished-narration" aria-label="Polished narration workflow"><h3>Source material → your final script</h3><p>Copy the original reports, refine the narration in your preferred writing tool, then paste the finished script here. Keep each paragraph about one story.</p>
    <button className="button secondary" disabled={locked||!sourceText} onClick={()=>{void run(async()=>{await navigator.clipboard.writeText(sourceText);setMessage('Source pack copied with locations, issue times and source links.');});}}><Copy size={15}/>Copy source pack</button>
    <details><summary>Read source material</summary>{sources.map(s=><article key={s.id}><h4>{s.title} · {s.area}</h4><small>{s.issued_at} · <a href={s.url} target="_blank" rel="noreferrer">Official source</a></small><p style={{whiteSpace:'pre-wrap'}}>{s.text}</p></article>)}</details>
    <label className="field-label">PASTE FINAL SCRIPT<textarea aria-label="Paste final script" rows={12} value={text} disabled={locked} placeholder="Paste your refined narration. Separate story paragraphs with a blank line." onChange={e=>setText(e.target.value)}/></label>
    <button className="button primary" disabled={locked||text.trim().length<50||text.trim()===script.text.trim()} onClick={()=>{void run(async()=>{const normalized=text.includes('\n\n')?text:text.split(/\r?\n/).map(line=>line.trim()).filter(Boolean).join('\n\n');const saved=await api<Script>(`/scripts/${script.id}/polished`,{expected_revision:script.revision,text:normalized,editor:editor.trim()||'Local editor',note:'Imported narration with automatic source mapping',sources:[]});setText(normalized);setMappings([]);await onSaved(saved);setMessage('Script saved and source checks prepared automatically. Upload its voiceover and click Make final video.');});}}><Save size={15}/>Save script &amp; prepare automatically</button>
    <button id="match-final-script" className="button secondary" disabled={locked||text.trim().length<50} onClick={()=>{void run(async()=>{const normalized=text.includes('\n\n')?text:text.split(/\r?\n/).map(line=>line.trim()).filter(Boolean).join('\n\n');const result=await api<{paragraphs:Mapping[]}>(`/scripts/${script.id}/source-map`,{text:normalized});setText(normalized);setMappings(result.paragraphs);setMappedText(normalized);});}}>Match paragraphs to sources</button>
    {mappedText===text&&mappings.length>0&&<><p className="review-note">Review each suggested source. Word matching does not verify facts. Local previews automatically check source numbers, units and chapter locations. Source matching does not prove meaning; broadcast review remains separate.</p>{mappings.map((m,i)=><details key={i} open={!m.advisory_id}><summary>Paragraph {i+1} · {(()=>{const source=sources.find(s=>s.id===m.advisory_id);return source?`${source.title} · ${source.area}`:'Choose source';})()}</summary><p>{m.text}</p><label>SOURCE REPORT<select aria-label={`Source for paragraph ${i+1}`} value={m.advisory_id} disabled={locked} onChange={e=>setMappings(old=>old.map((row,j)=>j===i?{...row,advisory_id:e.target.value}:row))}><option value="">Choose source</option>{sources.map(s=><option key={s.id} value={s.id}>{s.title} · {s.area} · {s.issued_at}</option>)}</select></label><p style={{whiteSpace:'pre-wrap'}}>{sources.find(s=>s.id===m.advisory_id)?.text}</p></details>)}
      <label className="field-label">EDITOR NAME<input id="final-script-editor" aria-label="Final script editor" value={editor} disabled={locked} onChange={e=>setEditor(e.target.value)}/></label>
      {editor.trim().length<2&&<p className="review-note">Enter your editor name to save this script and replace the old scene plan.</p>}
      <button className="button primary" disabled={locked||text===script.text} onClick={()=>{void run(async()=>{if(editor.trim().length<2){document.getElementById("final-script-editor")?.focus();throw new Error("Enter your editor name before saving.");}const missing=mappings.findIndex(m=>!m.advisory_id);if(missing>=0){document.querySelector<HTMLSelectElement>(`[aria-label="Source for paragraph ${missing+1}"]`)?.focus();throw new Error(`Choose a source report for paragraph ${missing+1} before saving.`);}const saved=await api<Script>(`/scripts/${script.id}/polished`,{expected_revision:script.revision,text,editor:editor.trim(),note:'Imported polished narration with paragraph sources',sources:mappings.map(m=>m.advisory_id)});await onSaved(saved);setMappings([]);setMessage('Final script saved. Review its source support, then upload matching audio below.');});}}><Save size={15}/>Save final script &amp; prepare scenes</button></>}
    {error&&<p role="alert" className="feed-error">{error}</p>}{message&&<p role="status">{message}</p>}
  </section>;
}
