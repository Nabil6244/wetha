import {useEffect, useState} from 'react';
import {Clapperboard, Download, FileCheck, FolderOpen, LoaderCircle, Play, Plus, RefreshCw, Save, Upload, X} from 'lucide-react';
import {api} from '../api';
import type {Dashboard} from '../contracts';
import MediaCatalogEditor, {type MediaCatalog} from './MediaCatalogEditor';
import MediaDiscovery from './MediaDiscovery';
import LongformPlanner from './LongformPlanner';
import ManualNarration, {uploadNarration} from './ManualNarration';

interface Media {
  id: string; name: string; kind: 'image' | 'video' | 'audio'; context: 'illustrative' | 'archival' | 'narration';
  license: string; attribution: string; source: string; seconds: number | null; bytes: number;
  source_provider?: 'local' | 'stock' | 'youtube'; reuse_basis?: string; reuse_evidence?: string; preferred_clip_seconds?: number;
  width: number | null; height: number | null; checksum: string; duplicate?: boolean;
  catalog?: MediaCatalog;
}
interface Scene {regional_targets?:string[];source_claim_text?: string; story_beat?: string; story_headline?: string; id: string; script_segment: string; type: string; target_seconds: number; seconds?: number; media_id?: string | null; trim_start?: number; transition: string; observations?: {observed_at: string}[]}
interface Plan {story_version?: number; story_script?: string; story_note?: string; id: string; script_id: string; script_revision: number; scenes: Scene[]; source_label: string; superseded_script_revision: boolean}
type Template = 'short_30' | 'report_60' | 'report_90';
interface FootageCut {media_id: string; seconds: number; trim_start: number}
type MapMode = 'auto' | 'track' | 'warnings' | 'radar' | 'forecast';
type GraphicStyle = 'auto' | 'change_gauge' | 'comparison_split' | 'advisory_timeline' | 'forecast_clock' | 'question_reveal' | 'source_card';
interface SceneEdit {regional_focus?:string;graphic_style?: GraphicStyle; map_mode?: MapMode; id: string; seconds: number; media_id: string | null; trim_start: number; transition: 'cut' | 'fade'; cuts?: FootageCut[]}
interface VisualIssue {scene_id?: string; code: string; message: string}
interface Suggestion {media_id: string; name: string; reasons: string[]; seconds: number; trim_start: number; label: string; attribution: string}
interface EditDraft {plan_id: string; scenes: SceneEdit[]; seconds: number; template: Template; ready?: boolean; target_seconds?: number; note: string; issues: VisualIssue[]; suggestions: {scene_id: string; protected_graphic: boolean; candidates: Suggestion[]}[]}
interface Timeline {
  id: string; plan_id: string; title: string; script_revision: number; scenes: (Scene & SceneEdit)[];
  source_label: string; current_source_label: string; superseded: boolean; seconds: number; audio_mode: string;
  presentation?: 'captioned' | 'cinematic' | 'broadcast'; music?: boolean; narration_id: string | null; narration_verified: boolean; review_valid_now: boolean;
  template?: Template | null;
}
interface Render {
  id: string; timeline_id: string; status: string; stage: string; progress: number; attempts: number; error: string | null;
  snapshot: Timeline; timeline_state: Timeline;
  validation: {seconds: number; width: number; height: number; fps: number; decoded: boolean; audio_mode: string; warnings: string[]} | null;
}
interface State {forecast_news?:{available:boolean;title?:string;seconds?:number;visual_revision?:number;visual_audit?:{shots:number;unique_graphic_treatments:number;repeated_graphic_treatments:number};status?:string;collected_at?:string;refresh_after?:string;note?:string};regional_chapter?:{available:boolean;title?:string;seconds?:number};regions:{code:string;name:string}[]; regional_coverage:{scenes:{plan_id:string;scene_id:string;regions:string[];matching_media_ids:string[];needs_footage:boolean}[];note:string};documentary?:{available:boolean;title?:string}; hour_graphics?:{available:boolean}; complete_episode?: {available: boolean; title?: string}; benchmark?: {available: boolean; event_id?: string; limitations?: string[]}; media: Media[]; timelines: Timeline[]; renders: Render[]; runtime: {ffmpeg: boolean; ffprobe: boolean; output: string; max_upload_bytes: number}}

