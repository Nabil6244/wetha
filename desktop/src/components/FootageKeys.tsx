import {useEffect, useState} from 'react';
import {KeyRound} from 'lucide-react';
import {api} from '../api';

type Provider = 'pexels' | 'pixabay';
type Status = Record<Provider, {configured: boolean; source: string | null}>;
const LINKS: Record<Provider, [string, string]> = {pexels: ['Pexels', 'https://www.pexels.com/api/'], pixabay: ['Pixabay', 'https://pixabay.com/api/docs/']};

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {method, headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Request failed');
  return result as T;
}

export default function FootageKeys() {
  const [status, setStatus] = useState<Status | null>(null);
  const [values, setValues] = useState<Record<Provider, string>>({pexels: '', pixabay: ''});
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {void api<Status>('/settings/footage-keys').then(setStatus).catch(e => setError(e.message));}, []);
  async function run(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try {await task();} catch (e) {setError(e instanceof Error ? e.message : 'Request failed');} finally {setBusy(false);}
  }
  const save = (changes: Partial<Record<Provider, string>>, message: string) => run(async () => {
    setStatus(await send<Status>('/settings/footage-keys', 'PUT', changes));
    setValues({pexels: '', pixabay: ''}); setNotice(message);
  });
  const test = () => run(async () => {
    const result = await send<Record<Provider, {ok: boolean; message: string}>>('/settings/footage-keys/test', 'POST', {});
    setNotice((Object.keys(result) as Provider[]).map(p => `${LINKS[p][0]}: ${result[p].message}`).join(' · '));
  });
  return <section className="panel" aria-label="Footage provider keys"><div className="panel-header"><h2><KeyRound size={17}/>Footage provider keys</h2></div><div className="detail-body">
    <p className="muted">Free keys turn on licensed stock video search. Keys are saved only on this computer, in the app's private data folder with owner-only access. They are never shown again, logged, or sent anywhere except to that provider.</p>
    {(Object.keys(LINKS) as Provider[]).map(provider => <form key={provider} className="production-actions" onSubmit={e => {e.preventDefault(); if (values[provider].trim()) void save({[provider]: values[provider]}, `${LINKS[provider][0]} key saved.`);}}>
      <label>{LINKS[provider][0].toUpperCase()} API KEY
        <input type="password" autoComplete="off" spellCheck={false} aria-label={`${LINKS[provider][0]} API key`} placeholder={status?.[provider]?.configured ? 'Saved · paste to replace' : 'Paste key'}
          value={values[provider]} onChange={e => setValues(old => ({...old, [provider]: e.target.value}))}/></label>
      <span className="pill">{status?.[provider]?.configured ? (status[provider].source === 'environment' ? 'Set by environment' : 'Saved') : 'Not set'}</span>
      <button className="button secondary" disabled={busy || !values[provider].trim()} type="submit">Save</button>
      {status?.[provider]?.source === 'saved in app' && <button className="text-button" type="button" disabled={busy} onClick={() => void save({[provider]: ''}, `${LINKS[provider][0]} key removed.`)}>Remove</button>}
      <a href={LINKS[provider][1]} target="_blank" rel="noreferrer">Get a free key</a>
    </form>)}
    <button className="button secondary" disabled={busy || !(status?.pexels.configured || status?.pixabay.configured)} onClick={() => void test()}>Test connection</button>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" className="production-error">{error}</p>}
  </div></section>;
}
