import {useEffect, useState} from 'react';
import {CheckCheck, Clock3, Download, ExternalLink, FileText, History, Pencil, Save, ShieldCheck, X} from 'lucide-react';
import {api} from '../api';
import type {Claim, Script} from '../contracts';

const nice = (value: string) => value.replaceAll('_', ' ');
const date = (value: string) => new Date(value).toISOString().slice(0,19).replace('T',' ') + ' UTC';
type Mutation = (path: string, body: unknown, notice: string) => Promise<Script | undefined>;

function ClaimCard({claim, script, name, busy, onMutation}: {claim: Claim; script: Script; name: string; busy: boolean; onMutation: Mutation}) {
  const [source, setSource] = useState(claim.source_advisory_ids[0] ?? script.advisory_id);
  const [quote, setQuote] = useState('');
  const [explanation, setExplanation] = useState('');
  const [original, setOriginal] = useState('');
  const [error, setError] = useState('');
  return <details className={'claim-card ' + (claim.status === 'requires_verification' ? 'unsupported' : '')} open={claim.status === 'requires_verification'}>
    <summary><ShieldCheck size={14}/><span>{nice(claim.status)}</span><small>{claim.id.slice(-8)}</small></summary><p>{claim.text}</p>
    <small className="muted">Citations: {claim.source_advisory_ids.join(', ')}</small>
    {claim.support && <div className="claim-support"><strong>Verified by {claim.support.reviewer}</strong><blockquote>{claim.support.quote}</blockquote><p>{claim.support.explanation}</p><small>{claim.support.note}</small></div>}
    {claim.status === 'requires_verification' && script.is_latest && <div className="claim-form">
      <label className="field-label" htmlFor={'cite-' + claim.id}>SUPPORTING SOURCE</label><select id={'cite-' + claim.id} value={source} onChange={e => {setSource(e.target.value); setOriginal('');}}>{script.evidence_manifest.map(item => <option value={item.id} key={item.id}>{item.id} · {item.issued_at}</option>)}</select>
      <button className="text-button" disabled={busy} onClick={() => {setError(''); void api<{advisory:{text:string}}>(`/advisories/${encodeURIComponent(source)}/evidence`).then(value => setOriginal(value.advisory.text)).catch(e => setError(e.message));}}>Read preserved source<ExternalLink size={12}/></button>
      {original && <pre className="source-quote-preview">{original}</pre>}{error && <p role="alert">{error}</p>}
      <label className="field-label" htmlFor={'quote-' + claim.id}>EXACT SUPPORTING QUOTE</label><textarea id={'quote-' + claim.id} value={quote} onChange={e => setQuote(e.target.value)} rows={4} placeholder="Copy the supporting passage from the preserved source."/>
      <label className="field-label" htmlFor={'explain-' + claim.id}>WHY THIS QUOTE SUPPORTS THE CLAIM</label><textarea id={'explain-' + claim.id} value={explanation} onChange={e => setExplanation(e.target.value)} rows={2}/>
      <p className="muted">Use the reviewer name in the editorial panel. You are confirming the meaning; automatic checks only confirm quote and numerical presence.</p>
      <button className="button secondary full" disabled={busy || name.trim().length < 2 || quote.trim().length < 20 || explanation.trim().length < 10} onClick={() => {void onMutation(`/scripts/${script.id}/claims/support`, {expected_revision:script.revision, claim_id:claim.id, advisory_id:source, quote, explanation, reviewer:name.trim()}, 'Source attestation saved as a new revision. Editorial approval is still required.');}}>Record source attestation</button>
    </div>}
  </details>;
}

