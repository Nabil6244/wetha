import {useEffect, useRef, useState} from 'react';
import {api} from '../api';

type Storage = {categories:Record<string,number>;total_bytes:number;scene_cache_bytes:number;temporary_bytes:number;response_cache_bytes:number;weather_asset_bytes:number;database_reclaimable_bytes:number;free_bytes:number;data_directory:string;busy:boolean;render_workers:number;video_encoder:string;retention_days:number};
const bytes=(value:number)=>value>=1024**3?`${(value/1024**3).toFixed(2)} GB`:value>=1024**2?`${(value/1024**2).toFixed(1)} MB`:`${Math.ceil(value/1024)} KB`;
const labels:Record<string,string>={media:'Uploaded audio and footage',renders:'Videos and render working files',observations:'Pinned weather imagery',storyboards:'Storyboards',quarantine:'Quarantined imports',database:'Database and source evidence',manual_footage:'Your manual footage folder',alignment:'Saved audio timing'};

export default function StorageSettings(){
  const [data,setData]=useState<Storage|null>(null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const pending=useRef(false);
  async function refresh(){setError('');try{setData(await api<Storage>('/storage'));}catch(e){setError(e instanceof Error?e.message:'Storage details unavailable.');}}
  useEffect(()=>{void refresh();},[]);
  async function clean(kind:string){
    if(pending.current)return;
    pending.current=true;setBusy(kind);setError('');setNotice('');
    try{const result=await api<{reclaimed_bytes:number;removed_files:number}>(`/storage/cleanup/${kind}`,{});
      setNotice(`${bytes(result.reclaimed_bytes)} cleared. Your scripts, uploads and final videos are preserved.`);
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:'Cleanup could not finish.');}finally{pending.current=false;setBusy('');}
  }
  return <section className="panel storage-settings" aria-label="Storage and performance"><div className="panel-header"><h2>Storage &amp; performance</h2><button className="button secondary" disabled={!!busy} onClick={()=>void refresh()}>Refresh storage</button></div><div className="detail-body">
    {error&&<p role="alert">{error} <button className="button secondary" onClick={()=>void refresh()}>Retry storage</button></p>}
    {notice&&<p role="status">{notice}</p>}
    {!data&&!error&&<p role="status">Measuring storage…</p>}
    {data&&<><p><strong>{bytes(data.total_bytes)}</strong> in this workspace · {bytes(data.free_bytes)} free on disk</p>
      <div className="settings-rows">{Object.entries(data.categories).map(([name,size])=><div key={name}><span>{labels[name]??name}</span><strong>{bytes(size)}</strong></div>)}</div>
      <p>Video encoding: <strong>{data.video_encoder==='libx264'?'CPU · hardware encoder unavailable':`${data.video_encoder} · hardware accelerated`}</strong> · {data.render_workers} scene workers</p>
      <p className="muted">Charts and map drawing use the CPU. Compatible video encoding uses hardware automatically, with a CPU fallback.</p>
      <div className="settings-rows"><div><span>Regenerable scene cache</span><strong>{bytes(data.scene_cache_bytes)}</strong></div><div><span>Abandoned temporary uploads</span><strong>{bytes(data.temporary_bytes)}</strong></div><div><span>Downloaded source response cache</span><strong>{bytes(data.response_cache_bytes)}</strong></div><div><span>Free database space</span><strong>{bytes(data.database_reclaimable_bytes)}</strong></div></div>
      <p className="muted">Scene caches older than {data.retention_days} days are removed when the app starts. Clearing them now makes future retries render those scenes again. Weather evidence, scripts, uploaded media, final videos and their reports stay saved. Source response cleanup may require another download. Compact database returns unused database space to disk.</p>
      {data.busy&&<p role="status">Cleanup is paused while production or collection is running. Refresh storage when it finishes.</p>}
      <div className="storage-cleanup-actions">{[['scene_cache','Clear scene cache'],['temporary','Clear temporary files'],['source_responses','Clear source response cache'],['compact','Compact database']].map(([kind,label])=><button key={kind} className="button secondary" disabled={!!busy||data.busy} onClick={()=>void clean(kind)}>{busy===kind?'Working…':label}</button>)}</div>
      <details><summary>Data location &amp; saved projects</summary><p className="muted">{data.data_directory}</p><p>Project deletion is separate from cache cleanup. These controls preserve saved projects and your current draft.</p></details>
    </>}
  </div></section>;
}
