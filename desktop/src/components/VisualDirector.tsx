import {useEffect,useRef,useState} from 'react';
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type {GeoJSONSource,StyleSpecification} from 'maplibre-gl';
import type {FeatureCollection} from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import {ArrowRight,Camera,Download,Globe2,Layers,Pause,Play,RefreshCw,Satellite,ShieldCheck} from 'lucide-react';
import {api} from '../api';
import type {Advisory,Dashboard,Script} from '../contracts';
maplibregl.setWorkerUrl(workerUrl);

interface Asset {id:string;kind:string;source_url:string;observed_at:string;checksum:string;temporal_label:string;metadata:{product?:string;extent?:number[];legend_asset_id?:string;note?:string;projection?:string;attribution?:string}}
interface Scene {id:string;type:string;script_segment:string;target_seconds:number;camera_movement:string;transition:string;parameters:Record<string,unknown>;fallback_asset:string}
interface Plan {id:string;script_id:string;script_revision:number;current_source_label:string;superseded_script_revision:boolean;scenes:Scene[];estimated_seconds:number;rendered:boolean;broadcast_eligible:boolean}
interface VisualState {assets:Asset[];sources:{id:string;status:string;last_error:string|null;checked_at:string|null}[];plans:Plan[];basemap:{name:string;license:string;source_url:string}}
interface Geography {advisory:Advisory;geojson:FeatureCollection;timeline:{advisory_id:string;issued_at:string;coordinates:[number,number];wind_mph?:number;pressure_mb?:number}[];omitted:{id:string;reason:string}[];note:string}
const date=(value:string)=>new Date(value).toISOString().slice(0,19).replace('T',' ')+' UTC';
const empty:FeatureCollection={type:'FeatureCollection',features:[]};

