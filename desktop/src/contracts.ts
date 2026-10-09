export type Fact = string | number | null;
export interface Advisory {
  id: string; provider: 'NHC' | 'NWS' | 'TRAINING'; event_key: string; title: string;
  issued_at: string; expires_at: string | null; source_url: string; provenance: string;
  severity: string; area: string; text: string; facts: Record<string, Fact>;
  freshness: string; previous_id: string | null;
  changes: {field: string; previous: Fact; current: Fact; delta: number | null}[];
  event_id: string; superseded_by: string | null; warnings: string[]; forecast_excerpt: string | null;
  verification: {status: string; checks: {check: string; passed: boolean}[]; manual_review_required: boolean; confidence_note: string};
  priority: Priority;
  comparison: {status: string; previous_source_url: string | null};
}
export interface Priority {score: number; tier: string; reasons: string[]}
export interface Feed {
  id: string; url: string; enabled: boolean; interval_seconds: number; status: string;
  last_attempt_at: string | null; last_success_at: string | null; next_poll_at: string | null;
  last_error: string | null; collected_count: number; inserted_count: number; rejected_count: number; consecutive_failures: number;
}
export interface NewsEvent {id: string; latest_advisory_id: string; title: string; provider: string; status: string; priority: Priority; advisory_ids: string[]; last_issue_at: string}
export interface Intelligence {
  feeds: Feed[]; events: NewsEvent[];
  quarantine: {id: string; feed_id: string; source_identifier: string; reason: string; last_seen_at: string}[];
}
export interface Script {
  id: string; advisory_id: string; title: string; text: string; status: string; label: string;
  source_refs: string[]; estimated_seconds: number; broadcast_eligible: boolean;
  source_issued_at: string; qc: {check: string; passed: boolean}[];
  scenes: {id: string; type: string; target_seconds: number; script_segment: string}[];
  revision: number; is_latest: boolean; run_id?: string; engine: string; review_valid: boolean;
  claims: Claim[];
  evidence_manifest: {id: string; checksum: string; source_url: string; issued_at: string; expires_at: string | null; provenance: string}[];
  editorial: {issues: {code: string; blocking: boolean; message: string; claim_id?: string}[]; can_review: boolean; high_impact: boolean; timing_basis: string; claim_validation: string};
  versions: {revision: number; editor: string; note: string; created_at: string}[];
  reviews: {id: string; revision: number; reviewer: string; note: string; created_at: string}[];
}
export interface Claim {id: string; text: string; status: string; source_advisory_ids: string[]; support: {reviewer: string; quote: string; explanation: string; note: string} | null}
export interface Engine {id: string; name: string; configured: boolean; mode: string}
export interface NewsroomRun {id: string; advisory_id: string; engine: string; status: string; script_id: string | null; error: string | null; created_at: string}
export interface RunDetail extends NewsroomRun {steps: {sequence: number; agent: string; status: string; input: unknown; output: unknown; error: string | null; started_at: string; finished_at: string | null}[]}
export interface Dashboard {
  channel: {name: string; id: string; auto_broadcast: boolean};
  advisories: Advisory[]; scripts: Script[];
  jobs: {id: string; kind: string; status: string; detail: string; created_at: string}[];
  stats: {stored_advisories: number; current_alerts: number; scripts: number; programs: number};
  latest_official_issue: string | null;
  agents: {name: string; status: string}[];
  broadcast: {status: string; obs_connected: boolean; fallback_ready: boolean};
  intelligence: Intelligence;
  newsroom: {runs: NewsroomRun[]; engines: Engine[]};
}
export interface Health {status: string; version: string; capabilities: Record<string, boolean>}
