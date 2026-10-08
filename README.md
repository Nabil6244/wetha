# Weather Intelligence Studio

A standalone Electron + React + TypeScript application with a local Python/FastAPI service and versioned SQLite storage. **Phase 3 adds a recorded six-role newsroom, versioned script editor and claim review** to the official weather intelligence pipeline. This is not a production broadcasting system.

The initial channel is **US Extreme Weather**. No paid API or existing Semantic YT Studio installation is required.

## What works

- Dark broadcast control center with real backend state and local runtime capability checks.
- Live NWS active-alert collection and NHC Atlantic public-advisory ingestion through official RSS. Historical NHC archive fetching is also implemented, but the tested archive page returns a source-side 403 in this cloud instance.
- NHC text import with strict timestamp, position, unit, and source-URL validation. Pasted text remains unverified until an identical official fetch confirms it.
- Persistent advisory evidence, deduplication, previous-advisory comparison, and **What changed?** measurements.
- Six newsroom roles with typed JSON handoffs, durable run/stage status and inspectable evidence packages.
- Source-linked English drafts with original forecast wording and revision-specific scene CSV exports.
- Immutable script revision history, optimistic editing conflicts, paragraph-level claim support and named quote-based attestations.
- Revision-specific review records that invalidate after edits, source updates or expiry.
- Optional Ollama/Gemini composition adapters; model output can only arrange existing grounded blocks. No mandatory model or paid API.
- Named editorial review of current, officially fetched operational evidence. Training, stale, superseded, or unverified source packages are blocked.
- Versioned database migration, durable collection job results, and restart handling for interrupted jobs.
- Persistent feed health, conditional ETag/Last-Modified caching, bounded retries, and opt-in background polling with saved schedules and failure backoff.
- Linked NWS updates/cancellations, active-feed withdrawal checks, immutable evidence quarantine, and event timelines.
- Deterministic editorial priority, explicit verification checks, original forecast wording, and watch/warning comparisons.
- Electron backend ownership, loopback-only access, readiness checks, isolated renderer, and process cleanup.

No draft is broadcast eligible. TTS, maps/satellite animation, media import, video rendering, OBS automation, and 60-minute programs are later phases. Their screens explicitly show this state. The synthetic training dataset is never presented as real observations.

## Develop

Use Node **24** and Python **3.12**. Commands below run from the repository root. The Python environment is isolated and dependencies are pinned with artifact hashes.

```sh
uv venv .venv --python python3
uv pip sync backend/requirements.lock --python .venv/bin/python --require-hashes
npm ci
```

On Windows use `--python python` when creating the environment and `.venv/Scripts/python.exe` when syncing it. Without uv, create the environment using `python -m venv .venv` and install using its Python with `-m pip install --require-hashes -r backend/requirements.lock`.

```sh
npm run dev       # FastAPI + Vite, both on loopback
npm run desktop   # Build the UI, then launch Electron with its own backend
```

On a cloud machine with a proxy, use `bash scripts/setup.sh`. Electron 44 downloads its native executable on first use; the setup script downloads it explicitly with the package-provided checksum verification. `NODE_USE_ENV_PROXY=1` lets Node 24 use the provided proxy and `NODE_EXTRA_CA_CERTS` must retain the supplied trust configuration. No checksum or TLS verification is disabled.

The developer backend binds to `127.0.0.1:8000`; the renderer uses `127.0.0.1:5173`. Electron serves the built renderer through a backend on an available loopback port. Cloud onboarding validates these locally and does not expose a public preview.

### First workflow

1. Use Refresh sources to collect both NWS active alerts and NHC Atlantic public advisories. Inspect each source's last successful check and any quarantined records.
2. Open Weather Intelligence. Events are ranked by severity, recency, relevance, and verified changes; filters support provider, region/search, and all advisory versions.
3. Select an event, inspect its evidence verification, **What changed?**, and chronological source timeline. NHC forecasts and watches/warnings retain the original source wording.
4. Start polling for either source if desired. Intervals of 1–60 minutes and enabled state persist across restarts; polling is paused by default. Pausing stops future polls and lets any current collection finish.
5. Run AI Newsroom for an advisory and inspect the six JSON handoffs, or create a source-linked script directly from the evidence desk.
6. Open Script Editor, edit narration and save a named revision. Unmatched edits require a supporting source quotation and named human attestation. Previous approval is cleared; history stays intact.
7. Record named editorial approval of the latest revision and export its scene plan. Unsupported claims, stale feeds, withdrawn alerts, cancellations, superseded versions, and unverified comparisons cannot pass current-news review.
8. For offline exploration, load the explicitly labeled training dataset. Archive text imports remain unverified; official archive fetches keep their historical timestamps.

For current reporting, NWS validity uses its actual expiry time and a recent successful feed check, rather than a blanket six-hour cutoff. The source-check limit is the greater of 15 minutes and three configured polling intervals. NHC advisories also retain a six-hour issue-age limit. Polling never starts a render or broadcast.

Required destinations: `api.weather.gov`, `www.nhc.noaa.gov`; future satellite work also needs `www.star.nesdis.noaa.gov`. Official source requests have bounded retries and do not follow redirects to unapproved domains.

## Validate

```sh
npm test          # Python API, evidence, migration, and safety tests
npm run build     # Strict TypeScript check and production UI build
npx playwright install chromium
npm run test:ui   # Real browser evidence-to-script workflow
```

If Chromium is already installed, set `WETHA_CHROMIUM` to its executable path rather than downloading another copy. On this cloud machine:

```sh
WETHA_CHROMIUM=/usr/bin/chromium npm run test:ui
```

UI tests own both servers, use a fresh temporary database per run, and refuse occupied ports. Tests include captured official NOAA responses with provenance/checksums in `backend/tests/fixtures/`, plus explicitly synthetic edge cases. Provider tests mock HTTP transport; live feed access is validated separately and recorded in [Phase 2 validation](docs/PHASE_2.md).

Optional model configuration and its limitations are described in [Phase 3](docs/PHASE_3.md). Default drafting is local and works without an API key. Live Ollama/Gemini access has not been validated.

## Storage and configuration

- Development database: `.local/data/studio.sqlite3` (ignored).
- Electron database and logs: the OS application-data directory provided by Electron.
- `WETHA_DATA_DIR`: optional backend data directory.
- `WETHA_PYTHON`: optional absolute Python interpreter for a development environment.
- `WETHA_UI_DIR`: optional path to the built renderer.
- Do not store credentials in tracked files or paste them into scripts.

The backend must remain bound to loopback. This milestone is a single-user local application with one backend process per database; remote hosting and distributed concurrency are outside its current contract.

See [architecture and contracts](docs/ARCHITECTURE.md), [packaging prerequisites](docs/PACKAGING.md), [third-party licensing](docs/THIRD_PARTY.md), and [the full build brief](docs/BUILD_BRIEF.md).
