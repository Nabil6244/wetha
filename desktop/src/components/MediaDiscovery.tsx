import {useEffect, useState} from 'react';
import {api} from '../api';

interface Candidate {
  id: string; title: string; kind: 'video' | 'image'; provider: string; context: string;
  download_url: string; source: string; catalogue_url: string; thumbnail_url?: string;
  license: string; attribution: string; description: string; declared_date?: string;
  match_reasons: string[]; local_media_id?: string; event_id?: string; location?: string;
}
interface Results {query: string; results: Candidate[]; warnings: string[]; links: {pexels: string; youtube: string; commons: string}; note: string}
interface Plan {id: string; script_id: string; scenes: {script_segment: string;regional_targets?:string[]}[]}

export default function MediaDiscovery({plans, scriptNames, imported, regions, requestedSearch}: {
  requestedSearch?:{query:string;planId:string};
  regions: {code:string;name:string}[]; plans: Plan[]; scriptNames: Record<string, string>; imported: () => Promise<void>;
}) {
  const [query, setQuery] = useState('storm rain waves');
  const [provider, setProvider] = useState('all');
  const [kind, setKind] = useState('video');
  const [planId, setPlanId] = useState('');
  const [live, setLive] = useState(true);
  const [results, setResults] = useState<Results | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [rights, setRights] = useState<Record<string, boolean>>({});
  useEffect(()=>{if(requestedSearch){setQuery(requestedSearch.query);setPlanId(requestedSearch.planId);setResults(null);}},[requestedSearch]);
  useEffect(() => {void api<Results>('/production/discovery').then(setResults).catch(e => setError(e.message));}, []);
  async function search() {
    setBusy(true); setError(''); setNotice(''); setRights({});
    try {setResults(await api<Results>('/production/discovery/search', {query, provider, kind, plan_id: planId || null, live}));}
    catch (e) {setError(e instanceof Error ? e.message : 'Search failed.');}
    finally {setBusy(false);}
  }
  async function acquire(candidate: Candidate) {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<{id: string; duplicate?: boolean}>('/production/discovery/import', {candidate_id: candidate.id, rights_confirmed: true});
      await imported();
      setNotice(result.duplicate ? 'This source is already in your media library.' : 'Source imported with credits, license and weather tags.');
      setResults(old => old ? {...old, results: old.results.map(row => row.id === candidate.id ? {...row, local_media_id: result.id} : row)} : old);
    } catch (e) {setError(e instanceof Error ? e.message : 'Import failed.');}
    finally {setBusy(false);}
  }
  return <section className="panel media-discovery"><div className="panel-header"><h2>Discover free weather footage</h2><span className="pill">No paid generation</span></div><div className="detail-body">
    <p className="muted">Search Wikimedia clips and images, including licensed YouTube-origin archives. Browse reviewed stock clips here or use the Pexels and YouTube search links for more sources.</p>
    <form onSubmit={e => {e.preventDefault(); void search();}}><div className="production-fields">
      <label>SEARCH WEATHER FOOTAGE<input aria-label="SEARCH WEATHER FOOTAGE" required minLength={2} maxLength={160} value={query} disabled={busy} onChange={e => setQuery(e.target.value)} placeholder="hurricane coastal waves"/></label>
      <label>SOURCE<select aria-label="DISCOVERY SOURCE" value={provider} disabled={busy} onChange={e => setProvider(e.target.value)}><option value="all">All available sources</option><option value="stock">Reviewed stock clips</option><option value="youtube">YouTube-origin licensed archives</option><option value="commons">Wikimedia Commons</option></select></label>
      <label>MEDIA<select aria-label="DISCOVERY MEDIA TYPE" value={kind} disabled={busy} onChange={e => setKind(e.target.value)}><option value="video">Video clips</option><option value="image">Stock images</option><option value="all">Clips and images</option></select></label>
      <label>MATCH TO PLAN<select aria-label="DISCOVERY SCENE PLAN" value={planId} disabled={busy} onChange={e => setPlanId(e.target.value)}><option value="">General weather search</option>{plans.map(plan => <option value={plan.id} key={plan.id}>{scriptNames[plan.script_id] ?? plan.script_id} · {plan.id.slice(0,6)}</option>)}</select></label>
    </div><div className="production-actions"><label className="production-check"><input type="checkbox" checked={live} disabled={busy} onChange={e => setLive(e.target.checked)}/>Include live Wikimedia search</label><button className="button secondary" type="button" disabled={busy || !planId} onClick={() => {
      const text = plans.find(p => p.id === planId)?.scenes.map(s => s.script_segment).join(' ') ?? '';
      const words = ['wind','rain','flood','waves','snow','lightning','storm','hurricane'].filter(word => text.toLowerCase().includes(word));
      const regionCodes = new Set(plans.find(p=>p.id===planId)?.scenes.flatMap(s=>s.regional_targets??[]) ?? []);
      const names=regions.filter(r=>regionCodes.has(r.code)).map(r=>r.name);
      setQuery([...names,...words].join(' ') || 'weather storm');
    }}>Use script weather topics</button><button className="button primary" disabled={busy}>Search free sources</button></div></form>
    {busy && <p role="status">Searching or importing source…</p>}{error && <p role="alert" className="production-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {results && <><p className="muted">{results.note}</p><div className="production-actions"><a className="button secondary" href={results.links.pexels} target="_blank" rel="noreferrer">Search Pexels</a><a className="button secondary" href={results.links.youtube} target="_blank" rel="noreferrer">Search YouTube</a><a className="button secondary" href={results.links.commons} target="_blank" rel="noreferrer">Search Wikimedia</a></div>{results.warnings.map(warning => <p role="alert" className="production-error" key={warning}>{warning}</p>)}
      {!results.results.length && <p>No importable matches found. Keep the location in your query and review sources using the search links.</p>}
      <div className="production-media-grid">{results.results.map(candidate => <article className="discovery-card" key={candidate.id}>
        {candidate.kind === 'video' ? <video controls preload="none" poster={candidate.thumbnail_url || undefined} src={candidate.local_media_id ? `/api/production/media/${candidate.local_media_id}/file` : candidate.download_url}/> : <img loading="lazy" src={candidate.local_media_id ? `/api/production/media/${candidate.local_media_id}/file` : candidate.thumbnail_url || candidate.download_url} alt={candidate.title}/>}
        <div><span className="pill">{candidate.provider} · {candidate.context}</span><h3>{candidate.title}</h3><p>{candidate.description}</p><p><strong>Credit:</strong> {candidate.attribution}</p><p><strong>License:</strong> {candidate.license}</p>{candidate.declared_date && <p><strong>Source-declared date:</strong> {candidate.declared_date}</p>}<p className="muted">{candidate.match_reasons.join(' · ')}</p><a href={candidate.source} target="_blank" rel="noreferrer">Original source</a>{candidate.catalogue_url !== candidate.source && <> · <a href={candidate.catalogue_url} target="_blank" rel="noreferrer">License archive</a></>}
          {candidate.local_media_id ? <p>Already in your media library</p> : <><label className="production-check"><input aria-label={`Review usage terms for ${candidate.title}`} type="checkbox" checked={!!rights[candidate.id]} disabled={busy} onChange={e => setRights(old => ({...old, [candidate.id]: e.target.checked}))}/>I reviewed the source and usage terms for this production.</label><button className="button secondary" disabled={busy || !rights[candidate.id]} onClick={() => {void acquire(candidate);}}>Import selected source</button></>}
        </div>
      </article>)}</div>
    </>}
  </div></section>;
}