export default function Production({page, data}: {page: 'Media Library' | 'Video Production'; data: Dashboard}) {
  const [state, setState] = useState<State | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<Media['kind']>('video');
  const [context, setContext] = useState<Media['context']>('illustrative');
  const [license, setLicense] = useState('');
  const [attribution, setAttribution] = useState('');
  const [source, setSource] = useState('');
  const [rights, setRights] = useState(false);
  const [sourceProvider, setSourceProvider] = useState<'local' | 'stock' | 'youtube'>('local');
  const [reuseBasis, setReuseBasis] = useState<'permission' | 'cc_by' | 'creator_owned'>('permission');
  const [reuseEvidence, setReuseEvidence] = useState('');
  const [clipSeconds, setClipSeconds] = useState(3.5);
  const [scriptId, setScriptId] = useState('');
  const [planId, setPlanId] = useState('');
  const [title, setTitle] = useState('Weather news preview');
  const [scenes, setScenes] = useState<SceneEdit[]>([]);
  const [narrationId, setNarrationId] = useState('');
  const [narrationVerified, setNarrationVerified] = useState(false);
  const [presentation, setPresentation] = useState<'captioned' | 'cinematic' | 'broadcast'>('captioned');
  const [music, setMusic] = useState(false);
  const [satelliteContext, setSatelliteContext] = useState(false);
  const [timelineId, setTimelineId] = useState('');
  const [dirty, setDirty] = useState(false);
  const [previewId, setPreviewId] = useState('');
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [template, setTemplate] = useState<Template | null>(null);
  const [requestedTemplate, setRequestedTemplate] = useState<Template>('short_30');
  const targetSeconds = requestedTemplate === 'report_90' ? 90 : requestedTemplate === 'report_60' ? 60 : 30;
  const [check, setCheck] = useState<{key: string; ready: boolean; issues: VisualIssue[]} | null>(null);

  async function load() {
    const [production, visual] = await Promise.all([api<State>('/production'), api<{plans: Plan[]}>('/visuals')]);
    setState(production); setPlans(visual.plans);
  }
  useEffect(() => {void load().catch(e => setError(e.message));}, []);
  const rendering = state?.renders.some(r => ['queued', 'running'].includes(r.status));
  useEffect(() => {
    if (!rendering) return;
    const timer = setInterval(() => {void load().catch(e => setError(e.message));}, 2500);
    return () => clearInterval(timer);
  }, [rendering]);
  async function work(label: string, action: () => Promise<void>) {
    setBusy(label); setError(''); setNotice('');
    try {await action(); await load();} catch (e) {setError(e instanceof Error ? e.message : 'Production operation failed');} finally {setBusy('');}
  }
  function choosePlan(id: string) {
    const plan = plans.find(p => p.id === id);
    setPlanId(id); setTimelineId(''); setDirty(true); setNarrationId(''); setNarrationVerified(false);
    setDraft(null); setTemplate(null); setCheck(null);
    setScenes(plan?.scenes.map(s => ({id: s.id, seconds: Math.max(1, Math.min(120, s.target_seconds)), media_id: null, trim_start: 0, transition: 'cut'})) ?? []);
  }
  function chooseTimeline(id: string) {
    const timeline = state?.timelines.find(t => t.id === id);
    setTimelineId(id);
    if (timeline) {
      setPlanId(timeline.plan_id); setTitle(timeline.title); setSatelliteContext(timeline.scenes.some(s => !!s.observations?.length)); setPresentation(timeline.presentation ?? 'captioned'); setMusic(timeline.music ?? false);
      setScenes(timeline.scenes.map(s => ({id: s.id, seconds: s.seconds, media_id: s.media_id, trim_start: s.trim_start, transition: s.transition, cuts: s.cuts, map_mode: s.map_mode, graphic_style:s.graphic_style,regional_focus:s.regional_focus})));
      setNarrationId(timeline.narration_id ?? ''); setNarrationVerified(timeline.narration_verified); setDirty(false);
      setTemplate(timeline.template ?? null); setDraft(null); setCheck(null);
    }
  }
  function editScene(index: number, changes: Partial<SceneEdit>) {
    setScenes(old => old.map((s, i) => i === index ? {...s, ...changes, ...('media_id' in changes ? {cuts: [], map_mode:'auto' as MapMode, graphic_style:'auto' as GraphicStyle} : {})} : s)); setDirty(true); setTemplate(null);
  }
  const plan = plans.find(p => p.id === planId);
  const total = scenes.reduce((sum, s) => sum + Math.round(s.seconds * 30) / 30, 0);
  const narration = state?.media.find(m => m.id === narrationId);
  const saved = state?.timelines.find(t => t.id === timelineId);
  const selectedPreview = state?.renders.find(r => r.id === previewId);
  const timelineBody = {plan_id: planId, title, scenes, narration_id: narrationId || null, satellite_context: satelliteContext, presentation, music, narration_verified: narrationVerified, template};
  const checkKey = JSON.stringify(timelineBody);
  const visibleCheck = check?.key === checkKey ? check : null;
  const activeDraft = draft?.plan_id === planId ? draft : null;
  const voiceoverText = plan?.scenes.map(s => s.script_segment).join('\n\n') ?? '';

  function fitNarration() {
    if (!narration?.seconds || !scenes.length) return;
    const frames = Math.round(narration.seconds * 30);
    if (frames < scenes.length * 30 || frames > scenes.length * 3600) {
      setError('This audio needs between 1 and 120 seconds per scene. Split a long recording into chapters or adjust the scene plan.'); return;
    }
    if (scenes.some(s => s.cuts?.length)) {
      setError('This edit has timed footage cuts. Adjust the cuts and scene durations to match your recording before saving.'); return;
    }
    // Allocate whole frames with scene limits, retaining original proportions where possible.
    const allocation = scenes.map(() => 0);
    let remaining = frames;
    let pending = scenes.map((_, i) => i);
    while (pending.length) {
      const weight = pending.reduce((sum, i) => sum + scenes[i].seconds, 0);
      const bounded = pending.filter(i => remaining * scenes[i].seconds / weight < 30 || remaining * scenes[i].seconds / weight > 3600);
      if (!bounded.length) {
        for (const i of pending) allocation[i] = Math.floor(remaining * scenes[i].seconds / weight);
        let extra = remaining - pending.reduce((sum, i) => sum + allocation[i], 0);
        for (const i of pending) {if (extra > 0 && allocation[i] < 3600) {allocation[i]++; extra--;}}
        break;
      }
      for (const i of bounded) allocation[i] = remaining * scenes[i].seconds / weight < 30 ? 30 : 3600;
      remaining -= bounded.reduce((sum, i) => sum + allocation[i], 0);
      pending = pending.filter(i => !bounded.includes(i));
    }
    setScenes(old => old.map((s, i) => ({...s, seconds: allocation[i] / 30})));
    setTemplate(null); setDraft(null); setCheck(null); setDirty(true); setError('');
    setNotice('Scene durations fitted to the audio. Review where each scene changes and check footage lengths before rendering.');
  }

  return <div className="production-workspace">
    {error && <div role="alert" className="message error">{error}<button aria-label="Dismiss production error" onClick={() => setError('')}><X size={16}/></button></div>}
    {notice && <div role="status" className="message success"><FileCheck size={16}/>{notice}</div>}
    {busy && <div role="status" className="working"><LoaderCircle size={15} className="spin"/>{busy}…</div>}
    <div className="production-banner"><Clapperboard size={21}/><div><strong>From script to screen</strong><p>Build a story with a hook, source evidence and a clear takeaway, then assemble a 30-, 60- or 90-second edit.</p></div><span className="pill">Local production</span></div>
    {!state ? <section className="panel detail-body">Loading production workspace…</section> : <>
    {page === 'Video Production' && <>
      <section className="panel"><div className="panel-header"><h2><Plus size={17}/>Choose a source-linked scene plan</h2><span className="pill">Revision-bound</span></div><div className="detail-body">
        <div className="production-fields"><label>SCRIPT FOR NEW PLAN<select aria-label="SCRIPT FOR NEW PLAN" disabled={!!busy} value={scriptId} onChange={e => setScriptId(e.target.value)}><option value="">Choose a script</option>{data.scripts.map(s => <option key={s.id} value={s.id}>{s.title} · revision {s.revision} · {s.label}</option>)}</select></label>
        <div className="production-inline-action"><button className="button secondary" disabled={!!busy || !scriptId} onClick={() => {void work('Preparing scenes', async () => {const script = data.scripts.find(s => s.id === scriptId)!; const result = await api<Plan>('/visuals/plans', {script_id: script.id, expected_revision: script.revision}); setPlans(old => [result, ...old]); setPlanId(result.id); setTimelineId(''); setNarrationId(''); setNarrationVerified(false); setTemplate(null); setDraft(null); setCheck(null); setDirty(true); setScenes(result.scenes.map(s => ({id: s.id, seconds: Math.max(1, Math.min(120, s.target_seconds)), media_id: null, trim_start: 0, transition: 'cut'}))); setNotice('Source-linked scenes prepared. Set their timing and choose media below.');});}}><Plus size={15}/>Prepare scene plan</button></div>
        <label>SAVED SCENE PLAN<select aria-label="PRODUCTION SCENE PLAN" disabled={!!busy} value={planId} onChange={e => choosePlan(e.target.value)}><option value="">Choose a visual plan</option>{plans.map(p => <option key={p.id} value={p.id}>{data.scripts.find(s => s.id === p.script_id)?.title ?? p.script_id} · revision {p.script_revision} · {p.source_label}{p.superseded_script_revision ? ' · superseded' : ''} · {p.id.slice(0, 6)}</option>)}</select></label>
        <label>SAVED TIMELINE<select aria-label="SAVED PRODUCTION TIMELINE" disabled={!!busy} value={timelineId} onChange={e => chooseTimeline(e.target.value)}><option value="">New timeline</option>{state.timelines.map(t => <option key={t.id} value={t.id}>{t.title} · {t.seconds.toFixed(1)}s{t.superseded ? ' · superseded' : ''} · {t.id.slice(0, 6)}</option>)}</select></label></div>
      </div></section>
      {plan && <ManualNarration key={plan.id} text={voiceoverText}
        label={`Scene plan · script revision ${plan.script_revision}${plan.story_version ? ' · story draft' : ''}`}
        maxBytes={state.runtime.max_upload_bytes} disabled={!!busy || plan.superseded_script_revision}
        onUpload={async audio => {
          let success = false;
          await work('Uploading narration', async () => {
            const result = await uploadNarration(audio, state.runtime.max_upload_bytes);
            setNarrationId(result.id); setNarrationVerified(false); setMusic(false); setDirty(true);
            setNotice(`Audio uploaded and selected: ${result.name} · ${result.seconds.toFixed(2)} seconds. Fit timing, listen and confirm it matches the script before saving.`);
            success = true;
          });
          return success;
        }}/>}
    {plan && <a className="button secondary" href="#production-timeline">Review timing and render</a>}
    </>}
    {page === 'Video Production' && state.forecast_news?.available && <section className="panel"><div className="panel-header"><h2>{state.forecast_news.title}</h2><span className="pill">{Math.round(state.forecast_news.seconds ?? 0)} seconds · forecast bulletin · 1080p</span></div><div className="detail-body"><p className={state.forecast_news.status==='refresh_needed'?'production-error':'muted'}>{state.forecast_news.status==='refresh_needed'?'Refresh needed — recorded forecast snapshot':'Recent recorded forecast snapshot'} · Collected {state.forecast_news.collected_at ? new Date(state.forecast_news.collected_at).toUTCString() : ''}</p><video controls preload="metadata" aria-label="Florida forecast news bulletin" style={{width:'100%',maxHeight:620}} src={`/api/production/forecast-news/video?v=${state.forecast_news.visual_revision ?? 1}`}/><p className="muted">Official NHC forecast and warnings, NWS city forecasts through 72 hours, dated rain, wind and temperature maps. Forecasts are labeled separately from reported storm values and illustrative Florida footage. Free local narration.</p><p className="muted">{state.forecast_news.note}</p>{state.forecast_news.visual_audit && <p className="muted">Visual revision {state.forecast_news.visual_revision} · {state.forecast_news.visual_audit.shots} scenes · {state.forecast_news.visual_audit.unique_graphic_treatments} distinct graphic treatments. Rain comparisons, forecast-hour heatmap, wind rankings, temperature dials and alert-record statistics.</p>}<a className="button secondary" href="/api/production/forecast-news/video" download="florida-forecast-bulletin.mp4">Download forecast bulletin</a> <a className="text-button" href="/api/production/forecast-news/manifest" target="_blank" rel="noreferrer">Sources and valid times</a> <a className="text-button" href="/api/production/forecast-news/subtitles" download="florida-forecast.srt">Captions</a> <a className="text-button" href="/api/production/forecast-news/narration" download="florida-forecast-narration.wav">Voiceover</a></div></section>}
    {page === 'Video Production' && state.regional_chapter?.available && <section className="panel"><div className="panel-header"><h2>{state.regional_chapter.title}</h2><span className="pill">{Math.round(state.regional_chapter.seconds ?? 0)} seconds · narrated · 1080p</span></div><div className="detail-body"><video controls preload="metadata" aria-label="South Florida narrated chapter" style={{width:'100%',maxHeight:620}} src="/api/production/regional-chapter/video"/><p className="muted">South Florida during Isaias, August 1–2, 2020. Local station readings, archived NHC maps and location-reviewed Florida coast footage. Later footage is illustrative. Free local Samantha narration and instrumental music.</p><a className="button secondary" href="/api/production/regional-chapter/video" download="south-florida-chapter.mp4">Download Florida chapter</a> <a className="text-button" href="/api/production/regional-chapter/manifest" target="_blank" rel="noreferrer">Sources and licenses</a> <a className="text-button" href="/api/production/regional-chapter/subtitles" download="south-florida.srt">Captions</a> <a className="text-button" href="/api/production/regional-chapter/narration" download="south-florida-narration.wav">Voiceover</a></div></section>}
    {page === 'Video Production' && state.documentary?.available && <section className="panel"><div className="panel-header"><h2>{state.documentary.title}</h2><span className="pill">90 seconds · documentary edit · 1080p</span></div><div className="detail-body"><video controls preload="metadata" aria-label="Isaias documentary edit" style={{width:'100%',maxHeight:620}} src="/api/production/documentary/video"/><p className="muted">24 shots: continuous footage, advancing radar and satellite, moving maps and statistics over the action. Historical August 2020 case study. Illustrative footage and the Irma archival comparison are labeled. Local instrumental; no voiceover.</p><a className="button secondary" href="/api/production/documentary/video" download="isaias-documentary-90.mp4">Download documentary</a> <a className="text-button" href="/api/production/documentary/manifest" target="_blank" rel="noreferrer">Sources and licenses</a> <a className="text-button" href="/api/production/documentary/subtitles" download="isaias-documentary.srt">Captions</a></div></section>}
    <section className="panel"><div className="panel-header"><h2>Regional relevance</h2><span className="pill">Script → location → sources</span></div><div className="detail-body"><p>Florida segments use Florida capture locations and Florida map views. Local statistics require local source measurements. Unknown-location clips are excluded from regional suggestions.</p><p className="muted">{state.regional_coverage.note}</p>{state.regional_coverage.scenes.length ? state.regional_coverage.scenes.slice(0,12).map((s,i)=><p key={`${s.plan_id}-${s.scene_id}-${i}`} className={s.needs_footage?'production-error':'muted'}>{s.scene_id} · {s.regions.join(', ')} · {s.matching_media_ids.length} location-reviewed assets{s.needs_footage?' · capture-location evidence needed':''}</p>) : <p className="muted">Choose a regional focus for a scene or prepare a script naming a state to check its asset coverage.</p>}</div></section>
    {page === 'Video Production' && <LongformPlanner timelines={state.timelines}/>}
    {page === 'Video Production' && state.hour_graphics?.available && <section className="panel"><div className="panel-header"><h2>Graphics for the one-hour program</h2><span className="pill">10 treatments · 60-second proof</span></div><div className="detail-body"><video controls preload="none" style={{width:'100%',maxHeight:520}} src="/api/production/hour-graphics/video"/><p className="muted">Six new motion graphics and four source-bound map views. This short reel demonstrates treatments for different chapters; it is not the full-hour export.</p><a className="button secondary" href="/api/production/hour-graphics/video" download="hour-graphics-proof.mp4">Download graphics proof</a> <a className="text-button" href="/api/production/hour-graphics/manifest" target="_blank" rel="noreferrer">Sources</a></div></section>}
    {page === 'Video Production' && state.complete_episode?.available && <section className="panel"><div className="panel-header"><h2>{state.complete_episode.title}</h2><span className="pill">60 seconds · 1080p · historical</span></div><div className="detail-body"><video controls preload="metadata" style={{width: '100%', maxHeight: 520}} src="/api/production/episode/video"/><p className="muted">Official track, coastal warnings, forecast cone, observed radar, satellite and rainfall. Short licensed footage cuts, measured statistics and a complete story. Stock and Irma footage are labeled separately. August 2020 archive; no current warning.</p><a className="button secondary" href="/api/production/episode/video" download="isaias-complete-60s.mp4">Download complete episode</a> <a className="text-button" href="/api/production/episode/manifest" target="_blank" rel="noreferrer">Sources and licenses</a></div></section>}
    {page === 'Video Production' && state.benchmark?.available && <section className="panel"><div className="panel-header"><h2>Historical broadcast benchmark · {state.benchmark.event_id}</h2><span className="pill">30 seconds · 1080p</span></div><div className="detail-body"><video controls preload="metadata" style={{width: '100%', maxHeight: 520}} src="/api/production/benchmark/video"/><p className="muted">Real NWS satellite and radar, NHC positions and measured statistics. Ground footage uses a labeled map fallback. Historical reconstruction; no current warning.</p><a className="button secondary" href="/api/production/benchmark/video" download="phase7-isaias-30s.mp4">Download historical benchmark</a> <a className="text-button" href="/api/production/benchmark/manifest" target="_blank" rel="noreferrer">Sources and limitations</a></div></section>}
    {(!state.runtime.ffmpeg || !state.runtime.ffprobe) && <div role="alert" className="message error">Install FFmpeg and FFprobe to import media and render video.</div>}
    {page === 'Media Library' ? <>
      <MediaDiscovery regions={state.regions} plans={plans} scriptNames={Object.fromEntries(data.scripts.map(s => [s.id, s.title]))} imported={load}/>
      <section className="panel"><div className="panel-header"><h2><Upload size={17}/>Import licensed media</h2><span className="pill">Local files · up to 250 MiB</span></div>
        <form className="detail-body production-import" onSubmit={e => {e.preventDefault(); void work('Importing media', async () => {
          if (!file) throw new Error('Choose a media file.');
          if (file.size > state.runtime.max_upload_bytes) throw new Error('Files are limited to 250 MiB.');
          const metadata = {name: file.name, kind, context, license, attribution, source, rights_confirmed: rights, source_provider: sourceProvider, reuse_basis: sourceProvider === 'youtube' ? reuseBasis : null, reuse_evidence: sourceProvider === 'youtube' ? reuseEvidence : '', preferred_clip_seconds: clipSeconds};
          const response = await fetch('/api/production/media', {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Media-Metadata': encodeURIComponent(JSON.stringify(metadata))}, body: file, signal: AbortSignal.timeout(180000)});
          const result = await response.json();
          if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Media import failed.');
          setNotice(result.duplicate ? 'This file is already in your library. Its license record was preserved.' : 'Media validated and copied into your library.');
        });}}>
          <div className="production-fields">
            <label>MEDIA ORIGIN<select aria-label="MEDIA ORIGIN" value={sourceProvider} onChange={e => {const origin = e.target.value as 'local' | 'stock' | 'youtube'; setSourceProvider(origin); setRights(false); if (origin === 'youtube') {setKind('video'); setContext('illustrative'); setFile(null);}}}><option value="local">Original / local media</option><option value="stock">Stock library</option><option value="youtube">YouTube clip</option></select></label>
            <label>MEDIA TYPE<select aria-label="MEDIA TYPE" disabled={sourceProvider === 'youtube'} value={kind} onChange={e => {const next = e.target.value as Media['kind']; setKind(next); setContext(next === 'audio' ? 'narration' : 'illustrative'); setFile(null);}}><option value="video">Video footage</option><option value="image">Still image</option><option value="audio">Imported narration audio</option></select></label>
            <label>MEDIA CONTEXT<select aria-label="MEDIA CONTEXT" value={context} onChange={e => setContext(e.target.value as Media['context'])}>{kind === 'audio' ? <option value="narration">Narration</option> : <><option value="illustrative">Illustrative footage</option><option value="archival">Archival footage</option></>}</select></label>
            <label className="span-two">CHOOSE FILE<input key={kind} aria-label="CHOOSE MEDIA FILE" type="file" required accept={kind === 'image' ? '.png,.jpg,.jpeg,.webp' : kind === 'audio' ? '.wav,.mp3,.m4a,.flac,.ogg' : '.mp4,.mov,.mkv,.webm'} onChange={e => setFile(e.target.files?.[0] ?? null)}/></label>
            <label>LICENSE / USAGE TERMS<input aria-label="LICENSE / USAGE TERMS" required minLength={3} maxLength={2000} placeholder="e.g. Original footage, owned by me" value={license} onChange={e => setLicense(e.target.value)}/></label>
            <label>ATTRIBUTION<input aria-label="MEDIA ATTRIBUTION" required minLength={2} maxLength={500} placeholder="Creator or rights holder" value={attribution} onChange={e => setAttribution(e.target.value)}/></label>
            <label className="span-two">{sourceProvider === 'youtube' ? 'ORIGINAL YOUTUBE VIDEO URL' : 'SOURCE / PROVENANCE'}<input aria-label="MEDIA SOURCE" required minLength={2} maxLength={1000} placeholder={sourceProvider === 'youtube' ? 'https://www.youtube.com/watch?v=…' : 'Source URL or description of the original recording'} value={source} onChange={e => setSource(e.target.value)}/></label>
            {sourceProvider === 'youtube' && <><label>YOUTUBE REUSE BASIS<select aria-label="YOUTUBE REUSE BASIS" value={reuseBasis} onChange={e => {setReuseBasis(e.target.value as typeof reuseBasis); setRights(false);}}><option value="permission">Creator permission</option><option value="cc_by">Creative Commons Attribution (CC BY)</option><option value="creator_owned">My own YouTube video</option></select></label><label>PREFERRED CUT LENGTH<input aria-label="YOUTUBE CUT SECONDS" type="number" min={3} max={4} step={0.1} value={clipSeconds} onChange={e => setClipSeconds(Number(e.target.value))}/></label><label className="span-two">PERMISSION / LICENSE REFERENCE<input aria-label="YOUTUBE REUSE EVIDENCE" required minLength={10} maxLength={2000} value={reuseEvidence} onChange={e => setReuseEvidence(e.target.value)} placeholder="Permission record, CC BY declaration URL, or ownership explanation"/></label><p className="muted span-two">Import a video file obtained from the creator or another permitted source. Enter its original YouTube URL above. This records your reuse evidence; it does not download or verify YouTube permissions. A short cut alone does not grant reuse rights.</p></>}
          </div>
          <label className="production-check"><input type="checkbox" required checked={rights} onChange={e => setRights(e.target.checked)}/>I have checked that these usage terms allow this media in the production.</label>
          <div className="production-actions"><p className="muted">Footage is visibly labeled illustrative or archival. Importing it does not make it weather evidence.</p><button className="button primary" disabled={!!busy || !file}><Upload size={15}/>Import media</button></div>
        </form>
      </section>
      <section className="panel"><div className="panel-header"><h2><FolderOpen size={17}/>Your media library</h2><span className="pill">{state.media.length} assets</span></div>
        {!state.media.length ? <div className="empty"><FolderOpen size={30}/><h3>Add footage for your first production</h3><p>Import licensed clips and stills, or render source cards without footage.</p></div> : <div className="production-media-grid">{state.media.map(m => <article className="production-media-card" key={m.id}>
          {m.kind === 'image' ? <img src={`/api/production/media/${m.id}/file`} alt={m.name}/> : m.kind === 'video' ? <video controls preload="metadata" src={`/api/production/media/${m.id}/file`}/> : <div className="production-audio"><audio controls preload="metadata" src={`/api/production/media/${m.id}/file`}/></div>}
          <div><span className="pill">{m.context}</span><h3>{m.name}</h3><p>{m.seconds ? `${m.seconds.toFixed(2)} seconds · ` : ''}{m.width ? `${m.width} × ${m.height} · ` : ''}{(m.bytes / 1048576).toFixed(1)} MiB</p><p><strong>License:</strong> {m.license}</p><p><strong>Credit:</strong> {m.attribution}</p><p><strong>Source:</strong> {m.source}</p>{m.source_provider === 'youtube' && <p><strong>YouTube:</strong> {m.reuse_basis?.replaceAll('_', ' ')} · {m.preferred_clip_seconds}s cuts<br/>{m.reuse_evidence}</p>}</div>
          <MediaCatalogEditor regions={state.regions} id={m.id} name={m.name} kind={m.kind} catalog={m.catalog} busy={!!busy} save={(id, catalog) => {void work('Saving footage tags', async () => {
            const response = await fetch(`/api/production/media/${id}/catalog`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(catalog)});
            if (!response.ok) {const result = await response.json(); throw new Error(typeof result.detail === 'string' ? result.detail : 'Unable to save footage tags.');}
            setNotice('Footage tags saved. New suggestions will use these catalogue details.');
          });}}/>
        </article>)}</div>}
      </section>
    </> : <>
      {plan && <section className="panel"><div className="panel-header"><h2>Story-first script &amp; storyboard</h2><span className="pill">Local drafting</span></div><div className="detail-body"><p>Open with a measured change, reveal the evidence, then explain what to watch next. Each beat keeps its source claim for review.</p><button className="button secondary" disabled={!!busy || !!plan.story_version || plan.superseded_script_revision} onClick={() => {void work('Building story draft', async () => {const result = await api<Plan>('/production/story', {plan_id: planId}); setPlans(old => [result,...old]); setPlanId(result.id); setTimelineId(''); setDraft(null); setTemplate(null); setCheck(null); setDirty(true); setPresentation('broadcast'); setMusic(true); setNarrationId(''); setNarrationVerified(false); setScenes(result.scenes.map(s => ({id:s.id,seconds:Math.max(3,Math.min(120,s.target_seconds)),media_id:null,trim_start:0,transition:'cut'}))); setNotice('Story draft prepared. Review the rewritten beats, then suggest a timed edit.');});}}>Build story draft</button>{plan.story_version && <><p className="muted">{plan.story_note}</p>{plan.scenes.map((s,i) => <article key={s.id}><strong>{i+1}. {s.story_beat ?? s.type.replaceAll('_',' ')} · {s.story_headline}</strong><p>{s.script_segment}</p><details><summary>Compare original source claim</summary><p>{s.source_claim_text}</p></details></article>)}</>}</div></section>}
      {scenes.length > 0 && <section id="production-timeline" className="panel production-timeline"><div className="panel-header"><h2><Clapperboard size={17}/>Assemble your timeline</h2><span className="pill">{total.toFixed(2)} seconds · {scenes.length} scenes</span></div><div className="detail-body">
        <label>EDIT TEMPLATE<select aria-label="EDIT TEMPLATE" value={requestedTemplate} disabled={!!busy} onChange={e => {setRequestedTemplate(e.target.value as Template); setDraft(null);}}><option value="short_30">30-second short</option><option value="report_60">60-second report</option><option value="report_90">90-second report</option></select></label><div className="production-actions"><p className="muted">The template preserves every script scene, keeps data graphics, and chooses unused matching clips from your library.</p><button className="button secondary" disabled={!!busy || !planId || !!plan?.superseded_script_revision} onClick={() => {void work('Suggesting short edit', async () => {setDraft(await api<EditDraft>('/production/assist', {plan_id: planId, template: requestedTemplate,regional_focus:Object.fromEntries(scenes.map(s=>[s.id,s.regional_focus??'auto']))})); setNotice('Draft prepared. Review suggestions and missing visuals below.');});}}>Suggest {targetSeconds}-second edit</button></div>
        {activeDraft && <section aria-label="Suggested short edit"><p>{activeDraft.note}</p>{activeDraft.issues.map((issue, i) => <p className="production-error" key={i}>{issue.scene_id ? `${issue.scene_id}: ` : ''}{issue.message}</p>)}<div className="production-actions"><span>{activeDraft.target_seconds ?? activeDraft.seconds}s target · 3–4 second footage cuts · local instrumental</span><button className="button secondary" disabled={!!busy || activeDraft.ready === false} onClick={() => {setScenes(activeDraft.scenes); setPresentation('broadcast'); setSatelliteContext(false); setMusic(true); setNarrationId(''); setNarrationVerified(false); setTemplate(activeDraft.template); setTimelineId(''); setDirty(true); setNotice('Timed edit applied. Check visuals and timing, then save your timeline.');}}>Apply {activeDraft.target_seconds ?? activeDraft.seconds}-second draft</button></div></section>}
        {dirty && saved && <div className="production-actions"><p className="muted">These edits have not been saved. Save a new timeline or reload the saved version before rendering.</p><button className="button secondary" onClick={() => chooseTimeline(saved.id)}>Discard timeline edits</button></div>}
        {(plan?.superseded_script_revision || saved?.superseded) && <div className="message error">This script has a newer revision. Prepare a new scene plan before rendering.</div>}
        <div className="production-fields"><label>PROGRAM TITLE<input aria-label="PROGRAM TITLE" value={title} maxLength={150} onChange={e => {setTitle(e.target.value); setDirty(true);}}/></label>
        <label>VIDEO STYLE<select aria-label="VIDEO STYLE" value={presentation} onChange={e => {const style = e.target.value as 'captioned' | 'cinematic' | 'broadcast'; setPresentation(style); if (style === 'broadcast') {setSatelliteContext(false); setScenes(old => old.map(s => ({...s, transition: 'fade'})));} if (style === 'cinematic') {setSatelliteContext(true); setScenes(old => old.map(s => ({...s, media_id: null, trim_start: 0})));} setDirty(true);}}><option value="broadcast">Broadcast · geographic scenes &amp; measured statistics</option><option value="captioned">Captioned report</option><option value="cinematic">Weather brief · full-screen imagery, stats &amp; headlines</option></select></label>
        <label>NARRATION AUDIO<select aria-label="NARRATION AUDIO" value={narrationId} onChange={e => {setNarrationId(e.target.value); if (e.target.value) setMusic(false); setNarrationVerified(false); setDirty(true);}}><option value="">Silent video with captions</option>{state.media.filter(m => m.kind === 'audio').map(m => <option key={m.id} value={m.id}>{m.name} · {m.seconds?.toFixed(2)} seconds</option>)}</select></label></div>
        {narration && <div className="production-narration"><audio controls src={`/api/production/media/${narration.id}/file`}/><span>Measured audio: {narration.seconds?.toFixed(2)}s · timeline: {total.toFixed(2)}s</span><button className="button secondary" disabled={!!busy} onClick={fitNarration}>Fit timing to audio</button><label className="production-check"><input type="checkbox" checked={narrationVerified} onChange={e => {setNarrationVerified(e.target.checked); setDirty(true);}}/>I checked that this audio matches the script revision.</label></div>}
        <div className="production-actions"><label className="production-check"><input type="checkbox" checked={satelliteContext} onChange={e => {setSatelliteContext(e.target.checked); setDirty(true);}}/>Use real NOAA Gulf/Atlantic satellite context for scenes without imported media</label><button className="button secondary" disabled={!!busy} onClick={() => {void work('Collecting NOAA satellite observations', async () => {const result = await api<{error?: string}>('/visuals/sources/goes/refresh', {}); if (result.error) throw new Error(result.error); setNotice('NOAA observations collected. Saving a timeline preserves the latest 12 frames and their timestamps.');});}}><RefreshCw size={14}/>Collect satellite observations</button></div>
        {satelliteContext && <p className="muted">Real GeoColor observations retain the entire NOAA image and timestamps. Regional context requires a reported storm center in the Gulf/Atlantic region. Imagery has its own observation time; it does not identify the reported storm. The chronological sequence plays once per scene.</p>}
        <label className="production-check"><input type="checkbox" checked={music} disabled={!!narrationId} onChange={e => {setMusic(e.target.checked); setDirty(true);}}/>Add an original instrumental pulse, generated locally without voice or paid services</label>
        <p className="muted">{template === 'short_30' ? '30-second short template' : template === 'report_60' ? '60-second report template' : template === 'report_90' ? '90-second report template' : 'Manual edit'} · {total.toFixed(2)} seconds</p>
        <div className="production-timebar" aria-label="Scene duration overview">{scenes.map((s, i) => <span key={s.id} style={{flex: s.seconds}} title={`Scene ${i+1}: ${s.seconds}s`}>{i+1}</span>)}</div>
        <div className="production-scene-list">{scenes.map((scene, index) => {
          const original = plan?.scenes.find(s => s.id === scene.id) ?? saved?.scenes.find(s => s.id === scene.id);
          return <article className="production-scene" key={scene.id}><div className="production-scene-heading"><span>{String(index+1).padStart(2, '0')}</span><strong>{original?.type.replaceAll('_', ' ') ?? 'Source-linked scene'}</strong><small>{scene.seconds.toFixed(2)}s</small></div><p>{original?.script_segment}</p><div className="production-scene-fields">
            <label>REGIONAL FOCUS<select aria-label={`Scene ${index+1} regional focus`} value={scene.regional_focus??'auto'} onChange={e=>{editScene(index,{regional_focus:e.target.value,media_id:null,trim_start:0});setDraft(null);}}><option value="auto">Automatic from script{original?.regional_targets?.length ? ' · '+original.regional_targets.join(', ') : ''}</option>{state.regions.map(r=><option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
            <label>SECONDS<input aria-label={`Scene ${index+1} seconds`} type="number" min={1} max={120} step={0.1} disabled={!!scene.cuts?.length} value={scene.seconds} onChange={e => editScene(index, {seconds: Number(e.target.value)})}/></label>
            <label>VISUAL<select aria-label={`Scene ${index+1} media`} value={scene.media_id ?? ''} disabled={!!scene.cuts?.length} onChange={e => {const selected = state.media.find(m => m.id === e.target.value); editScene(index, {media_id: e.target.value || null, trim_start: 0, ...(selected?.source_provider === 'youtube' ? {seconds: selected.preferred_clip_seconds ?? 3.5, transition: 'cut'} : {})});}}><option value="">{satelliteContext ? 'Real NOAA satellite context' : 'Planned graphic / source card'}</option>{state.media.filter(m => m.kind !== 'audio').map(m => <option key={m.id} value={m.id}>{m.name} · {m.context}</option>)}</select></label>
            <label>MAP TYPE<select aria-label={`Scene ${index+1} map type`} value={scene.map_mode ?? 'auto'} disabled={presentation !== 'broadcast' || !!scene.media_id || !!scene.cuts?.length} onChange={e => editScene(index,{map_mode:e.target.value as MapMode,graphic_style:'auto'})}><option value="auto">Automatic graphic</option><option value="track">Reported track &amp; motion compass</option><option value="warnings">Warning areas &amp; coverage</option><option value="radar">Radar observations · precipitation context</option><option value="forecast">Forecast outlook &amp; uncertainty</option></select></label>
            <label>MOTION GRAPHIC<select aria-label={`Scene ${index+1} motion graphic`} value={scene.graphic_style??'auto'} disabled={presentation !== 'broadcast'||!!scene.media_id||!!scene.cuts?.length} onChange={e=>editScene(index,{graphic_style:e.target.value as GraphicStyle,map_mode:e.target.value==='forecast_clock'?'forecast':'auto'})}><option value="auto">Use planned map / graphic</option><option value="change_gauge">Change dial</option><option value="comparison_split">Before / after split</option><option value="advisory_timeline">Advisory timeline</option><option value="forecast_clock">Forecast time ladder</option><option value="question_reveal">Question / answer reveal</option><option value="source_card">Source spotlight</option></select></label>
            <label>CLIP START<input aria-label={`Scene ${index+1} clip start`} type="number" min={0} step={0.1} value={scene.trim_start} disabled={!scene.media_id || state.media.find(m => m.id === scene.media_id)?.kind !== 'video'} onChange={e => editScene(index, {trim_start: Number(e.target.value)})}/></label>
            <label>TRANSITION<select aria-label={`Scene ${index+1} transition`} value={scene.transition} onChange={e => editScene(index, {transition: e.target.value as 'cut' | 'fade'})}><option value="cut">Cut</option><option value="fade">{presentation === 'broadcast' ? 'Dissolve' : 'Fade through black'}</option></select></label>
          </div>{!!scene.cuts?.length && <div><p className="muted">Footage sequence · {scene.cuts.length} cuts</p>{scene.cuts.map((cut, i) => <p className="muted" key={i}>{state.media.find(m => m.id === cut.media_id)?.name ?? cut.media_id} · {cut.trim_start.toFixed(2)}s start · {cut.seconds.toFixed(2)}s duration</p>)}<button className="button secondary" disabled={!!busy} onClick={() => editScene(index, {cuts: [], media_id: null, trim_start: 0})}>Clear footage sequence for scene {index+1}</button></div>}{activeDraft?.suggestions.find(s => s.scene_id === scene.id)?.candidates.map(candidate => <div className="production-actions" key={candidate.media_id}><p><strong>{candidate.name}</strong> · {candidate.label}<br/><span className="muted">{candidate.reasons.join(' · ')} · Credit: {candidate.attribution}</span></p><button className="button secondary" disabled={!!busy} onClick={() => {setPresentation('broadcast'); setSatelliteContext(false); editScene(index, {media_id: candidate.media_id, seconds: candidate.seconds, trim_start: candidate.trim_start, transition: 'cut'});}}>Use suggestion for scene {index+1}</button></div>)}</article>;
        })}</div>
        <button className="button secondary" disabled={!!busy || !planId} onClick={() => {void work('Checking visuals and timing', async () => {const result = await api<{ready: boolean; issues: VisualIssue[]}>('/production/check', timelineBody); setCheck({...result, key: checkKey}); setNotice(result.ready ? 'Timeline checks passed. Review any graphic fallbacks below.' : 'Timeline needs fixes before it can be saved.');});}}>Check visuals &amp; timing</button>
        {visibleCheck && <div role="region" aria-label="Timeline checks"><p>{visibleCheck.ready ? 'Ready to render after saving' : 'Fix these issues before rendering'}</p>{visibleCheck.issues.map((issue, i) => <p className="production-error" key={i}>{issue.scene_id ? `${issue.scene_id}: ` : ''}{issue.message}</p>)}</div>}
        <div className="production-actions"><p className="muted">Saving creates an immutable timeline. {narrationId ? 'Audio and scene duration must agree within 0.2 seconds.' : music ? 'Original instrumental soundtrack with captions. No voiceover will be generated.' : 'No narration will be generated. The output includes captions and a silent audio track.'}</p><div><button className="button secondary" disabled={!!busy || !planId} onClick={() => {void work('Saving timeline', async () => {const checked = await api<{ready: boolean; issues: VisualIssue[]}>('/production/check', timelineBody); setCheck({...checked, key: checkKey}); if (!checked.ready) throw new Error(checked.issues.map(i => i.message).join(' ')); const result = await api<Timeline>('/production/timelines', timelineBody); setState(old => old ? {...old, timelines: [result, ...old.timelines]} : old); setTimelineId(result.id); setDirty(false); setNotice('Timeline saved. You can now render this exact scene assembly.');});}}><Save size={15}/>Save timeline</button><button className="button primary" disabled={!!busy || !timelineId || dirty || saved?.superseded || !state.runtime.ffmpeg || !state.runtime.ffprobe} onClick={() => {void work('Starting render', async () => {await api('/production/renders', {timeline_id: timelineId}); setNotice('Render queued. You can keep working while FFmpeg prepares the video.');});}}><Play size={15}/>Render 1080p preview</button></div></div>
      </div></section>}
      <section className="panel"><div className="panel-header"><h2><Clapperboard size={17}/>Render jobs</h2><button className="text-button" disabled={!!busy} onClick={() => {void work('Refreshing renders', load);}}><RefreshCw size={14}/>Refresh</button></div>
        {!state.renders.length ? <div className="empty"><Clapperboard size={30}/><h3>Your first video starts here</h3><p>Prepare a scene plan, save a timeline, and render a preview.</p></div> : <div className="production-jobs">{state.renders.map(r => <article className="production-job" key={r.id}><div><h3>{r.snapshot.title}</h3><span className={'pill ' + (r.status === 'succeeded' ? 'green' : 'amber')}>{r.status}</span></div><p>{r.stage} · attempt {r.attempts} · {r.snapshot.seconds.toFixed(1)}s · {r.snapshot.source_label} · {r.snapshot.audio_mode.replaceAll('_', ' ')}</p><progress max={100} value={r.progress}/>{r.error && <p className="production-error">{r.error}</p>}{r.timeline_state.superseded && <p className="production-error">A newer script revision exists. This output retains the older revision.</p>}
          <div className="production-job-actions">{['queued', 'running'].includes(r.status) && <button className="button secondary" disabled={!!busy} onClick={() => {void work('Cancelling render', async () => {await api(`/production/renders/${r.id}/cancel`, {});});}}><X size={14}/>Cancel render</button>}{['failed', 'cancelled'].includes(r.status) && <button className="button secondary" disabled={!!busy || r.timeline_state.superseded} onClick={() => {void work('Retrying render', async () => {await api(`/production/renders/${r.id}/retry`, {});});}}><RefreshCw size={14}/>Retry render</button>}{r.status === 'succeeded' && <><button className="button primary" onClick={() => setPreviewId(r.id)}><Play size={14}/>Preview video</button><a className="button secondary" href={`/api/production/renders/${r.id}/video?download=true`} download><Download size={14}/>Download MP4</a><a className="button secondary" href={`/api/production/renders/${r.id}/subtitles?download=true`} download>Subtitles</a><a className="button secondary" href={`/api/production/renders/${r.id}/manifest?download=true`} download>Source &amp; license manifest</a></>}</div>
          {r.validation && <p className="muted">Validated {r.validation.width} × {r.validation.height}, {r.validation.fps} fps, H.264 / AAC · full output decoded · production preview only</p>}
          {r.validation?.warnings?.map(warning => <p key={warning} className="production-error">{warning}</p>)}
        </article>)}</div>}
      </section>
      {selectedPreview?.status === 'succeeded' && <section className="panel production-preview"><div className="panel-header"><h2>Production preview</h2><button aria-label="Close video preview" onClick={() => setPreviewId('')}><X size={18}/></button></div><video key={previewId} controls autoPlay src={`/api/production/renders/${previewId}/video`}/></section>}
    </>}
    </>}
  </div>;
}
