import {useState} from 'react';
import {Copy, Upload} from 'lucide-react';

export interface NarrationAsset {id: string; name: string; seconds: number; duplicate?: boolean}

export async function uploadNarration(file: File, maxBytes: number): Promise<NarrationAsset> {
  if (!file.size) throw new Error('Choose a non-empty audio file.');
  if (file.size > maxBytes) throw new Error('Audio files are limited to 250 MiB.');
  const metadata = {name: file.name, kind: 'audio', context: 'narration',
    license: 'User confirms permission to use this narration in the video',
    attribution: 'User-supplied narration', source: 'Manually uploaded external narration', rights_confirmed: true};
  const response = await fetch('/api/production/media', {method: 'POST',
    headers: {'Content-Type': 'application/octet-stream', 'X-Media-Metadata': encodeURIComponent(JSON.stringify(metadata))},
    body: file, signal: AbortSignal.timeout(180000)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Audio upload failed.');
  return result;
}

export default function ManualNarration({text, label, maxBytes, disabled, onUpload, compact = false}: {
  text: string; label: string; maxBytes: number; disabled: boolean; compact?: boolean;
  onUpload: (file: File) => Promise<boolean>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const [inputKey, setInputKey] = useState(0);
  return <section className="panel" aria-label="Manual voiceover workflow">
    <div className="panel-header"><h2>2. Upload your voiceover</h2><span className="pill">No generation credits</span></div>
    <div className="detail-body">
      <p>{compact ? 'Record the complete narration above, then upload the finished audio here.' : 'Copy the narration below, record it or use your preferred voice tool, then upload the finished audio for this video.'}</p>
      <p className="muted">{label}</p>
      {compact ? <details><summary>Read or copy the voiceover script</summary><textarea aria-label="Voiceover script" readOnly value={text} rows={8} style={{width:'100%'}}/></details> : <>
      <textarea aria-label="Voiceover script" readOnly value={text} rows={8} style={{width:'100%'}}/>
      <button className="button secondary" disabled={disabled || !text} onClick={() => {
        void navigator.clipboard.writeText(text).then(() => setCopyStatus('Script copied.')).catch(() => setCopyStatus('Select the script above and copy it manually.'));
      }}><Copy size={15}/>Copy voiceover script</button>
      {copyStatus && <p role="status">{copyStatus}</p>}
      </>}
      <form onSubmit={e => {e.preventDefault(); if (file) void onUpload(file).then(success => {
        if (success) {setFile(null); setRights(false); setInputKey(old => old+1);}
      });}}>
        <label className="field-label">UPLOAD NARRATION AUDIO<input key={inputKey} aria-label="UPLOAD NARRATION AUDIO" type="file" required
          disabled={disabled} accept=".wav,.mp3,.m4a,.flac,.ogg" onChange={e => {setFile(e.target.files?.[0] ?? null); setRights(false);}}/></label>
        <p className="muted">WAV, MP3, M4A, FLAC or OGG · up to 250 MiB. Audio stays in your local library.</p>
        <label className="production-check"><input type="checkbox" checked={rights} disabled={disabled}
          onChange={e => setRights(e.target.checked)}/>I have permission to use this voiceover in my video.</label>
        <button className="button primary" disabled={disabled || !file || !rights} type="submit"><Upload size={15}/>Upload audio for this video</button>
      </form>
    </div>
  </section>;
}
