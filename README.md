# Weather Intelligence Studio

A standalone Electron + React + TypeScript application with a local Python/FastAPI service and versioned SQLite storage. **Phase 5 adds licensed local media, manual timelines and validated FFmpeg video previews** to the official weather intelligence pipeline. Local voiceover generation is excluded; optional narration audio can be imported. This is not a production broadcasting system.

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
- Local MapLibre country map, official advisory centers/polygons, eased camera controls and animated What Changed graphics.
- Timestamped GOES/radar adapters and conservative NHC cone parsing, with verified local media caching and explicit source failures. Live GOES and nowCOAST collection and playback were verified; NHC forecast-cone downloads still return HTTP 403.
- A complete 60-second historical episode with actual archived NHC cone/forecast points/coastal warning lines, NWS rainfall, real observation loops, measured statistics and short licensed footage cuts. See [Complete episode](docs/COMPLETE_EPISODE.md).
- Twelve-chapter one-hour deep-dive planning, content/repetition audit and six reusable source-bound motion graphic styles. The full hour requires expanded content and final assembly; see [One-hour program](docs/ONE_HOUR_PROGRAM.md).
- Revision-bound visual plans with presentation-only scene CSV import/export.
- Licensed local image/video/audio imports with measured durations, provenance, duplicate detection and checksum validation.
- Expanded Florida footage bank with event/location metadata and 46 short cut ranges across archival weather, damage, cleanup, relief and coastal illustration. See [Footage bank](docs/FOOTAGE_BANK.md).
- Revision-bound production timelines with manual timing, clip trimming, source-linked captions and optional imported narration.
- Background 1080p H.264/AAC renders, preview/download, source/license manifests, cancellation, scene-cache retry and output quality checks.
- Electron backend ownership, loopback-only access, readiness checks, isolated renderer, and process cleanup.

No draft or rendered preview is broadcast eligible. Local TTS is excluded; OBS automation and 60-minute programs are later phases. Satellite/radar views require successful collection and explicitly show unavailable observations or source failures. The synthetic training dataset is never presented as real observations.

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

Install FFmpeg and FFprobe and make them available on PATH for Phase 5 media import and video rendering. Open **Media Library** to import licensed media, then **Video Production** to assemble and render. Video Production can also collect and render real NOAA satellite observations with preserved timestamps and source credits. No narration model or paid API is required. See [Phase 5](docs/PHASE_5.md) for supported graphics, timing, validation and current limits.

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
8. Open Visual Director to inspect actual geographic evidence, compare advisory measurements, and direct scenes from a pinned script revision. Collect satellite/radar observations manually; source failures preserve cached evidence.
9. For offline exploration, load the explicitly labeled training dataset. Archive text imports remain unverified; official archive fetches keep their historical timestamps.

For current reporting, NWS validity uses its actual expiry time and a recent successful feed check, rather than a blanket six-hour cutoff. The source-check limit is the greater of 15 minutes and three configured polling intervals. NHC advisories also retain a six-hour issue-age limit. Polling never starts a render or broadcast.

Required destinations: `api.weather.gov`, `www.nhc.noaa.gov`; visual observation collection also needs `www.star.nesdis.noaa.gov`, `cdn.star.nesdis.noaa.gov`, and `nowcoast.noaa.gov`. Official source requests have bounded retries and do not follow redirects to unapproved domains.

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

See [Phase 5](docs/PHASE_5.md) for local production, and [Phase 4](docs/PHASE_4.md) for source projection, timestamp, map resolution and current access limits. Optional model configuration and its limitations are described in [Phase 3](docs/PHASE_3.md). Default drafting is local and works without an API key. Live Ollama/Gemini access has not been validated.

## Manual voiceover

In **Script Editor**, use **Copy script** to record narration with your preferred tool.
In **Video Production**, choose or prepare a scene plan, then use **Upload your voiceover**.
Its copy button includes the exact scene narration, including any rewritten story draft.
Upload WAV, MP3, M4A, FLAC or OGG (up to 250 MiB and one hour); the app validates
the file, measures its duration, and selects it for the timeline. Listen to the audio,
use **Fit timing to audio**, confirm it matches the script, then check, save and render.
This uses local processing and no paid generation service.

Timing fit distributes whole video frames across scenes (1–120 seconds per scene).
It clears the fixed 30/60/90-second template. Review scene changes manually: it does
not transcribe speech or detect sentence boundaries. Timed footage sequences need
manual cut adjustments; insufficient footage is caught by the existing timing checks.
Choosing a different plan clears the narration selection and its confirmation.

