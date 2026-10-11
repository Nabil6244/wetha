# Automatic production engine

You pick the stories, write the final script, record the voiceover and upload both. One click on **Make final video** starts a saved production job that does everything else and returns a finished MP4 with a production report, a thumbnail, and a title and description.

## What the job does

`POST /api/production/auto` creates a job in the `production_jobs` table and runs these stages. Each one reuses the existing module instead of a parallel copy.

| Stage | What happens | Module |
|---|---|---|
| Validate | Checks the script plan, its source audit and the voiceover file | `production.validate_plan` |
| Align | Local faster-whisper word timing, reused when it was already done for this exact script and audio. If alignment fails, your fitted scene timing is used, and the job says so. | `alignment` |
| Plan | Splits the narration into 2.5–4 second shots cut on word starts, then builds the mixed footage edit | `automatic_edit`, `bulletin_edit` |
| Footage (optional) | Searches licensed sources for the gaps the plan reported, then plans again | `footage_expansion`, `media_discovery` |
| Timeline | Reads each beat's meaning, attaches evidence (charts, the SPC outlook), picks a visual state per shot, transitions, and a decision record per shot | `visual_director`, `visual_states`, `create_timeline` |
| Render | Parallel scene workers, scene cache, fades built as constant-cost pieces, one continuous final encode, voice with a ducked music bed | `production`, `broadcast`, `audio_polish` |
| Report | Measured quality checks, the production report, thumbnail and metadata | `production_report`, `packaging` |

Progress shows in the app under **Make final video**. Each stage shows its status and detail, alongside errors, a **Resume** button and the report summary.

### Restart and resume

The job document is saved after every stage update. When the app starts, any job left `queued` or `running` becomes `interrupted`. **Resume** (`POST /api/production/auto/{id}/resume`) runs the job again from the start. That's safe and quick, because:
- completed alignments are found again by script and audio checksum
- unchanged scenes are copied from earlier renders by an identical snapshot plus a checksummed file (`reuse_scene_cache`)
- footage already imported is detected by checksum

Renders interrupted by a restart can also be retried directly. Alignment and footage search jobs are saved to disk and report when they were interrupted.

## Visual director

`visual_director.classify` reads each beat and decides:
- **Intent:** intensification, weakening, landfall, movement, tornado, flooding, rainfall, winter, temperature, warning, uncertainty, impact, response, or context.
- **Hazard:** taken from the beat's own words, falling back to the story's advisory title.
- **Footage class:** the weather itself, its impact, the response, or an establishing shot.

Specific hazards always outrank generic framing such as "in effect" or "could". The rules are fixed and deterministic, and no model is used.

The intent ranks visual states, and only states whose evidence exists are offered:

| State | Evidence it needs |
|---|---|
| Change dial, before/after split, question reveal | Two source wind or pressure measurements |
| Key numbers card, facts panel | Numeric source facts |
| Original wording card | Source wording |
| Storm track, advisory timeline | Reported positions |
| Place callout | A catalogued place named by the story |
| Severe weather outlook | An SPC outlook valid at the story's time |
| Overview, pan, push in, pull out | Reported geography |

Variety rules still apply:
- no state repeats within 4 shots
- no two cards back to back, and no card right after a chart
- the same card for the same story waits 12 shots

Every shot stores `parameters.visual_decision` with:
- timing: start and end
- what's said: narration, story and claim
- meaning: intent, hazard and footage class
- the evidence found
- the choice: the chosen view, alternatives with scores, the reason and the fallback
- the transition and the confidence
- warnings, such as "Preferred change gauge needs two measurements; not available, so pan was used."

The full plan is saved on the timeline (`visual_plan`) and in the report.

## Footage intelligence

**Ranking** (`media_selection.rank`) scores each clip on:
- topic overlap: weather topics weigh more than impact or response topics
- the shot class the beat needs: +8 when it matches, −4 when the beat describes impact or response but the clip only shows weather
- general sky footage never outranks specific evidence (−6)
- event and date matches, a declared location named in the script, resolution, and reuse spacing

Each candidate carries:
- `shot_classes`
- `location_confidence`: `reviewed`, `provisional` (a location declared by the source) or `unknown`
- `temporal`: `current`, `archival` or `unknown`

**Clean cuts:** shot changes inside each clip are detected at import (`footage_library.detect_shots`), so cuts start on a fresh camera shot. Off-ratio clips fill the frame with a blurred copy instead of black bars. Archival clips keep their original context label on screen and in the report.

**Searching:** `footage_expansion`
- searches the biggest gaps first, up to 24 queries per run
- downloads three files at once, with up to 3 attempts with backoff for transient failures
- reserves real byte counts against a 500 MiB budget per batch
- pauses when less than 2 GiB of disk is free

**Library screen:** under Media Library, the **Footage library** panel shows clips and usable cuts by topic, region, context and event, the gaps for a selected plan, and a button that backfills shot analysis for older clips.

## Providers

