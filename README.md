# Weather Intelligence Studio

A standalone Electron + React + TypeScript application with a local Python/FastAPI service and versioned SQLite storage. This is **Phase 1 and the first evidence-to-newsroom vertical slice**, not a production broadcasting system.

The initial channel is **US Extreme Weather**. No paid API or existing Semantic YT Studio installation is required.

## What works

- Dark broadcast control center with real backend state and local runtime capability checks.
- NWS active-alert collection and NHC historical public-advisory fetching (official domains must be reachable).
- NHC text import with strict timestamp, position, unit, and source-URL validation. Pasted text remains unverified until an identical official fetch confirms it.
- Persistent advisory evidence, deduplication, previous-advisory comparison, and **What changed?** measurements.
- Deterministic source-linked English drafts and structured scene plans with CSV export.
- Named editorial review of current, officially fetched operational evidence. Training, stale, superseded, or unverified source packages are blocked.
- Versioned database migration, durable collection job results, and restart handling for interrupted jobs.
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

1. Open Weather Intelligence and load the explicitly labeled training dataset to exercise the offline workflow, or import official NHC public advisory text.
2. Fetch two advisories for the same storm from the NHC archive to verify real historical changes. The UI accepts the official archive URL; old advisories remain archival.
3. Select the latest advisory and inspect **What changed?**.
4. Create a source-linked script, inspect its source references and editorial gate, and export the scene plan.
5. Use Refresh sources to collect current NWS alerts when `api.weather.gov` is reachable.

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

UI tests own both servers, use a separate ignored database, and refuse occupied ports. Fixtures in tests are synthetic, not NOAA historical observations. Network-provider tests use mocked responses; passing them does not establish live NOAA connectivity.

## Storage and configuration

- Development database: `.local/data/studio.sqlite3` (ignored).
- Electron database and logs: the OS application-data directory provided by Electron.
- `WETHA_DATA_DIR`: optional backend data directory.
- `WETHA_PYTHON`: optional absolute Python interpreter for a development environment.
- `WETHA_UI_DIR`: optional path to the built renderer.
- Do not store credentials in tracked files or paste them into scripts.

The backend must remain bound to loopback. This first milestone is a single-user local application; remote hosting and distributed concurrency are outside its current contract.

See [architecture and contracts](docs/ARCHITECTURE.md), [packaging prerequisites](docs/PACKAGING.md), [third-party licensing](docs/THIRD_PARTY.md), and [the full build brief](docs/BUILD_BRIEF.md).