export default function ScriptEditor({script, scripts, busy, onSelect, onMutation}: {script?: Script; scripts: Script[]; busy: boolean; onSelect:(id: string) => void; onMutation: Mutation}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(script?.text ?? '');
  const [baseRevision, setBaseRevision] = useState(script?.revision ?? 1);
  const [editor, setEditor] = useState('');
  const [note, setNote] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [reviewNote, setReviewNote] = useState('');
  const [history, setHistory] = useState<Script | null>(null);
  const [historyError, setHistoryError] = useState('');
  const shown = history ?? script;
  useEffect(() => {
    if (!editing && script) {setText(script.text); setBaseRevision(script.revision);}
  }, [script?.revision, script?.text, editing]); // Keep unsaved text while background refreshes arrive.
  async function save() {
    if (!script) return;
    const result = await onMutation(`/scripts/${script.id}/revisions`, {expected_revision:baseRevision, text, editor:editor.trim(), note:note.trim()}, 'New revision saved. Previous approval was cleared.');
    if (result) {setEditing(false); setNote(''); setText(result.text); setBaseRevision(result.revision);}
  }
  async function browse(revision: string) {
    setHistoryError('');
    if (!script || revision === 'latest') {setHistory(null); return;}
    try {setHistory(await api<Script>(`/scripts/${script.id}?revision=${revision}`));}
    catch (e) {setHistoryError(e instanceof Error ? e.message : 'Could not load revision');}
  }
  return <div className="script-layout"><section className="panel script-document"><div className="panel-header"><h2><FileText size={17}/>Newsroom drafts</h2><span className="pill amber">Editorial review required</span></div>{shown && script ? <div className="detail-body">
    <label className="field-label" htmlFor="draft-select">SELECT DRAFT</label><select id="draft-select" value={script.id} onChange={e => onSelect(e.target.value)} disabled={editing || busy}>{scripts.map(value => <option key={value.id} value={value.id}>{value.title} · {value.id.slice(0,8)}</option>)}</select>
    <div className="revision-toolbar"><div><label className="field-label" htmlFor="revision-select">REVISION HISTORY</label><select id="revision-select" value={history?.revision ?? 'latest'} onChange={e => {void browse(e.target.value);}} disabled={editing || busy}><option value="latest">Latest · revision {script.revision}</option>{script.versions.map(value => <option key={value.revision} value={value.revision}>Revision {value.revision} · {value.editor}</option>)}</select></div><span className="pill">{shown.engine}</span></div>
    {historyError && <p role="alert">{historyError}</p>}{history && <div className="review-note"><History size={14}/>Viewing immutable revision {history.revision}. Select Latest to edit or approve.</div>}
    <div className="script-heading"><h2>{shown.title}</h2><span className="pill amber">{nice(shown.label)}</span></div><div className="script-meta"><span><Clock3 size={14}/>~{shown.estimated_seconds}s estimated · no audio yet</span><span>{date(shown.source_issued_at)}</span></div>
    {!editing ? <><article className="script-text">{shown.text.split('\n\n').map((paragraph, i) => <p key={i}>{paragraph}</p>)}</article>{!history && <button className="button secondary" disabled={busy} onClick={() => {setText(script.text); setBaseRevision(script.revision); setEditing(true);}}><Pencil size={15}/>Edit narration</button>}</> : <div className="narration-edit">
      {script.revision !== baseRevision && <p className="feed-error">A newer revision is available. Your unsaved text is preserved; reload the latest revision before saving.</p>}
      <label className="field-label" htmlFor="narration-text">NARRATION TEXT</label><textarea id="narration-text" value={text} onChange={e => setText(e.target.value)} rows={18}/><p className="muted">Separate paragraphs with a blank line. Preserve the opening source context. Edited claims require source support.</p>
      <div className="editor-fields"><div><label className="field-label" htmlFor="revision-editor">EDITOR NAME</label><input id="revision-editor" value={editor} onChange={e => setEditor(e.target.value)}/></div><div><label className="field-label" htmlFor="revision-note">REVISION NOTE</label><input id="revision-note" value={note} onChange={e => setNote(e.target.value)}/></div></div>
      <div className="editor-actions"><button className="button primary" disabled={busy || editor.trim().length < 2 || note.trim().length < 3 || text.trim().length < 50 || text === script.text} onClick={() => {void save();}}><Save size={15}/>Save new revision</button><button className="button secondary" disabled={busy} onClick={() => setEditing(false)}><X size={15}/>Discard edits</button></div>
    </div>}
    <div className="references"><label className="field-label">SOURCE REFERENCES</label>{shown.evidence_manifest.map(item => <div className="script-source" key={item.id}><strong>{item.id}</strong><small>{date(item.issued_at)} · {item.provenance}</small>{item.source_url.startsWith('https://') ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}<ExternalLink size={12}/></a> : <span>{item.source_url} · synthetic fixture</span>}<code>SHA-256 {item.checksum}</code></div>)}</div>
    {!editing && <div className="claims-panel"><h3><ShieldCheck size={16}/>Claim support</h3><p className="muted">Every narration paragraph retains its evidence. Human attestations are recorded separately from generated source-backed text.</p>{shown.claims.map((claim, i) => <ClaimCard key={claim.id + ':' + shown.revision + ':' + i} claim={claim} script={shown} name={reviewer} busy={busy} onMutation={onMutation}/>)}</div>}
    <details className="version-audit"><summary><History size={15}/>Revision audit trail</summary>{script.versions.map(value => <div key={value.revision}><strong>Revision {value.revision} · {value.editor}</strong><p>{value.note}</p><small>{date(value.created_at)}</small></div>)}</details>
  </div> : <div className="empty"><FileText size={30}/><h3>Your first draft starts with evidence</h3><p>Select an advisory in Weather Intelligence or run the AI Newsroom to create a source-linked script.</p></div>}</section>
  <aside className="panel review-panel"><div className="panel-header"><h2><ShieldCheck size={17}/>Editorial gate</h2></div>{shown ? <div className="detail-body"><span className={'pill ' + (shown.review_valid ? 'green' : 'amber')}>{nice(shown.status)} · v{shown.revision}</span><p className="muted">Approval applies to this exact revision and source evidence. Source updates and expiry invalidate approval; edits always clear it.</p>{shown.editorial.high_impact && <div className="review-note">High-impact information requires careful human review of official emergency guidance and forecast uncertainty.</div>}
    <div className="qc-list">{shown.qc.map(check => <div key={check.check}>{check.passed ? <CheckCheck size={17} className="teal"/> : <Clock3 size={17} className="amber"/>}{check.check}</div>)}</div>
    <div className="editorial-issues">{shown.editorial.issues.map((issue, i) => <p className={issue.blocking ? 'blocking' : ''} key={i}><strong>{issue.blocking ? 'BLOCKED' : 'CHECK'}</strong>{issue.message}</p>)}</div>
    <label className="field-label" htmlFor="reviewer">REVIEWER NAME</label><input id="reviewer" value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="Your name"/><label className="field-label" htmlFor="review-note">EDITORIAL REVIEW NOTE</label><textarea id="review-note" rows={3} value={reviewNote} onChange={e => setReviewNote(e.target.value)} placeholder="Attribution, emergency guidance, timing, uncertainty…"/>
    <button className="button primary full" disabled={busy || !!history || editing || reviewer.trim().length < 2} onClick={() => {void onMutation(`/scripts/${shown.id}/review`, {expected_revision:shown.revision, reviewer:reviewer.trim(), note:reviewNote.trim()}, 'Editorial review recorded for this revision. Media production remains a separate gate.');}}><ShieldCheck size={16}/>Record editorial review</button>
    <div className="review-note">No draft can enter a live queue in this milestone. Rendering and broadcast admission are not connected.</div><a className="button secondary full" href={`/api/scripts/${shown.id}/scenes.csv?revision=${shown.revision}`} download><Download size={15}/>Export scene plan CSV</a><small className="muted">{shown.scenes.length} source-linked scenes · estimated timing</small>
    <div className="review-history"><h3>Recorded reviews</h3>{script?.reviews.length ? script.reviews.map(review => <div key={review.id}><strong>{review.reviewer} · revision {review.revision}</strong><p>{review.note || 'Named editorial approval'}</p><small>{date(review.created_at)}</small></div>) : <p className="muted">No named review recorded.</p>}</div>
  </div> : <div className="empty"><ShieldCheck size={30}/><h3>Awaiting a draft</h3><p>Quality checks appear after script generation.</p></div>}</aside></div>;
}