function EvidenceMap({geography,radar,journey}: {geography:Geography|null;radar:Asset|null;journey:number|null}) {
  const container=useRef<HTMLDivElement>(null);const mapRef=useRef<maplibregl.Map|null>(null);
  const [ready,setReady]=useState(false);const [error,setError]=useState('');
  const geoRef=useRef(geography);geoRef.current=geography;
  useEffect(()=>{
    if(!container.current)return;
    const style:StyleSpecification={version:8,sources:{countries:{type:'geojson',data:'/api/visuals/basemap'},evidence:{type:'geojson',data:empty}},layers:[
      {id:'ocean',type:'background',paint:{'background-color':'#0a1b29'}},
      {id:'countries',type:'fill',source:'countries',paint:{'fill-color':'#263d43','fill-opacity':.9}},
      {id:'coastline',type:'line',source:'countries',paint:{'line-color':'#657d80','line-width':.7}},
      {id:'alert-fill',type:'fill',source:'evidence',filter:['==',['get','kind'],'alert_area'],paint:{'fill-color':'#e2ad68','fill-opacity':.18}},
      {id:'alert-line',type:'line',source:'evidence',filter:['==',['get','kind'],'alert_area'],paint:{'line-color':'#e2ad68','line-width':2}},
      {id:'cone-fill',type:'fill',source:'evidence',filter:['==',['get','kind'],'forecast_cone'],paint:{'fill-color':'#cbbddd','fill-opacity':.2}},
      {id:'cone-line',type:'line',source:'evidence',filter:['==',['get','kind'],'forecast_cone'],paint:{'line-color':'#cbbddd','line-width':2,'line-dasharray':[3,2]}},
      {id:'reported-track',type:'line',source:'evidence',filter:['==',['get','kind'],'reported_track'],paint:{'line-color':'#85ddc4','line-width':2,'line-dasharray':[2,2]}},
      {id:'reported-center',type:'circle',source:'evidence',filter:['==',['get','kind'],'reported_center'],paint:{'circle-color':'#a4ebd5','circle-radius':5,'circle-stroke-color':'#0f262d','circle-stroke-width':2}},
    ]};
    let map:maplibregl.Map;
    try {map=new maplibregl.Map({container:container.current,style,center:[-92,29],zoom:3.4,attributionControl:false,maxZoom:10,minZoom:1,renderWorldCopies:false});}
    catch {setError('Geographic preview requires WebGL. Evidence and scene plans remain available.');return;}
    mapRef.current=map;
    map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'top-right');
    map.on('load',()=>{setReady(true);});
    map.on('idle',()=>{if(container.current&&map.getLayer('countries'))container.current.dataset.countryFeatures=String(map.queryRenderedFeatures({layers:['countries']}).length);});
    map.on('error',event=>setError('Map layer could not load: '+event.error.message));
    map.on('click','countries',event=>{const name=event.features?.[0]?.properties?.name;if(name)new maplibregl.Popup().setLngLat(event.lngLat).setText(String(name)+' · Natural Earth geography').addTo(map);});
    return()=>{setReady(false);map.remove();mapRef.current=null;};
  },[]);
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    const source=map.getSource('evidence') as GeoJSONSource;
    source.setData(geography?.geojson??empty);
    if(geography?.timeline.length){const latest=geography.timeline.at(-1)!;map.easeTo({center:latest.coordinates,zoom:4.3,bearing:0,pitch:25,duration:1300});}
    else if(geography?.geojson.features.length){
      const points:number[][]=[];
      const collect=(value:unknown):void=>{if(!Array.isArray(value))return;if(typeof value[0]==='number'){points.push(value as number[]);return;}value.forEach(collect);};
      geography.geojson.features.forEach(feature=>{if(feature.geometry&&'coordinates' in feature.geometry)collect(feature.geometry.coordinates);});
      if(points.length){const bounds=new maplibregl.LngLatBounds();points.forEach(point=>bounds.extend([point[0],point[1]]));map.fitBounds(bounds,{padding:75,maxZoom:7,duration:1200});}
    }
  },[geography,ready]);
  useEffect(()=>{const map=mapRef.current;if(!ready||!map||journey===null||!geography?.timeline[journey])return;map.easeTo({center:geography.timeline[journey].coordinates,zoom:5,bearing:0,pitch:30,duration:1500});},[journey,geography,ready]);
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    if(map.getLayer('radar-overlay'))map.removeLayer('radar-overlay');
    if(map.getSource('radar-image'))map.removeSource('radar-image');
    if(radar?.metadata.extent){const [w,s,e,n]=radar.metadata.extent;map.addSource('radar-image',{type:'image',url:'/api/visuals/assets/'+radar.id,coordinates:[[w,n],[e,n],[e,s],[w,s]]});map.addLayer({id:'radar-overlay',type:'raster',source:'radar-image',paint:{'raster-opacity':.75,'raster-fade-duration':0}},'alert-fill');map.fitBounds([[w,s],[e,n]],{padding:25,duration:1500});}
  },[radar,ready]);
  return <div className="geographic-preview"><div ref={container} className="map-canvas" data-testid="geographic-map"/>{error&&<div role="alert" className="map-error">{error}</div>}<div className="map-caption"><span>GEOGRAPHIC EVIDENCE</span><strong>{geography?.advisory.title??'Official weather workspace'}</strong><small>{geography?date(geography.advisory.issued_at):'Select source evidence'} · {geography?.advisory.freshness??'No evidence'}</small></div><div className="map-attribution">Natural Earth · public domain / NOAA evidence</div><div className="camera-controls"><button aria-label="Reset regional camera" onClick={()=>mapRef.current?.easeTo({center:geoRef.current?.timeline.at(-1)?.coordinates??[-92,29],zoom:4,bearing:0,pitch:0,duration:1400})}><Globe2 size={15}/>Region</button><button aria-label="Rotate map camera" onClick={()=>{const map=mapRef.current;map?.easeTo({bearing:map.getBearing()+20,duration:1200});}}><Camera size={15}/>Rotate</button><button aria-label="Tilt map camera" onClick={()=>{const map=mapRef.current;map?.easeTo({pitch:map.getPitch()>10?0:35,duration:1200});}}><Layers size={15}/>Tilt</button></div></div>;
}

