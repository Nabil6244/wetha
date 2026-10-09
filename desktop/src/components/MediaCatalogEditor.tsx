import {useState} from 'react';

export interface MediaCatalog {
  tags: string[]; event_id: string; location: string; captured_at: string | null;
  region_codes?: string[]; location_reviewed?: boolean; reference: string; preferred_trim_start: number;
}

export default function MediaCatalogEditor({id, name, kind, catalog, busy, save, regions}: {
  regions: {code:string;name:string}[]; id: string; name: string; kind: string; catalog?: MediaCatalog; busy: boolean;
  save: (id: string, catalog: MediaCatalog) => void;
}) {
  const [tags, setTags] = useState(catalog?.tags.join(', ') ?? '');
  const [event, setEvent] = useState(catalog?.event_id ?? '');
  const [location, setLocation] = useState(catalog?.location ?? '');
  const [date, setDate] = useState(catalog?.captured_at ?? '');
  const [reference, setReference] = useState(catalog?.reference ?? '');
  const [regionCodes,setRegionCodes] = useState(catalog?.region_codes ?? []);
  const [locationReviewed,setLocationReviewed] = useState(catalog?.location_reviewed ?? false);
  const [trim, setTrim] = useState(catalog?.preferred_trim_start ?? 0);
  if (kind === 'audio') return null;
  return <details><summary>Tag footage for automatic suggestions</summary><form className="production-fields" onSubmit={e => {
    e.preventDefault(); save(id, {tags: tags.split(',').map(t => t.trim()).filter(Boolean), event_id: event, location,
      captured_at: date || null, region_codes:regionCodes, location_reviewed:locationReviewed, reference, preferred_trim_start: trim});
  }}>
    <p className="muted span-two">Add only details you know. These catalogue declarations help rank footage; they do not verify that it shows the reported event.</p>
    <label>WEATHER TAGS<input aria-label={`${name} weather tags`} placeholder="rain, wind, flooding, waves" value={tags} onChange={e => setTags(e.target.value)}/></label>
    <label>EVENT ID<input aria-label={`${name} event ID`} maxLength={80} placeholder="Optional, e.g. AL112017" value={event} onChange={e => setEvent(e.target.value)}/></label>
    <label>LOCATION<input aria-label={`${name} location`} maxLength={150} placeholder="Optional capture location" value={location} onChange={e => {setLocation(e.target.value);setLocationReviewed(false);}}/></label>
    <label>CAPTURE DATE<input aria-label={`${name} capture date`} type="date" value={date} onChange={e => setDate(e.target.value)}/></label>
    <label className="span-two">CATALOGUE REFERENCE<input aria-label={`${name} catalogue reference`} maxLength={1000} placeholder="Source documenting event, date or location" value={reference} onChange={e => {setReference(e.target.value);setLocationReviewed(false);}}/></label>
    <label>CAPTURE REGION<select multiple aria-label={`${name} capture region`} value={regionCodes} onChange={e=>{setRegionCodes(Array.from(e.target.selectedOptions,o=>o.value));setLocationReviewed(false);}}>{regions.map(r=><option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
    <label className="production-check"><input type="checkbox" aria-label={`${name} location reviewed`} checked={locationReviewed} onChange={e=>setLocationReviewed(e.target.checked)}/>I reviewed the source reference and it documents this capture region.</label>
    <p className="muted span-two">Named regional scenes exclude unknown or unrelated capture locations. Weather tags and event names alone do not establish where a clip was filmed.</p>
    {kind === 'video'  && <label>PREFERRED CLIP START<input aria-label={`${name} preferred clip start`} type="number" min={0} max={3600} step={0.1} value={trim} onChange={e => setTrim(Number(e.target.value))}/></label>}
    <button className="button secondary" disabled={busy}>Save footage tags</button>
  </form></details>;
}
