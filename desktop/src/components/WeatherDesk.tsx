import {useEffect, useState} from 'react';
import {ArrowDown, ArrowRight, ArrowUp, CheckCheck, Clock3, FileText, Globe2, Pause, Play, Plus, RefreshCw, Search, ShieldCheck, Sparkles, ExternalLink} from 'lucide-react';
import type {Advisory, Feed, Intelligence} from '../contracts';
import {api} from '../api';

const date = (stamp: string | null) => stamp ? new Date(stamp).toLocaleString('en-US', {month:'short', day:'2-digit', hour:'2-digit', minute:'2-digit', year:'numeric', hour12:false, timeZone:'UTC'}) + ' UTC' : 'Not collected';
const nice = (value: string) => value.replaceAll('_', ' ');
const preview = (value: unknown) => value === null ? 'Not supplied' : String(value).length > 120 ? String(value).slice(0,120) + '…' : String(value);

interface Props {
  advisories: Advisory[]; intelligence: Intelligence; advisory: Advisory | undefined; busy: boolean;
  onSelect: (id: string) => void; onTraining: () => void; onDraft: (item: Advisory) => void;
  onPolling: (feed: Feed, enabled: boolean, interval: number) => void;
  onRefresh: (feed: Feed) => void;
}

export function SourceControls({feeds, busy, onPolling, onRefresh}: Pick<Props, 'busy' | 'onPolling' | 'onRefresh'> & {feeds: Feed[]}) {
  return <div className="feed-cards">{feeds.map(feed => <section className="panel feed-card" key={feed.id}>
    <div className="feed-title"><Globe2 size={18}/><strong>{feed.id.toUpperCase()} {feed.id === 'nws' ? 'active alerts' : 'Atlantic advisories'}</strong><span className={'pill ' + (feed.status === 'healthy' ? 'green' : 'amber')}>{nice(feed.status)}</span></div>
    <p className="source-url">{feed.url}</p>
    <div className="feed-readings"><span>Last verified collection<strong>{date(feed.last_success_at)}</strong></span><span>Valid records<strong>{feed.collected_count} <small>· {feed.rejected_count} quarantined</small></strong></span></div>
    {feed.last_error && <p className="feed-error">{feed.last_error}</p>}
    <div className="feed-actions"><label>Poll every<select aria-label={`${feed.id.toUpperCase()} polling interval`} disabled={busy} value={feed.interval_seconds} onChange={event => onPolling(feed, feed.enabled, Number(event.target.value))}>{[60,300,900,1800,3600].map(seconds => <option value={seconds} key={seconds}>{seconds / 60} min</option>)}</select></label>
    <button className={'button ' + (feed.enabled ? 'primary' : 'secondary')} disabled={busy} onClick={() => onPolling(feed, !feed.enabled, feed.interval_seconds)}>{feed.enabled ? <Pause size={13}/> : <Play size={13}/>} {feed.enabled ? 'Pause polling' : 'Start polling'}<span className="sr-only"> {feed.id.toUpperCase()}</span></button><button className="icon-button" aria-label={`Refresh ${feed.id.toUpperCase()}`} disabled={busy} onClick={() => onRefresh(feed)}><RefreshCw size={15}/></button></div>
    <small className="feed-next">{feed.enabled ? 'Next scheduled check: ' + date(feed.next_poll_at) : 'Automatic collection paused · manual refresh available'}</small>
  </section>)}</div>;
}

