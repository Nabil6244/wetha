import {useMemo, useState} from 'react';
import type {MediaCatalog} from './MediaCatalogEditor';

// Each category is saved as the hazard tags the footage selector's hazard gate already reads, so a flood clip
// can only be placed on flood or tropical beats, never on a tornado or winter story.
export const CATEGORIES: Record<string, string[]> = {
  'Hurricane': ['hurricane', 'wind', 'rain'], 'Tropical storm': ['tropical storm', 'wind', 'rain'], 'Flood': ['flood'],
  'Flash flood': ['flash flood', 'flood'], 'Severe thunderstorm': ['severe thunderstorm', 'storm'], 'Lightning': ['lightning'],
  'Hail': ['hail'], 'Tornado': ['tornado'], 'Storm surge': ['storm surge', 'flood', 'waves'], 'Winter weather': ['snow'], 'Ice storm': ['ice'],
  'Wildfire': ['wildfire'], 'Drought': ['drought'], 'General weather': ['sky'],
};
type Certainty = 'unknown' | 'declared' | 'verified';

interface Clip {
  id: string; name: string; kind: string; context: string; license: string; attribution: string; source: string;
  seconds: number | null; width: number | null; height: number | null; catalog?: MediaCatalog; quarantined?: {reason: string};
}
interface Upload {name: string; status: 'waiting' | 'uploading' | 'added' | 'duplicate' | 'failed'; message?: string}

export function categoryOf(tags: string[] = []): string {
  // The most specific category whose tags the clip carries (Flash flood before Flood, Storm surge before Flood).
  const matches = Object.entries(CATEGORIES).filter(([, wanted]) => wanted.every(t => tags.includes(t)));
  return matches.sort((a, b) => b[1].length - a[1].length)[0]?.[0] ?? '';
}

function certaintyOf(catalog?: MediaCatalog): Certainty {
  return catalog?.location_reviewed ? 'verified' : (catalog?.location ?? '').trim() ? 'declared' : 'unknown';
}

function catalogFor(base: MediaCatalog | undefined, category: string, extra: string[], location: string, regions: string[], certainty: Certainty, reference: string): MediaCatalog {
  // Every tag the editor kept is saved; a hazard tag that belongs to another category is never dropped silently.
  const tags = Array.from(new Set([...(CATEGORIES[category] ?? []), ...extra]));
  return {tags, event_id: base?.event_id ?? '', captured_at: base?.captured_at ?? null, preferred_trim_start: base?.preferred_trim_start ?? 0,
    setting_cleared: base?.setting_cleared ?? false, setting_note: base?.setting_note ?? '',
    location: certainty === 'unknown' ? '' : location, region_codes: certainty === 'unknown' ? [] : regions,
    location_reviewed: certainty === 'verified', reference: certainty === 'verified' ? reference : (base?.reference ?? '')};
}

async function saveCatalog(id: string, catalog: MediaCatalog) {
  const response = await fetch(`/api/production/media/${id}/catalog`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(catalog)});
  if (!response.ok) {const result = await response.json(); throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save the footage details.');}
}