function ChangeGraphics({advisory}: {advisory:Advisory}) {
  const measurements=advisory.changes.filter(change=>typeof change.previous==='number'&&typeof change.current==='number'&&['wind_mph','pressure_mb','latitude','longitude'].includes(change.field));
  const [animate,setAnimate]=useState(false);
  useEffect(()=>{setAnimate(false);const timer=setTimeout(()=>setAnimate(true),60);return()=>clearTimeout(timer);},[advisory.id]);
  return <section className="panel change-graphics"><div className="panel-header"><h2>WHAT CHANGED?</h2><span className="pill">{advisory.comparison.status.replaceAll('_',' ')}</span></div><div className="comparison-visuals">{measurements.length?measurements.map(change=>{const previous=Number(change.previous),current=Number(change.current);const scale=Math.max(Math.abs(previous),Math.abs(current),1);const label=change.field==='wind_mph'?'Maximum sustained wind · mph':change.field==='pressure_mb'?'Central pressure · mb':change.field.replaceAll('_',' ')+' · degrees';return <div className="comparison-card" key={change.field}><label>{label}</label><div className="comparison-values"><strong>{previous}</strong><ArrowRight size={17}/><strong>{current}</strong><span>{change.delta!==null&&change.delta>0?'+':''}{change.delta}</span></div><div className="measurement-bar"><i style={{width:animate?`${Math.abs(previous)/scale*100}%`:'0%'}}/></div><div className="measurement-bar current"><i style={{width:animate?`${Math.abs(current)/scale*100}%`:'0%'}}/></div><small>Previous / selected advisory · bars use magnitude, not a zero-based impact scale</small></div>;}):<p className="muted">No supported numeric comparison is available for this source.</p>}</div><div className="panel-footer">Position, wind and pressure are source measurements. Changes do not establish a future track or cause.</div></section>;
}

