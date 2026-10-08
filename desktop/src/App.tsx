import { lazy, Suspense, useEffect, useState } from 'react';
import { Activity, ArrowDown, ArrowRight, ArrowUp, AudioLines, Bell, Check, CheckCheck, ChevronDown, Clapperboard, Clock3, CloudSun, Database, Download, ExternalLink, FileText, FolderOpen, Globe2, LayoutDashboard, LoaderCircle, MonitorPlay, Play, Plus, Radio, RefreshCw, Satellite, Settings2, ShieldCheck, Sparkles, SquareArrowOutUpRight, Tv, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { api } from './api';
import type { Advisory, Dashboard, Health, Script, Feed } from './contracts';
import WeatherDesk from './components/WeatherDesk';
import Newsroom from './components/Newsroom';
import ScriptEditor from './components/ScriptEditor';
const VisualDirector = lazy(() => import('./components/VisualDirector'));

type Page = 'Dashboard' | 'Weather Intelligence' | 'AI Newsroom' | 'Script Editor' | 'Voice Studio' | 'Visual Director' | 'Media Library' | 'Video Production' | 'Broadcast Scheduler' | 'OBS Controller' | 'Channel Manager' | 'Settings';
const groups: {label: string; links: [Page, LucideIcon][]}[] = [
  {label: 'WORKSPACE', links: [['Dashboard', LayoutDashboard], ['Weather Intelligence', Globe2], ['AI Newsroom', Sparkles], ['Script Editor', FileText]]},
  {label: 'PRODUCTION', links: [['Voice Studio', AudioLines], ['Visual Director', Satellite], ['Media Library', FolderOpen], ['Video Production', Clapperboard]]},
  {label: 'ON AIR', links: [['Broadcast Scheduler', Clock3], ['OBS Controller', Radio], ['Channel Manager', Tv]]},
];
const phaseInfo: Partial<Record<Page, {phase: string; description: string; requirements: string[]}>> = {
  'Voice Studio': {phase:'Phase 5', description:'A local narration pipeline with WAV preview, normalization, pronunciation controls, and actual audio alignment.', requirements:['Install and verify a commercially compatible local voice model', 'Generate audio from an approved, source-linked script', 'Measure timing with FFprobe before scene assembly']},

  'Media Library': {phase:'Phase 5', description:'A reusable collection of footage with provenance, licenses, tags, and duplicate detection.', requirements:['Local import with video validation', 'License record required for each asset', 'Explicit archival labels and scene relevance checks']},
  'Video Production': {phase:'Phase 5', description:'Independent render jobs that produce validated 1080p programs without interrupting the broadcast process.', requirements:['Actual narration and rights-cleared visual assets', 'FFmpeg scene rendering, assembly, and resumable job state', 'Audio, duration, black-frame, and output quality checks']},
  'Broadcast Scheduler': {phase:'Phase 6', description:'Hourly programming with next-program readiness, safe transitions, and a tested fallback.', requirements:['A rendered program that passes media and editorial checks', 'An evergreen emergency fallback program', 'Expiry checks at admission and playback, with manual override']},
  'OBS Controller': {phase:'Phase 6', description:'A separate broadcast watchdog connected to your own OBS Studio instance.', requirements:['OBS Studio with authenticated WebSocket access', 'Explicit operator action to connect and start a stream', '24-hour continuity test before an unattended operation claim']},
};
const nice = (s: string) => s.replaceAll('_', ' ').replaceAll('nhc', 'NHC').replaceAll('nws', 'NWS');
const date = (s: string) => new Date(s).toLocaleString('en-US', {month:'short', day:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', timeZone:'UTC', hour12:false}) + ' UTC';

function Pill({children, tone = ''}: {children: React.ReactNode; tone?: string}) { return <span className={'pill ' + tone}>{children}</span>; }
function Empty({icon: Icon, title, children}: {icon: LucideIcon; title: string; children: React.ReactNode}) { return <div className="empty"><Icon size={30}/><h3>{title}</h3><p>{children}</p></div>; }

export default function App() {
  const [page, setPage] = useState<Page>('Dashboard');
  const [data, setData] = useState<Dashboard | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string>('');
  const [scriptId, setScriptId] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [paste, setPaste] = useState(false);
  const [sourceUrl, setSourceUrl] = useState('https://www.nhc.noaa.gov/archive/2024/al14/al142024.public.013.shtml');
  const [sourceText, setSourceText] = useState('');

  async function refresh() {
    const [dashboard, currentHealth] = await Promise.all([api<Dashboard>('/dashboard'), api<Health>('/health')]);
    setData(dashboard); setHealth(currentHealth);
  }
  useEffect(() => { void refresh().catch(e => setError(e.message)); const timer = setInterval(() => { void refresh().catch(() => {}); }, 15000); return () => clearInterval(timer); }, []);
  async function action(label: string, work: () => Promise<void>) {
    setBusy(label); setError(''); setNotice('');
    try { await work(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : 'Operation failed'); } finally { setBusy(''); }
  }
  const advisory: Advisory | undefined = data?.advisories.find(a => a.id === selected) ?? data?.advisories[0];
  const script: Script | undefined = data?.scripts.find(s => s.id === scriptId) ?? data?.scripts[0];
  const officialCount = data?.advisories.filter(a => a.provenance === 'official_fetch').length ?? 0;
  const draft = (item: Advisory) => action('Drafting script', async () => { const result = await api<Script>('/scripts', {advisory_id:item.id}); setScriptId(result.id); setPage('Script Editor'); setNotice('Source-linked draft created. Editorial review is required.'); });

  function sourceLink(item: Advisory) { return item.source_url.startsWith('https://') ? <a href={item.source_url} target="_blank" rel="noreferrer">Official source <ExternalLink size={12}/></a> : <span className="muted">Synthetic fixture · no official source</span>; }
  function advisoryRows(limit?: number) {
    const items = limit ? data?.advisories.slice(0, limit) : data?.advisories;
    if (!items?.length) return <Empty icon={Globe2} title="Your evidence desk is clear">Refresh official NWS alerts or import an NHC advisory to begin. You can also explore with the labeled training dataset.</Empty>;
    return <div className="event-list">{items.map(item => <button key={item.id} className={'event-row ' + (item.id === advisory?.id ? 'selected' : '')} onClick={() => {setSelected(item.id); setPage('Weather Intelligence');}}>
      <span className={'event-symbol ' + (item.freshness === 'current' ? 'current' : '')}><CloudSun size={20}/></span>
      <span className="event-copy"><strong>{item.title}</strong><small>{item.provider} · {date(item.issued_at)}{item.area && ' · ' + item.area}</small></span>
      <Pill tone={item.freshness === 'current' ? 'green' : 'amber'}>{item.freshness}</Pill><ArrowRight size={16}/>
    </button>)}</div>;
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><AudioLines size={25}/></span><div>WEATHER<span>INTELLIGENCE STUDIO</span></div></div>
      <button className="channel-switch" onClick={() => setPage('Channel Manager')}><span className="channel-icon"><CloudSun size={18}/></span><span><strong>US Extreme Weather</strong><small>CHANNEL 01</small></span><ChevronDown size={14}/></button>
      <nav>{groups.map(group => <div className="nav-group" key={group.label}><label>{group.label}</label>{group.links.map(([name, Icon]) => <button key={name} aria-label={name} className={page === name ? 'active' : ''} onClick={() => setPage(name)}><Icon size={18}/><span>{name}</span>{name === 'AI Newsroom' && <span className="nav-count" aria-hidden="true">6</span>}</button>)}</div>)}</nav>
      <div className="sidebar-bottom"><div className="local-status"><span className={'dot ' + (health ? 'green' : 'amber')}/><span>{health ? 'Local service connected' : 'Connecting to local service'}</span></div><button className={page === 'Settings' ? 'active' : ''} onClick={() => setPage('Settings')}><Settings2 size={18}/>Settings<span className="version">v0.4</span></button><div className="operator"><span>WS</span><div>Local workspace<small>Phase 4 · visual engine</small></div><ShieldCheck size={17}/></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="breadcrumb">Studio <span>/</span> <strong>{page}</strong></div><div className="topbar-right"><span className="offline"><span className="dot"/>Broadcast offline</span><span className="top-separator"/><button className="icon-button" aria-label="Show operation log" onClick={() => setPage('AI Newsroom')}><Bell size={18}/>{data?.jobs.some(j => j.status === 'failed') && <i/>}</button><span className="avatar">WS</span></div></header>
      <main>
        <div className="page-heading"><div><span className="eyebrow">{page === 'Dashboard' ? 'YOUR WEATHER OPERATIONS, IN FOCUS' : 'WEATHER INTELLIGENCE STUDIO'}</span><h1>{page === 'Dashboard' ? 'Control center' : page}</h1><p>{page === 'Dashboard' ? 'From official evidence to the next story. Every source, every step.' : page === 'Weather Intelligence' ? 'Collect official advisories. Preserve evidence. Understand what changed.' : page === 'AI Newsroom' ? 'Six editorial roles. Structured evidence. Human oversight.' : page === 'Script Editor' ? 'Source-grounded narration, with an explicit editorial gate.' : 'One channel. A clear path from evidence to broadcast.'}</p></div><div className="heading-actions"><button className="button secondary" disabled={!!busy} onClick={() => action('Refreshing sources', async () => {const result = await api<{feeds:{feed:string; collected?:number; rejected?:number; error?:string}[]}>('/sources/refresh', {}); const failures = result.feeds.filter(feed => feed.error); setNotice(result.feeds.map(feed => feed.error ? `${feed.feed.toUpperCase()}: collection failed — inspect source status` : `${feed.feed.toUpperCase()}: ${feed.collected} valid advisories, ${feed.rejected} quarantined`).join(' · ')); if(failures.length) setError(failures.map(feed => feed.error).join(' · '));})}><RefreshCw size={15} className={busy === 'Refreshing sources' ? 'spin' : ''}/>Refresh sources</button><button className="button primary" onClick={() => setImportOpen(true)}><Plus size={16}/>Import advisory</button></div></div>
        {error && <div role="alert" className="message error"><Bell size={16}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {notice && <div role="status" className="message success"><Check size={16}/><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={16}/></button></div>}
        {busy && <div role="status" className="working"><LoaderCircle size={15} className="spin"/>{busy}…</div>}
        {!data ? <div className="panel"><Empty icon={Database} title="Connecting to your workspace">The local Python service provides your data. Run npm run dev to start both services.</Empty></div> : <>
        {page === 'Dashboard' && <>
          <div className="stats">{[
            {icon:Globe2, label:'CURRENT OFFICIAL ALERTS', value:data.stats.current_alerts, footer:officialCount ? 'Freshness checked at source time' : 'No official sources collected', tone:'teal'},
            {icon:Database, label:'STORED ADVISORIES', value:data.stats.stored_advisories, footer:'Persistent, deduplicated evidence', tone:'blue'},
            {icon:FileText, label:'NEWSROOM DRAFTS', value:data.stats.scripts, footer:'Human review before production', tone:'amber'},
            {icon:MonitorPlay, label:'BROADCAST-READY PROGRAMS', value:0, footer:'Production pipeline not connected', tone:'purple'},
          ].map(stat => <div className="stat-card" key={stat.label}><div className="stat-top"><span>{stat.label}</span><stat.icon size={18} className={stat.tone}/></div><strong>{stat.value.toString().padStart(2, '0')}</strong><small><span className={'tiny-square ' + stat.tone}/>{stat.footer}</small></div>)}</div>
          <div className="dashboard-grid"><section className="panel evidence-panel"><div className="panel-header"><h2><Satellite size={17}/>Intelligence desk</h2><Pill>Evidence first</Pill></div><div className="desk-hero"><div className="desk-grid" aria-hidden="true"/><div className="hero-copy"><span className="eyebrow teal">OFFICIAL DATA → ORIGINAL REPORTING</span><h2>A better story starts<br/>with the source.</h2><p>Collect, compare, and explain weather developments without losing their provenance.</p><button className="button primary" onClick={() => setPage('Weather Intelligence')}>Open intelligence desk<ArrowRight size={16}/></button></div><div className="orbital" aria-hidden="true"><div className="orbit orbit-a"/><div className="orbit orbit-b"/><div className="orbit orbit-c"/><Satellite size={36}/><span className="orbit-point point-a"/><span className="orbit-point point-b"/><span className="orbit-label">SOURCE / TIME / EVIDENCE</span></div></div><div className="desk-foot"><span><ShieldCheck size={14}/>No simulated weather presented as observations</span><span>PHASE 04</span></div></section>
          <section className="panel next-program"><div className="panel-header"><h2><MonitorPlay size={17}/>Next program</h2><Pill tone="amber">Not scheduled</Pill></div><div className="program-placeholder"><span className="program-icon"><Play size={25}/></span><span className="eyebrow">PRODUCTION STANDBY</span><h3>Your next hour<br/>starts here.</h3><p>Create a source-linked draft first. Audio, rendering, and broadcast will follow in later milestones.</p></div><div className="program-steps"><span className="done">01 Evidence</span><span>02 Editorial</span><span>03 Production</span></div></section>
          <section className="panel events-panel"><div className="panel-header"><h2><Activity size={17}/>Weather evidence</h2><button className="text-button" onClick={() => setPage('Weather Intelligence')}>View all<ArrowRight size={14}/></button></div>{advisoryRows(4)}<div className="panel-footer"><span>Issue timestamps are retained in every draft.</span><button className="text-button" disabled={!!busy} onClick={() => action('Loading training data', async () => {await api('/training/load', {}); setNotice('Synthetic training dataset loaded. It is not real weather and cannot pass broadcast review.');})}>Load training dataset<ArrowRight size={14}/></button></div></section>
          <section className="panel agents-panel"><div className="panel-header"><h2><Sparkles size={17}/>Newsroom roles</h2><span className="muted small">LOCAL WORKFLOW</span></div><div className="agent-list">{data.agents.map((agent, i) => <div key={agent.name}><span className="agent-number">0{i + 1}</span><span>{agent.name}</span><Pill tone={['ready', 'succeeded'].includes(agent.status) ? 'green' : agent.status === 'manual' ? 'amber' : ''}>{agent.status}</Pill></div>)}</div><div className="panel-footer"><span>Deterministic baseline · no paid AI API</span></div></section></div>
          <div className="safety-strip"><ShieldCheck size={20}/><div><strong>Editorial integrity is part of the workflow.</strong><span>Training fixtures, unverified imports, and stale advisories stay out of broadcast approval.</span></div><button className="text-button" onClick={() => setPage('Settings')}>Workspace status<ArrowRight size={14}/></button></div>
        </>}
        {page === 'Weather Intelligence' && <WeatherDesk advisories={data.advisories} intelligence={data.intelligence} advisory={advisory} busy={!!busy}
          onSelect={setSelected} onDraft={item => {void draft(item);}}
          onTraining={() => {void action('Loading training data', async () => {await api('/training/load', {}); setNotice('Training data loaded — not real observations.');});}}
          onPolling={(feed: Feed, enabled, interval) => {void action('Saving polling schedule', async () => {await api(`/feeds/${feed.id}/polling`, {enabled, interval_seconds:interval}); setNotice(`${feed.id.toUpperCase()} automatic collection ${enabled ? 'enabled' : 'paused'}. Settings persist across restarts.`);});}}
          onRefresh={feed => {void action(`Refreshing ${feed.id.toUpperCase()}`, async () => {const result = await api<{collected:number; rejected:number}>(`/providers/${feed.id}/refresh`, {}); setNotice(`${feed.id.toUpperCase()}: ${result.collected} valid advisories; ${result.rejected} quarantined.`);});}}/>}
        {page === 'AI Newsroom' && <Newsroom data={data} busy={!!busy}
          onRun={(item, engine, refresh_sources) => {void action('Running newsroom', async () => {const result = await api<Script>('/newsroom/runs', {advisory_id:item.id, engine, refresh_sources}); setScriptId(result.id); setNotice('Six newsroom roles completed. Inspect the JSON handoffs or open the draft for review.');});}}
          onOpen={id => {setScriptId(id); setPage('Script Editor');}}/>}
        {page === 'Script Editor' && <ScriptEditor key={script?.id ?? 'empty'} script={script} scripts={data.scripts} busy={!!busy} onSelect={setScriptId}
          onMutation={async (path, body, notice) => {let saved: Script | undefined; await action('Saving editorial work', async () => {saved = await api<Script>(path, body); setNotice(notice);}); return saved;}}/>}
        {page === 'Visual Director' && <Suspense fallback={<div className="panel"><p className="detail-body">Loading geographic workspace…</p></div>}><VisualDirector data={data}/></Suspense>}
        {phaseInfo[page] && <section className="panel roadmap-panel"><div className="panel-header"><h2>{page}</h2><Pill tone="amber">{phaseInfo[page]!.phase} · not connected</Pill></div><div className="roadmap-body"><span className="roadmap-icon"><Clapperboard size={32}/></span><span className="eyebrow teal">THE NEXT PRODUCTION MILESTONE</span><h2>{page === 'OBS Controller' ? 'Broadcast begins with a verified program.' : 'Built on a reliable evidence workflow.'}</h2><p>{phaseInfo[page]!.description}</p><div className="requirements">{phaseInfo[page]!.requirements.map((r, i) => <div key={r}><span>0{i+1}</span>{r}</div>)}</div><button className="button primary" onClick={() => setPage('Weather Intelligence')}>Prepare weather evidence<ArrowRight size={16}/></button></div></section>}
        {page === 'Channel Manager' && <section className="panel"><div className="panel-header"><h2>Channel profile</h2><Pill>Single-channel foundation</Pill></div><div className="detail-body"><div className="channel-profile"><span className="brand-mark"><CloudSun size={28}/></span><div><h2>{data.channel.name}</h2><p>United States · English (US)</p></div></div><div className="settings-rows"><div><span>Channel ID</span><code>{data.channel.id}</code></div><div><span>Target program length</span><strong>60 minutes · future production target</strong></div><div><span>Automatic broadcast</span><Pill tone="amber">Disabled</Pill></div><div><span>Voice profile / streaming credentials</span><strong>Not configured</strong></div></div><p className="muted">Profiles are isolated in persistent storage. This milestone prepares one channel; independent production and broadcast queues arrive in later phases.</p></div></section>}
        {page === 'Settings' && <div className="settings-grid"><section className="panel"><div className="panel-header"><h2>Runtime capabilities</h2><Pill tone="green">{health?.version}</Pill></div><div className="settings-rows">{Object.entries(health?.capabilities ?? {}).map(([name, available]) => <div key={name}><span>{nice(name)}</span><Pill tone={available ? 'green' : 'amber'}>{available ? 'Available' : 'Not configured'}</Pill></div>)}</div><div className="panel-footer">A binary being available does not mean its production integration is complete.</div></section><section className="panel"><div className="panel-header"><h2>Official source access</h2><ShieldCheck size={17}/></div><div className="detail-body"><p className="muted">Network access is checked when you fetch. Imported text retains unverified status, even when its reference points to an official domain.</p><div className="source-domain"><Globe2 size={16}/>api.weather.gov<span>NWS alerts</span></div><div className="source-domain"><Satellite size={16}/>www.nhc.noaa.gov<span>NHC advisories</span></div><div className="source-domain"><Satellite size={16}/>www.star.nesdis.noaa.gov<span>GOES · planned</span></div><p className="review-note">No paid API key is required for this milestone. Source issue times are displayed in UTC.</p></div></section></div>}
        </>}
        <footer className="workspace-footer"><span><span className="dot green"/>Weather Intelligence Studio · AI newsroom</span><span>Official evidence. Clear provenance. Editorial control.</span></footer>
      </main>
    </div>
    {importOpen && <div className="modal-backdrop" onClick={e => {if(e.target === e.currentTarget && !busy) setImportOpen(false);}}><section role="dialog" aria-modal="true" aria-labelledby="import-title" className="modal"><div className="panel-header"><h2 id="import-title">Import NHC advisory</h2><button className="icon-button" aria-label="Close import" disabled={!!busy} onClick={() => setImportOpen(false)}><X size={20}/></button></div><form onSubmit={e => {e.preventDefault(); void action(paste ? 'Importing advisory' : 'Fetching NHC advisory', async () => {const result = await api<{advisory:Advisory; inserted:boolean}>(paste ? '/advisories/import' : '/advisories/fetch', paste ? {text:sourceText, source_url:sourceUrl} : {source_url:sourceUrl}); setSelected(result.advisory.id); setPage('Weather Intelligence'); setImportOpen(false); setNotice(result.inserted ? 'Advisory stored with its original issue time and provenance.' : 'This advisory is already cached.');});}}><div className="modal-tabs"><button type="button" className={!paste ? 'chosen' : ''} onClick={() => setPaste(false)}><Download size={15}/>Fetch official archive</button><button type="button" className={paste ? 'chosen' : ''} onClick={() => setPaste(true)}><FileText size={15}/>Paste advisory text</button></div><p className="muted">{paste ? 'Manual imports are retained as unverified evidence. An official URL alone does not verify the pasted facts.' : 'Fetch a historical public advisory directly from the National Hurricane Center. The original timestamp is retained.'}</p><label className="field-label" htmlFor="source-url">OFFICIAL ARCHIVE URL</label><input id="source-url" type="url" required value={sourceUrl} onChange={e => setSourceUrl(e.target.value)}/>{paste && <><label className="field-label" htmlFor="source-text">COMPLETE PUBLIC ADVISORY TEXT</label><textarea id="source-text" required minLength={100} value={sourceText} onChange={e => setSourceText(e.target.value)} placeholder="Include the advisory title, issue time, storm ID, and summary measurements." rows={9}/></>}{error && <div role="alert" className="message error">{error}</div>}<div className="modal-footer"><button type="button" className="button secondary" disabled={!!busy} onClick={() => setImportOpen(false)}>Cancel</button><button className="button primary" type="submit" disabled={!!busy}>{busy ? <LoaderCircle size={16} className="spin"/> : <SquareArrowOutUpRight size={16}/>} {paste ? 'Import advisory' : 'Fetch and verify'}</button></div></form></section></div>}
  </div>;
}