## Storage and configuration

- Development database: `.local/data/studio.sqlite3` (ignored).
- Electron database and logs: the OS application-data directory provided by Electron.
- `WETHA_DATA_DIR`: optional backend data directory.
- `WETHA_PYTHON`: optional absolute Python interpreter for a development environment.
- `WETHA_UI_DIR`: optional path to the built renderer.
- Do not store credentials in tracked files or paste them into scripts.

The backend must remain bound to loopback. This milestone is a single-user local application with one backend process per database; remote hosting and distributed concurrency are outside its current contract.

See [architecture and contracts](docs/ARCHITECTURE.md), [packaging prerequisites](docs/PACKAGING.md), [third-party licensing](docs/THIRD_PARTY.md), and [the full build brief](docs/BUILD_BRIEF.md).

### Cinematic broadcast benchmark

Broadcast scenes offer four **Map type** treatments: reported movement, warning
coverage, radar observations and forecast outlook. Each retains source and time
labels, with explicit fallbacks for missing layers. See
[map treatments and source requirements](docs/MAP_TREATMENTS.md).

Video Production includes **Build story draft** for a local, source-linked hook,
evidence sequence and closing takeaway. The renderer adds story captions over
footage and automatically frames reported map positions. See
[story-first drafting and its limits](docs/STORY_FIRST.md).

Media Library includes **Discover free weather footage**: previews, credits,
reviewed stock clips, Wikimedia search and licensed YouTube-origin archives.
Selected sources can be imported into the existing automatic editor. See
[available sources and discovery limitations](docs/MEDIA_DISCOVERY.md).

Video Production can now suggest and apply an exact 30-second draft from the
local media library, preserving source-linked scenes and data graphics. Tag
footage in Media Library, then use **Suggest 30-second edit** and **Check visuals
& timing**. See [automatic short-edit workflow](docs/AUTOMATIC_SHORT_EDIT.md).

The **Edit template** selector also offers 60- and 90-second reports with
multiple 3–4-second footage segments per script scene. Maps and statistics
remain visible; insufficient footage blocks applying the draft. See
[report templates](docs/REPORT_TEMPLATES.md).

The first mixed-footage sample adds free stock footage and a license-reviewed
YouTube-origin archival clip with four-second cuts. Run
`.venv/bin/python scripts/render-mixed-sample.py` with the downloaded local media
pool to reproduce it. See [sample, sources and remaining work](docs/MIXED_SAMPLE.md).

The new **Broadcast** production style uses source geography and measured statistics with short lower thirds. Video Production also previews the verified 30-second Isaias AL092020 historical benchmark after running `.venv/bin/python scripts/render-benchmark.py`. It uses genuine NWS satellite/radar loops, NHC positions and an explicit ground-footage fallback. See [Phase 7 implementation and limitations](docs/PHASE_7.md).

Media Library supports YouTube source records for locally supplied, authorized video files. Choose **YouTube clip**, record the original URL and reuse evidence, then select the asset in a timeline for a default 3.5-second cut. This is not an automatic YouTube downloader.

Video Production now opens with a completed **90-second documentary edit**:
24 shots, continuous real imagery, traveling maps and measured statistics over
the action. Rebuild it locally with `.venv/bin/python scripts/render-documentary.py`.
The preview includes sources, licenses and downloadable captions. See
[documentary edit and remaining one-hour requirements](docs/DOCUMENTARY_EDIT.md).

Regional scenes now require location-reviewed footage and state-focused maps.
Choose **Regional Focus** per scene and save **Capture Region** evidence in Media
Library. Out-of-region clips are excluded, storm-wide figures cannot become local
measurements, and missing regional weather layers are flagged. See
[regional matching, source requirements and current limits](docs/REGIONAL_RELEVANCE.md).

## Narrated regional chapter

The South Florida historical chapter combines region-reviewed footage, local station measurements and original NHC forecast/warning layers. It uses the free installed macOS Samantha voice and no paid generation calls. See [Florida chapter](docs/FLORIDA_CHAPTER.md) for the render command, source pack and editorial limitations. The validated movie appears at the top of Video Production.

## Forecast-news bulletin

The first current Florida bulletin uses official NWS hourly point forecasts through 72 hours, active alerts, and matching NHC forecast/warning geometry. Recorded editions preserve their source dates and show refresh status. See [Forecast news](docs/FORECAST_NEWS.md) for collection, rendering, source scope and refresh requirements.