export default function VisualDirector({data}: {data:Dashboard}) {
  const [state,setState]=useState<VisualState|null>(null);const [selected,setSelected]=useState('');const [geo,setGeo]=useState<Geography|null>(null);
  const [mode,setMode]=useState<'map'|'satellite'|'radar'>('map');const [frame,setFrame]=useState(0);const [playing,setPlaying]=useState(false);const [journey,setJourney]=useState<number|null>(null);
  const [scriptId,setScriptId]=useState('');const [plan,setPlan]=useState<Plan|null>(null);const [busy,setBusy]=useState('');const [error,setError]=useState('');const [notice,setNotice]=useState('');const [imageReady,setImageReady]=useState(false);
  const initial=data.advisories.find(item=>item.provider==='NHC'&&item.provenance==='official_fetch')??data.advisories[0];
  const advisory=data.advisories.find(item=>item.id===selected)??initial;
  const script:Script|undefined=data.scripts.find(item=>item.id===scriptId)??data.scripts[0];
  const frames=(state?.assets??[]).filter(asset=>asset.kind===(mode==='satellite'?'goes':'radar')).sort((a,b)=>a.observed_at.localeCompare(b.observed_at));
  const activeFrame=frames[Math.min(frame,Math.max(0,frames.length-1))];
  const radar=mode==='radar'&&activeFrame?.metadata.legend_asset_id&&state?.assets.some(asset=>asset.id===activeFrame.metadata.legend_asset_id)?activeFrame:null;
  async function load(){const result=await api<VisualState>('/visuals');setState(result);return result;}
  useEffect(()=>{void load().catch(e=>setError(e.message));},[]);
  useEffect(()=>{if(!advisory)return;let stopped=false;setJourney(null);void api<Geography>('/visuals/geography/'+encodeURIComponent(advisory.id)).then(result=>{if(!stopped)setGeo(result);}).catch(e=>{if(!stopped)setError(e.message);});return()=>{stopped=true;};},[advisory?.id,advisory?.freshness]);
  useEffect(()=>{setFrame(0);setPlaying(false);},[mode]);
  useEffect(()=>{setImageReady(false);},[activeFrame?.id]);
  useEffect(()=>{if(!playing||frames.length<2)return;const timer=setInterval(()=>setFrame(value=>(value+1)%frames.length),900);return()=>clearInterval(timer);},[playing,frames.length]);
  useEffect(()=>{if(journey===null||!geo||journey>=geo.timeline.length-1)return;const timer=setTimeout(()=>setJourney(journey+1),1800);return()=>clearTimeout(timer);},[journey,geo]);
  async function action(label:string,work:()=>Promise<void>){setBusy(label);setError('');setNotice('');try{await work();await load();}catch(e){setError(e instanceof Error?e.message:'Visual operation failed');}finally{setBusy('');}}
  return <>
    {error&&<div role="alert" className="message error">{error}</div>}{notice&&<div role="status" className="message success">{notice}</div>}{busy&&<div role="status" className="working">{busy}…</div>}
    <section className="panel visual-workspace"><div className="visual-toolbar"><div><label className="field-label" htmlFor="visual-evidence">VISUAL SOURCE EVIDENCE</label><select id="visual-evidence" value={advisory?.id??''} onChange={e=>setSelected(e.target.value)}>{data.advisories.map(item=><option key={item.id} value={item.id}>{item.title} · {item.provider} · {item.issued_at}</option>)}{!advisory&&<option>No stored weather evidence</option>}</select></div><div className="visual-mode" role="group" aria-label="Visual layer"><button className={mode==='map'?'active':''} onClick={()=>setMode('map')}><Globe2 size={14}/>Map</button><button className={mode==='satellite'?'active':''} onClick={()=>setMode('satellite')}><Satellite size={14}/>Satellite</button><button className={mode==='radar'?'active':''} onClick={()=>setMode('radar')}><Layers size={14}/>Radar</button></div></div>
      {mode==='satellite'?<div className="satellite-preview"><div className="satellite-image-window">{activeFrame?<img style={{visibility:imageReady?'visible':'hidden'}} className={imageReady&&playing?'observational-pan':''} src={'/api/visuals/assets/'+activeFrame.id} alt={'NOAA GeoColor observation '+date(activeFrame.observed_at)} onLoad={()=>setImageReady(true)} onError={()=>{setImageReady(false);setError('Cached imagery could not be decoded. This frame is unavailable.');}}/>:<div className="visual-empty"><Satellite size={38}/><h3>No satellite observations cached</h3><p>Collect dated NOAA imagery. Source failures never create substitute weather frames.</p></div>}</div><div className="observation-caption"><strong>WEATHER TIME MACHINE</strong><span>{activeFrame?date(activeFrame.observed_at):'Observation time unavailable'}</span><span>{activeFrame?.temporal_label??'No observations'}</span></div></div>:<EvidenceMap geography={geo} radar={radar} journey={journey}/>}
      <div className="visual-legend"><span><i className="legend-center"/>Reported storm center</span><span><i className="legend-alert"/>Official alert polygon</span><span><i className="legend-cone"/>Official forecast cone · forecast</span></div>
      {mode!=='map'&&<div className="observation-controls"><button className="button secondary" disabled={frames.length<2} onClick={()=>setPlaying(!playing)}>{playing?<Pause size={14}/>:<Play size={14}/>} {playing?'Pause observations':'Play observations'}</button><input type="range" aria-label="Observation timeline" min={0} max={Math.max(0,frames.length-1)} value={Math.min(frame,Math.max(0,frames.length-1))} disabled={!frames.length} onChange={e=>{setPlaying(false);setFrame(Number(e.target.value));}}/><span>{frames.length?`${Math.min(frame,frames.length-1)+1} / ${frames.length}`:'0 frames'}</span></div>}
      {mode==='radar'&&<div className="radar-legend">{radar?<><span>{date(radar.observed_at)} · {radar.temporal_label}</span><img src={'/api/visuals/assets/'+radar.metadata.legend_asset_id} alt="NOAA radar reflectivity color legend in dBZ"/><small>Reflectivity (dBZ), not rainfall accumulation</small></>:<p>No timestamped radar frames with a source-provided legend are cached.</p>}</div>}
      {mode==='satellite'&&<p className="visual-note">NOAA/NESDIS/STAR GeoColor · Gulf/Atlantic. Native NOAA image projection shown separately from the geographic map. Composite enhancement is not rainfall intensity. Playback advances real observation times.</p>}
      {geo&&<div className="geographic-note"><ShieldCheck size={15}/><p>{geo.note}{geo.omitted.length>0&&' '+geo.omitted.map(item=>item.reason).join(' ')}</p></div>}
    </section>
    <div className="visual-source-cards">{['goes','radar','forecast_cone'].map(id=>{const source=state?.sources.find(value=>value.id===id);return <section className="panel" key={id}><h3>{id==='goes'?'GOES satellite':id==='radar'?'NOAA radar':'NHC forecast cone'}</h3><span className={'pill '+(source?.status==='healthy'?'green':'amber')}>{source?.status.replaceAll('_',' ')??'not collected'}</span><p>{id==='goes'?'Twelve dated GeoColor frames from the official product catalogue.':id==='radar'?'Time-enabled reflectivity in EPSG:3857, with the official color legend.':'Inline official KMZ geometry must match the selected regular advisory issue time.'}</p>{source?.last_error&&<small className="feed-error">{source.last_error}</small>}<button className="button secondary" disabled={!!busy||(id==='forecast_cone'&&(!advisory||advisory.provider!=='NHC'))} onClick={()=>{void action('Collecting '+id,async()=>{const result=await api<{collected:number}>(id==='forecast_cone'?'/visuals/forecast-cone':'/visuals/sources/'+id+'/refresh',id==='forecast_cone'?{advisory_id:advisory!.id}:{});setNotice(`${result.collected} official visual records cached with timestamps and checksums.`);});}}><RefreshCw size={14}/>Collect {id==='goes'?'satellite':id==='radar'?'radar':'official cone'}</button></section>;})}</div>
    {geo?.timeline.length? <section className="panel storm-journey"><div className="panel-header"><h2>Storm journey</h2><button className="text-button" disabled={geo.timeline.length<2} onClick={()=>{setMode('map');setJourney(0);}}><Play size={14}/>Follow reported centers</button></div><div className="reported-timeline">{geo.timeline.map((point,index)=><button className={index===journey?'selected':''} key={point.advisory_id} onClick={()=>{setMode('map');setJourney(index);}}><strong>{point.wind_mph} mph / {point.pressure_mb} mb</strong><span>{date(point.issued_at)}</span><small>{point.coordinates[1]}°, {point.coordinates[0]}°</small></button>)}</div><div className="panel-footer">Camera interpolation is a viewing motion. It is not an inferred continuous storm track.</div></section>:null}
    {advisory&&<ChangeGraphics advisory={advisory}/>}
    <section className="panel visual-planning"><div className="panel-header"><h2><Camera size={17}/>Scene direction</h2><span className="pill amber">Preview · no audio or video output</span></div><div className="detail-body"><label className="field-label" htmlFor="visual-script">SCRIPT REVISION</label><select id="visual-script" value={script?.id??''} onChange={e=>setScriptId(e.target.value)}>{data.scripts.map(s=><option key={s.id} value={s.id}>{s.title} · revision {s.revision} · {s.label}</option>)}{!script&&<option>Create a newsroom draft first</option>}</select><p className="muted">Scene plans preserve the selected script revision, claims and evidence. Unavailable imagery uses an explicit source-card fallback. Timing remains estimated until voiceover is produced.</p><button className="button primary" disabled={!!busy||!script} onClick={()=>{void action('Directing scenes',async()=>{setPlan(await api<Plan>('/visuals/plans',{script_id:script!.id,expected_revision:script!.revision,style:mode}));setNotice('Source-linked visual plan saved. Rendering and broadcasting remain disabled.');});}}><Camera size={15}/>Direct scenes</button>
    <label className="field-label" htmlFor="visual-plan">SAVED VISUAL PLAN</label><select id="visual-plan" value={plan?.id??''} onChange={e=>{void api<Plan>('/visuals/plans/'+e.target.value).then(setPlan).catch(e=>setError(e.message));}}><option value="" disabled>Select a saved plan</option>{state?.plans.map(p=><option key={p.id} value={p.id}>{p.id.slice(0,8)} · script revision {p.script_revision} · {p.current_source_label}</option>)}</select>
    {plan&&<div className="scene-plan"><div className="plan-meta"><span>Revision {plan.script_revision} · {plan.current_source_label}{plan.superseded_script_revision?' · script revision superseded':''}</span><span>~{Math.round(plan.estimated_seconds)}s estimated</span><a className="button secondary" href={'/api/visuals/plans/'+plan.id+'/scenes.csv'} download><Download size={14}/>Export visual scenes CSV</a></div>{plan.scenes.map(scene=><details key={scene.id}><summary><span>{scene.id}</span><strong>{scene.type.replaceAll('_',' ')}</strong><small>{scene.target_seconds}s · {scene.camera_movement}</small></summary><p>{scene.script_segment}</p><p className="muted">Fallback: {scene.fallback_asset}</p><pre>{JSON.stringify(scene.parameters,null,2)}</pre></details>)}<label className="field-label" htmlFor="scene-csv">IMPORT CAMERA / TRANSITION EDITS</label><input id="scene-csv" type="file" accept=".csv,text/csv" disabled={!!busy} onChange={e=>{const file=e.target.files?.[0];if(!file)return;void action('Importing scene CSV',async()=>{if(file.size>500000)throw new Error('Scene CSV is too large.');const csv_text=await file.text();setPlan(await api<Plan>('/visuals/plans/'+plan.id+'/import',{csv_text}));setNotice('Presentation edits saved as a new plan. Narration and evidence remain unchanged.');});}}/><p className="muted">CSV imports may change supported camera movement and cut/dissolve transitions. Weather data, narration, attribution and timing cannot be replaced.</p></div>}
    </div></section>
  </>;
}