function LocationFields({regions, location, setLocation, codes, setCodes, certainty, setCertainty, reference, setReference}: {
  regions: {code: string; name: string}[]; location: string; setLocation: (v: string) => void; codes: string[]; setCodes: (v: string[]) => void;
  certainty: Certainty; setCertainty: (v: Certainty) => void; reference: string; setReference: (v: string) => void;
}) {
  return <>
    <label>LOCATION<select aria-label="Location certainty" value={certainty} onChange={e => setCertainty(e.target.value as Certainty)}>
      <option value="unknown">Unknown</option><option value="declared">Declared, not verified</option><option value="verified">Verified with a source</option></select></label>
    {certainty !== 'unknown' && <>
      <label>PLACE<input aria-label="Place filmed" placeholder="e.g. Fort Myers Beach, Florida" value={location} onChange={e => setLocation(e.target.value)}/></label>
      <label>STATE / REGION<select aria-label="State filmed" value={codes[0] ?? ''} onChange={e => setCodes(e.target.value ? [e.target.value] : [])}>
        <option value="">Choose a state</option>{regions.map(r => <option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
    </>}
    {certainty === 'verified' && <label className="span-two">LOCATION EVIDENCE URL<input aria-label="Location evidence URL" placeholder="https://… page that documents where it was filmed" value={reference} onChange={e => setReference(e.target.value)}/></label>}
  </>;
}

function ClipCard({clip, regions, busy, run}: {clip: Clip; regions: {code: string; name: string}[]; busy: boolean; run: (label: string, task: () => Promise<void>) => void}) {
  const tags = clip.catalog?.tags ?? [];
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(categoryOf(tags));
  const [extra, setExtra] = useState(tags.filter(t => !(CATEGORIES[categoryOf(tags)] ?? []).includes(t)).join(', '));
  const [certainty, setCertainty] = useState<Certainty>(certaintyOf(clip.catalog));
  const [location, setLocation] = useState(clip.catalog?.location ?? '');
  const [codes, setCodes] = useState<string[]>(clip.catalog?.region_codes ?? []);
  const [reference, setReference] = useState(clip.catalog?.reference ?? '');
  const label = {unknown: 'Location unknown', declared: 'Location declared, not verified', verified: 'Location verified'}[certaintyOf(clip.catalog)];
  return <div className="production-media-card" aria-label={`Footage ${clip.name}`}>
    <video controls preload="metadata" src={`/api/production/media/${clip.id}/file`} style={{width: '100%', maxHeight: 200}}/>
    <strong>{clip.name}</strong>
    <p className="muted">{categoryOf(tags) || 'No category'} · {clip.seconds ? `${clip.seconds.toFixed(1)} s` : 'duration unknown'}{clip.width ? ` · ${clip.width}×${clip.height}` : ''} · {label}{clip.catalog?.location ? ` · ${clip.catalog.location}` : ''}</p>
    <p className="muted">{clip.context} · {clip.attribution} · {clip.license}</p>
    {clip.quarantined ? <>
      <p className="review-note">Removed from the library ({clip.quarantined.reason}). The file is kept and can be restored.</p>
      <button className="button secondary" disabled={busy} onClick={() => run('Restoring clip', async () => {
        const response = await fetch(`/api/production/media/${clip.id}/restore`, {method: 'POST'});
        if (!response.ok) throw new Error('Could not restore this clip.');})}>Restore to library</button>
    </> : <>
      <button className="text-button" onClick={() => setEditing(!editing)}>{editing ? 'Close' : 'Edit details'}</button>
      <button className="text-button" disabled={busy} onClick={() => {
        if (!window.confirm(`Remove “${clip.name}” from the footage library? The file is kept, not deleted, and you can restore it.`)) return;
        run('Removing clip from the library', async () => {
          const response = await fetch(`/api/production/media/${clip.id}/quarantine`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({reason: 'Removed from the footage library by the editor'})});
          if (!response.ok) {const result = await response.json(); throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not remove this clip.');}
        });}}>Remove from library</button>
    </>}
    {editing && !clip.quarantined && <form className="production-fields" onSubmit={e => {e.preventDefault(); run('Saving footage details', async () => {
      await saveCatalog(clip.id, catalogFor(clip.catalog, category, extra.split(',').map(t => t.trim().toLowerCase()).filter(Boolean), location, codes, certainty, reference));
      setEditing(false);});}}>
      <label>CATEGORY<select aria-label="Footage category" value={category} onChange={e => setCategory(e.target.value)}><option value="">No category</option>{Object.keys(CATEGORIES).map(c => <option key={c}>{c}</option>)}</select></label>
      <label>VISIBLE CONTENT TAGS<input aria-label="Visible content tags" placeholder="waves, debris, flooded road" value={extra} onChange={e => setExtra(e.target.value)}/></label>
      <LocationFields {...{regions, location, setLocation, codes, setCodes, certainty, setCertainty, reference, setReference}}/>
      <button className="button secondary" disabled={busy}>Save details</button>
    </form>}
  </div>;
}

export default function ManualFootageLibrary({media, regions, maxBytes, reload}: {
  media: Clip[]; regions: {code: string; name: string}[]; maxBytes: number; reload: () => Promise<void>;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [category, setCategory] = useState('');
  const [extra, setExtra] = useState('');
  const [context, setContext] = useState<'illustrative' | 'archival'>('illustrative');
  const [license, setLicense] = useState('');
  const [attribution, setAttribution] = useState('');
  const [source, setSource] = useState('');
  const [rights, setRights] = useState(false);
  const [certainty, setCertainty] = useState<Certainty>('unknown');
  const [location, setLocation] = useState('');
  const [codes, setCodes] = useState<string[]>([]);
  const [reference, setReference] = useState('');
  const [query, setQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterRegion, setFilterRegion] = useState('');
  const [showRemoved, setShowRemoved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  function run(label: string, task: () => Promise<void>) {
    setBusy(true);setError('');
    void task().then(reload).catch(e => setError(`${label}: ${e instanceof Error ? e.message : String(e)}`)).finally(() => setBusy(false));
  }

  async function uploadAll() {
    const rows: Upload[] = files.map(f => ({name: f.name, status: 'waiting'}));
    setUploads([...rows]);
    for (const [index, file] of files.entries()) {
      const update = (row: Partial<Upload>) => {rows[index] = {...rows[index], ...row}; setUploads([...rows]);};
      if (file.size > maxBytes) {update({status: 'failed', message: `larger than ${Math.round(maxBytes / 1048576)} MiB`}); continue;}
      update({status: 'uploading'});
      try {
        const metadata = {name: file.name, kind: 'video', context, license, attribution, source, rights_confirmed: rights, source_provider: 'local'};
        // The file is streamed; the server writes it to a temporary file and only adds it once it is complete and decodable.
        const response = await fetch('/api/production/media', {method: 'POST', body: file, signal: AbortSignal.timeout(Math.max(180000, file.size / 1000)),
          headers: {'Content-Type': 'application/octet-stream', 'X-Media-Metadata': encodeURIComponent(JSON.stringify(metadata))}});
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Upload failed');
        if (result.duplicate) {update({status: 'duplicate', message: `already in the library as “${result.name}”; its details were kept`}); continue;}
        await saveCatalog(result.id, catalogFor(undefined, category, extra.split(',').map(t => t.trim().toLowerCase()).filter(Boolean), location, codes, certainty, reference));
        update({status: 'added'});
      } catch (e) {update({status: 'failed', message: e instanceof Error ? e.message : String(e)});}
    }
    setFiles([]);await reload();
  }

  const videos = useMemo(() => media.filter(m => m.kind === 'video' && (showRemoved || !m.quarantined)).filter(m => {
    const tags = m.catalog?.tags ?? [];
    const text = [m.name, m.attribution, m.catalog?.location ?? '', ...tags].join(' ').toLowerCase();
    return (!query || text.includes(query.toLowerCase())) && (!filterCategory || categoryOf(tags) === filterCategory)
      && (!filterRegion || (m.catalog?.region_codes ?? []).includes(filterRegion));
  }), [media, query, filterCategory, filterRegion, showRemoved]);

  return <section className="panel" aria-label="Footage library">
    <div className="panel-header"><h2>Footage library</h2><span className="pill">{media.filter(m => m.kind === 'video' && !m.quarantined).length} clips · kept in the app's data folder</span></div>
    <div className="detail-body">
      <form className="production-fields" onSubmit={e => {e.preventDefault(); if (!files.length) {setError('Choose one or more video files.'); return;} void uploadAll();}}>
        <label className="span-two">VIDEO FILES<input aria-label="Footage files" type="file" multiple accept=".mp4,.mov,.mkv,.webm" onChange={e => setFiles(Array.from(e.target.files ?? []))}/></label>
        <label>CATEGORY<select aria-label="Upload category" value={category} onChange={e => setCategory(e.target.value)}><option value="">Choose a category</option>{Object.keys(CATEGORIES).map(c => <option key={c}>{c}</option>)}</select></label>
        <label>VISIBLE CONTENT TAGS<input aria-label="Upload content tags" placeholder="waves, debris, flooded road" value={extra} onChange={e => setExtra(e.target.value)}/></label>
        <label>USE<select aria-label="Footage use" value={context} onChange={e => setContext(e.target.value as 'illustrative' | 'archival')}><option value="illustrative">Illustrative (not the reported event)</option><option value="archival">Archival (a dated past event)</option></select></label>
        <LocationFields {...{regions, location, setLocation, codes, setCodes, certainty, setCertainty, reference, setReference}}/>
        <label>LICENSE / USAGE TERMS<input aria-label="Upload license" required minLength={3} placeholder="e.g. Filmed by me" value={license} onChange={e => setLicense(e.target.value)}/></label>
        <label>ATTRIBUTION<input aria-label="Upload attribution" required minLength={2} placeholder="Creator or rights holder" value={attribution} onChange={e => setAttribution(e.target.value)}/></label>
        <label className="span-two">SOURCE<input aria-label="Upload source" required minLength={2} placeholder="Where the footage came from" value={source} onChange={e => setSource(e.target.value)}/></label>
        <label className="span-two"><input type="checkbox" checked={rights} onChange={e => setRights(e.target.checked)}/> I have the right to use these videos</label>
        <button className="button" disabled={busy || !category || !rights}>Upload {files.length || ''} {files.length === 1 ? 'video' : 'videos'}</button>
      </form>
      {uploads.length > 0 && <ul aria-label="Upload progress">{uploads.map(u => <li key={u.name}>{u.name} · {u.status}{u.message ? ` · ${u.message}` : ''}</li>)}</ul>}
      {error && <p className="production-error" role="alert">{error}</p>}
      <div className="production-fields">
        <label>SEARCH<input aria-label="Search footage" placeholder="name, tag or place" value={query} onChange={e => setQuery(e.target.value)}/></label>
        <label>CATEGORY<select aria-label="Filter category" value={filterCategory} onChange={e => setFilterCategory(e.target.value)}><option value="">All</option>{Object.keys(CATEGORIES).map(c => <option key={c}>{c}</option>)}</select></label>
        <label>STATE<select aria-label="Filter state" value={filterRegion} onChange={e => setFilterRegion(e.target.value)}><option value="">All</option>{regions.map(r => <option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
        <label><input type="checkbox" checked={showRemoved} onChange={e => setShowRemoved(e.target.checked)}/> Show removed clips</label>
      </div>
      <p className="muted">{videos.length} shown. Video production picks from this library automatically when a clip's category fits the story's hazard; a clip of another hazard is never used, and an unverified location is never shown as verified. Dated archive footage carries its event and date on screen; every clip's source and location status is listed in the production report.</p>
      <div className="production-media-grid">{videos.map(clip => <ClipCard key={clip.id + JSON.stringify(clip.catalog) + (clip.quarantined ? 'q' : '')} clip={clip} regions={regions} busy={busy} run={run}/>)}</div>
    </div>
  </section>;
}
