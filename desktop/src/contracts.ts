export type Fact = string | number | null;
export interface Advisory {
  id: string; provider: 'NHC' | 'NWS' | 'TRAINING'; event_key: string; title: string;
  issued_at: string; expires_at: string | null; source_url: string; provenance: string;
  severity: string; area: string; text: string; facts: Record<string, Fact>;
  freshness: string; previous_id: string | null;
  changes: {field: string; previous: Fact; current: Fact; delta: number | null}[];
}
export interface Script {
  id: string; advisory_id: string; title: string; text: string; status: string; label: string;
  source_refs: string[]; estimated_seconds: number; broadcast_eligible: boolean;
  source_issued_at: string; qc: {check: string; passed: boolean}[];
  scenes: {id: string; type: string; target_seconds: number; script_segment: string}[];
}
export interface Dashboard {
  channel: {name: string; id: string; auto_broadcast: boolean};
  advisories: Advisory[]; scripts: Script[];
  jobs: {id: string; kind: string; status: string; detail: string; created_at: string}[];
  stats: {stored_advisories: number; current_alerts: number; scripts: number; programs: number};
  latest_official_issue: string | null;
  agents: {name: string; status: string}[];
  broadcast: {status: string; obs_connected: boolean; fallback_ready: boolean};
}
export interface Health {status: string; version: string; capabilities: Record<string, boolean>}
