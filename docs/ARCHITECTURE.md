# Application foundation, weather intelligence and Phase 3 newsroom

```text
desktop/
  electron/main.cjs       Native app lifecycle and owned Python process
  src/contracts.ts       Typed renderer API contracts
  src/api.ts             Local HTTP transport with errors and timeouts
  src/App.tsx            Control center, evidence desk, scripts, review
  src/components/        Source polling controls and evidence workspace
  src/styles.css         Tailwind and application design system
backend/
  app/contracts.py       Validated advisory and request schemas
  app/weather.py         NHC parser, NWS provider, retries, differences
  app/transport.py       Bounded HTTPS reads and durable conditional cache
  app/collector.py       Owned background polling and coalesced collections
  app/intelligence.py    CAP event grouping, live verification and priority
  app/newsroom.py        Source-backed narration and pluggable media interfaces
  app/pipeline.py        Six roles with typed JSON handoffs and durable runs
  app/editorial.py       Claim tracking, quote attestations and review evaluation
  app/models.py          Constrained optional Ollama/Gemini composition
  app/storage.py         SQLite transactions, migrations, durable jobs
  app/main.py            API, local-origin guard, static renderer serving
  app/fixtures.py        Explicit synthetic offline training data
  migrations/            Ordered database schema migrations
  tests/                 Reproducible API and evidence workflow tests
scripts/                 Local startup, setup, packaging preflight
tests/                   Chromium end-to-end workflow
```

The renderer never receives Node filesystem or process access. Electron owns the backend, selects a loopback port, waits for a functional health response, and terminates its child on quit. Native application data survives restart. The backend restricts host and origin access and serves the built UI. External links are limited to official weather domains.

SQLite connections enable foreign keys and use WAL with a 15-second busy timeout. Migration application and its version record commit together. Advisory IDs and content checksums deduplicate evidence. Different content for a stored NHC advisory ID is rejected rather than silently replacing source evidence. An identical official fetch may promote a manual import to verified provenance. Interrupted collection jobs are marked failed at restart instead of displayed as running indefinitely.

## Initial database schema

| Table | Persistent contract |
|---|---|
| `schema_migrations` | Version and application time; ordered SQL changes |
| `advisories` | ID, provider, event key, UTC issue time, SHA-256 evidence checksum, normalized JSON, ingestion time |
| `scripts` | ID, advisory foreign key, source-linked JSON document, creation time |
| `jobs` | ID, kind, running/succeeded/failed status, detail, creation/update times |
| `channel_profiles` | Channel ID and isolated configuration JSON |
| `feeds` | Enabled state, interval, persistent schedule, health, attempts, success time, failures, counts |
| `http_cache` | Last response, checksum, ETag/Last-Modified, last network check |
| `feed_members` | Current IDs from a successfully completed provider refresh |
| `rejected_evidence` | Original invalid/conflicting payloads, reasons, first/last observation, resolution timestamp |
| `news_events` | Rebuilt event projections and priority; immutable advisories remain authoritative |
| `newsroom_runs` / `agent_steps` | Run identity/status and ordered versioned JSON handoffs, timestamps and errors |
| `script_versions` | Immutable narration revisions with editor/note/time and source manifests |
| `editorial_reviews` | Exact revision, reviewer, note/time and evidence reviewed |

Future voiceovers, licensed assets, render outputs, and broadcast history receive their own migrations. They are not represented by fabricated records in this milestone. Rendering and broadcasting will run independently; this milestone starts neither process.

## Service interfaces

Pydantic `Advisory` preserves provider, source URL, issue and expiry times, provenance, severity, text, and extracted facts with units in their keys. Timezones are mandatory and normalized to UTC. NHC import checks include source domain/path identity, wind-unit consistency, geographic limits, central pressure bounds, and future timestamps. Manual imports remain unverified even if their URL is official.

Provider, scriptwriter, voice, renderer, and broadcast interfaces are Python protocols. Providers, the six newsroom roles and optional constrained composition adapters have implementations. Voice, rendering and broadcasting remain interfaces. They can be replaced without changing advisory storage or renderer contracts.

| API | Purpose |
|---|---|
| `GET /api/health` | Service/database readiness and actual binary availability |
| `GET /api/dashboard` | Persisted state, advisory details, jobs, and explicit module status |
| `GET /api/advisories` | Source packages, freshness, previous ID, differences |
| `POST /api/advisories/import` | Import NHC public text as unverified evidence |
| `POST /api/advisories/fetch` | Fetch an allowed NHC archive URL with official provenance |
| `POST /api/providers/nws/refresh` | Collect and store NWS active alerts |
| `POST /api/providers/nhc/refresh` | Collect NHC Atlantic public advisories from official RSS |
| `POST /api/sources/refresh` | Independently refresh both feeds and return individual results |
| `GET /api/intelligence` | Feed health, grouped events, and quarantine summaries |
| `POST /api/feeds/{id}/polling` | Save enable/disable and interval; wake the owned worker |
| `GET /api/events/{id}` | Chronological linked advisory evidence and changes |
| `GET /api/advisories/{id}/evidence` | Original preserved provider payload and checksum |
| `POST /api/training/load` | Idempotently load labeled synthetic fixtures |
| `POST /api/scripts` | Generate a deterministic draft for a stored advisory |
| `POST /api/scripts/{id}/review` | Record named editorial review after fresh official-source checks |
| `GET /api/scripts/{id}/scenes.csv` | Export source-linked estimated scene instructions |

OpenAPI is generated by FastAPI. TypeScript contracts mirror the initial responses. Automated OpenAPI-to-TypeScript generation is a future improvement.

## Acceptance for this milestone

- Backend and UI start locally and perform the evidence-to-draft workflow.
- Repeated dataset imports do not duplicate records; data and scripts survive restart.
- Comparisons use prior advisories for the same event, with issue timestamps and signed deltas.
- Drafts carry source references, provenance labels, and original issue times.
- Review checks freshness again at the time of review; expired, superseded, training, unverified, test, and cancellation evidence cannot pass.
- Editorial review never implies broadcast readiness. Audio and video are unavailable and the broadcast queue remains empty.
- UI build/typecheck and meaningful Python/browser tests pass.

Live NWS and NHC RSS collection has been validated in this instance. The tested historical NHC archive page returns CloudFront 403 and remains an outstanding access limitation. Native Windows/macOS lifecycle and installer testing require those hosts and bundled Python runtimes. See [Phase 2 contracts and validation](PHASE_2.md).

## Next milestones

1. Phase 4 visuals: real geographic maps, observed GOES/radar layers, camera motion and source timestamps.
   Phase 3 is implemented; see [its source/claim/model contracts and validation](PHASE_3.md).
2. Additional historical hurricane fixtures once archive access is available; deeper geographic priority rules and source-specific correlation.
3. MapLibre, timestamped GOES/radar layers, licensed local media, and visual evidence timelines.
4. Verified local TTS, alignment, FFmpeg rendering, media quality checks, and 30-second then five-minute outputs.
5. Hourly assembly, independent OBS automation, safe queues/fallbacks, and 24-hour soak tests.
6. Redistributable platform runtime bundles, installers, signing, notarization, and target-platform verification.