| Provider | Status | Products | Key | Limits and cadence | Licence | Cache and failure behaviour |
|---|---|---|---|---|---|---|
| NHC (RSS, archive) | Live, existing | Advisories, positions, archived cones | None | Advisory every 3–6 hours | US government, public domain | ETag cache. The archive and cone downloads returned 403 from a cloud host; the reason is labelled and nothing is drawn. |
| NWS api.weather.gov | Live, existing | Active alerts and polygons | User-Agent header | Unpublished per-client limit; backoff | Public domain | Conditional requests; withdrawal checks |
| NOAA GOES (STAR) | Live, existing | GeoColor image sequences | None | About 10 minutes | Public domain, credit NOAA | Checksummed cache; missing frames labelled |
| NOAA nowCOAST | Live, existing | Radar reflectivity (Web Mercator) | None | About 5 minutes | Public domain | Checksummed cache |
| **SPC outlooks** | **New.** Fetched live once while building this; tests use mocks. | Day 1–3 categorical severe-weather risk areas | None | Day 1 several times a day | Public domain, credit NOAA/NWS SPC | Each issuance cached under its issue time; only used inside its valid period; 3 attempts with backoff, then a clear error and no outlook |
| Wikimedia Commons | Live, existing | Video and stills | None | Polite use | Per-file CC licences | 10-minute search cache |
| NASA Images API | Live, existing | ISS and archive video | None | Polite use | NASA media guidelines | Used as an alternate source |
| **Pexels** | **New. Mocked only.** | Stock video | `PEXELS_API_KEY` | 200 requests an hour, 20,000 a month | Pexels License: free use, no endorsement, no resale of unaltered copies | 24-hour search cache; skipped without a key |
| **Pixabay** | **New. Mocked only.** | Stock video | `PIXABAY_API_KEY` | 100 requests a minute | Pixabay Content License | 24-hour cache, as Pixabay requires; skipped without a key |

Not integrated yet:
- WPC rainfall forecasts, river gauges (NWPS) and flood-risk maps
- infrared and water-vapour satellite channels
- temperature, wind-field and pressure analysis maps, and forecast model comparisons
- FEMA and NOAA photo libraries
- YouTube upload

None of these are claimed to work, and the engine never draws them from estimates.

## Quality control and report

Measured on every render:
- exact duration and frame count, codecs, and a full decode
- black frames, frozen picture (6 seconds or more), silence
- integrated loudness and peak (`ebur128`) against `WETHA_LOUDNESS_TARGET` (default −16 LUFS, tolerance ±2)
- caption layout, flash captions, reading speed and blank captions
- the same view on adjacent shots, missing credit lines, missing clip attribution
- source age for current stories

Duration, frame-count and decode failures stop the render. Everything else is a finding with a severity. Geographic correctness and footage relevance are traced to their sources, not visually inspected.

Each render folder holds:
- `report.json` and `report.md`
- `metadata.json`: title options, a description with chapters, sources and footage credits, tags, and `privacy: private`
- `thumbnail.jpg`: 1280×720, made from a real frame

Serve them with `/api/production/renders/{id}/{report|report_md|metadata|thumbnail}`. Nothing is uploaded or published.

## Captions

When alignment has recognized words, each caption page appears on its first word's spoken frame. Pages are two lines of at most 42 characters. Without word timing, pages share the shot in proportion to their words.

## Performance

- **Parallel scenes:** up to `WETHA_RENDER_WORKERS` scenes at once in a process pool (default: half the CPU cores, at most 4). If the pool can't start, scenes render in-process instead.
- **Faster drawing:** full-screen cards skip drawing the map beneath them, the header and lower third are drawn once per shot, and the zoom crop uses sub-pixel boxes, which is also smoother.

Measured per 1080p frame on the development Mac:

| View | Before | After |
|---|---|---|
| Full-screen cards | ~22 ms | 4–6 ms |
| Map views | ~17 ms | 14–16 ms |

- **Joins and final encode:** fades are short pieces between neighbouring scenes, and the program is encoded in one pass. Programs of 10 minutes or more use the Mac hardware H.264 encoder when it's present. Set `WETHA_VIDEO_ENCODER` to `software` or `auto` to choose.
- **Incremental updates:** a scene re-renders only when its snapshot (narration, timing, parameters, source timestamps) changes. When an advisory updates, its scenes change and re-render, and the others are reused.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `WETHA_RENDER_WORKERS` | half the cores, at most 4 | Scenes rendered at once |
| `WETHA_VIDEO_ENCODER` | `software` for scenes; `auto` for finals of 10 minutes or more | `software` or `auto` (hardware when available) |
| `WETHA_LOUDNESS_TARGET` | `-16` | Integrated loudness target in LUFS for QC findings |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY` | unset | Turn on the stock video providers |
| `WETHA_SPEECH_CACHE` | `.local/speech-model` | Where the faster-whisper model is cached |

Database migration `007_production_jobs.sql` adds the `production_jobs` table and is applied automatically on startup. Existing data is untouched.

## Benchmarks

`scripts/benchmark-production.py 60 300 600 1800` runs the real pipeline from voiceover to finished video. It uses the training advisory and an alignment fixture, so it needs no network or speech model. For each length it records stage timings, total time, peak memory, and a second identical run to measure scene reuse. Results are written to `docs/benchmarks/production-latest.json`; see that file for the latest numbers on this machine.