export default function WeatherDesk(props: Props) {
  const {advisories, intelligence, advisory, busy, onSelect, onTraining, onDraft} = props;
  const [search, setSearch] = useState('');
  const [provider, setProvider] = useState('all');
  const [scope, setScope] = useState('latest');
  const [timeline, setTimeline] = useState<Advisory[]>([]);
  const [timelineError, setTimelineError] = useState('');
  const latestIds = new Set(intelligence.events.map(event => event.latest_advisory_id));
  const visible = advisories.filter(item => (scope === 'all' || latestIds.has(item.id)) && (provider === 'all' || item.provider === provider) && [item.title, item.area, item.event_key].join(' ').toLowerCase().includes(search.toLowerCase()));
  useEffect(() => {
    let active = true;
    setTimeline([]); setTimelineError('');
    if (advisory) api<{timeline:Advisory[]}>(`/events/${encodeURIComponent(advisory.event_id)}`).then(result => {if (active) setTimeline(result.timeline);}).catch(error => {if (active) setTimelineError(error.message);});
    return () => {active = false;};
  }, [advisory?.event_id, advisories.length, advisory?.id, advisory?.freshness]);

  return <>
    <SourceControls feeds={intelligence.feeds} busy={busy} onPolling={props.onPolling} onRefresh={props.onRefresh}/>
    <div className="intelligence-grid">
      <section className="panel archive-panel"><div className="panel-header"><h2>News priority & evidence</h2><span className="pill">{intelligence.events.length} events</span></div>
        <div className="archive-controls"><div className="search-field"><Search size={15}/><input aria-label="Search weather evidence" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search event, region, or storm ID"/></div><div className="archive-selects"><select aria-label="Evidence provider" value={provider} onChange={event => setProvider(event.target.value)}><option value="all">All providers</option><option value="NWS">NWS</option><option value="NHC">NHC</option><option value="TRAINING">Training</option></select><select aria-label="Evidence versions" value={scope} onChange={event => setScope(event.target.value)}><option value="latest">Latest per event</option><option value="all">All advisory versions</option></select></div></div>
        <div className="priority-legend">Ranked by official severity, recency, US relevance, and verified changes.</div>
        <div className="event-list">{visible.slice(0,150).map(item => <button className={'event-row ' + (item.id === advisory?.id ? 'selected' : '')} key={item.id} onClick={() => onSelect(item.id)}>
          <span className={'priority-score ' + item.priority.tier} title={item.priority.reasons.join('; ')}>{item.priority.score.toString().padStart(2,'0')}</span><span className="event-copy"><strong>{item.title}</strong><small>{item.provider} · {date(item.issued_at)}{item.area && ' · ' + item.area}</small></span><span className={'pill ' + (item.freshness === 'current' ? 'green' : 'amber')}>{nice(item.freshness)}</span><ArrowRight size={14}/>
        </button>)}</div>
        {!visible.length && <div className="empty"><Globe2 size={30}/><h3>{advisories.length ? 'No matching evidence' : 'Collect your first official source'}</h3><p>Refresh the feeds or import an advisory. A labeled training dataset is also available for the offline workflow.</p></div>}
        {visible.length > 150 && <div className="panel-footer">Showing the first 150 of {visible.length} matching records. Narrow your search to find a specific event.</div>}
        <div className="panel-footer"><span>{advisories.length} immutable records</span><button className="text-button" disabled={busy} onClick={onTraining}>Load training dataset<Plus size={14}/></button></div>
      </section>
      <section className="panel advisory-detail">{advisory ? <>
        <div className="panel-header"><h2>Source package</h2><span className={'pill ' + (advisory.freshness === 'current' ? 'green' : 'amber')}>{nice(advisory.freshness)}</span></div>
        <div className="detail-body"><span className="eyebrow teal">{advisory.provider} / {nice(advisory.provenance)}</span><h2>{advisory.title}</h2><p className="muted">Issued {date(advisory.issued_at)}</p>{advisory.expires_at && <p className="muted">Valid until {date(advisory.expires_at)}</p>}{advisory.area && <p className="affected-area">{advisory.area}</p>}
          {advisory.source_url.startsWith('https://') ? <a href={advisory.source_url} target="_blank" rel="noreferrer">Official source<ExternalLink size={12}/></a> : <p className="muted">Synthetic fixture · no official source</p>}
          <div className="priority-explained"><strong>Editorial priority <span>{advisory.priority.score}/100</span></strong><p>{advisory.priority.reasons.join(' · ')}</p></div>
          <div className="verification-checks"><h3><ShieldCheck size={15}/>Evidence verification</h3>{advisory.verification.checks.map(check => <div key={check.check}>{check.passed ? <CheckCheck size={14} className="teal"/> : <Clock3 size={14} className="amber"/>}<span>{check.check}</span><small>{check.passed ? 'Passed' : 'Restricted'}</small></div>)}<p>{advisory.verification.confidence_note}</p></div>
          {!!Object.keys(advisory.facts).filter(key => ['wind_mph', 'pressure_mb', 'latitude', 'longitude', 'movement_mph', 'movement_degrees'].includes(key)).length && <div className="measurements">{Object.entries(advisory.facts).filter(([key]) => ['wind_mph', 'pressure_mb', 'latitude', 'longitude', 'movement_mph', 'movement_degrees'].includes(key)).map(([key,value]) => <div key={key}><small>{nice(key)}</small><strong>{value}</strong></div>)}</div>}
          <div className="change-header"><span className="eyebrow">SIGNATURE INTELLIGENCE</span><h3>What changed?</h3></div>{advisory.previous_id && <p className="comparison-note">{advisory.comparison.status === "verified_sources" ? "Both versions were fetched from official sources. Original issue times are preserved." : "This comparison includes unverified or synthetic evidence. Confirm both sources before using the changes in reporting."}</p>}{advisory.previous_id ? <div className="changes">{advisory.changes.length ? advisory.changes.map(change => <div className={change.delta === null ? 'text-change' : ''} key={change.field}><span>{nice(change.field)}</span><strong>{preview(change.previous)}<ArrowRight size={14}/>{preview(change.current)}</strong>{change.delta !== null ? <span className="delta">{change.delta >= 0 ? <ArrowUp size={13}/> : <ArrowDown size={13}/>} {Math.abs(change.delta)}</span> : <details><summary>Compare full source wording</summary><pre>PREVIOUS{String('\n')}{change.previous}{String('\n\n')}LATEST{String('\n')}{change.current}</pre></details>}</div>) : <p>No changes in extracted facts.</p>}</div> : <p className="muted">No earlier stored version is available. Future collections preserve revisions for comparison.</p>}
          {!!advisory.warnings.length && <details><summary>Official watches & warnings</summary><ul className="warning-list">{advisory.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></details>}
          {advisory.forecast_excerpt && <details><summary>Official forecast guidance · source wording</summary><pre>{advisory.forecast_excerpt}</pre></details>}
          <details><summary>Complete original advisory text</summary><pre>{advisory.text}</pre></details>
          <button className="button primary full" disabled={busy} onClick={() => onDraft(advisory)}><Sparkles size={16}/>Create source-linked script</button>
          <div className="evidence-timeline"><h3><Clock3 size={15}/>Visual evidence timeline</h3>{timelineError && <p className="feed-error">{timelineError}</p>}{timeline.map(item => <button key={item.id} className={advisory.id === item.id ? 'timeline-active' : ''} onClick={() => onSelect(item.id)}><span className="timeline-dot"/><span><strong>{date(item.issued_at)}</strong><small>{item.title} · {nice(item.freshness)}</small></span><ArrowRight size={13}/></button>)}</div>
        </div>
      </> : <div className="empty"><FileText size={30}/><h3>Select an advisory</h3><p>Source verification, meaningful changes, and the evidence timeline appear here.</p></div>}</section>
    </div>
    {!!intelligence.quarantine.length && <section className="panel quarantine-panel"><div className="panel-header"><h2><ShieldCheck size={15}/>Quarantined source evidence</h2><span className="pill amber">Review required</span></div><p className="priority-legend">These records failed validation. They are excluded from active evidence and editorial approval.</p>{intelligence.quarantine.slice(0,20).map(item => <div className="quarantine-row" key={item.id}><strong>{item.feed_id.toUpperCase()}</strong><span>{item.source_identifier}<small>{item.reason}</small></span><time>{date(item.last_seen_at)}</time></div>)}</section>}
  </>;
}
