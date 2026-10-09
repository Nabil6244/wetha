# Phase 5 — Local video production

Phase 5 adds a working media-to-video workflow. Local voiceover generation is excluded by request. Videos use manual scene timing, with optional user-supplied narration audio.

## Workflow

1. Create a source-linked script in the newsroom. Resolve unsupported edits in Script Editor.
2. In Media Library, import still PNG/JPEG/WebP images, MP4/MOV/MKV/WebM footage, or WAV/MP3/M4A/FLAC/OGG narration. Each asset requires usage terms, creator attribution, provenance, and explicit rights confirmation. Files are copied into application storage. NOAA imagery can also be collected with the satellite observation button in Video Production.
3. Open Video Production. Select a script and prepare a scene plan, or select an existing Visual Director plan.
4. Set each scene's duration (1–120 seconds), optional footage trim point, and cut or fade-through-black transition. Preserve the source-linked scene order and narration. No footage is automatically looped.
5. Select imported narration if desired. Preview it, confirm it matches this script revision, and make the timeline agree with the measured audio duration within 0.2 seconds. The fit-timing control distributes measured duration proportionally; it does not align words automatically. Silent video is the default.
6. Save an immutable timeline, then render. Jobs run independently from the UI, one at a time, with a bounded queue, progress, cancellation, and retry.
7. Preview and download the validated MP4, SRT subtitles, and source/license manifest.

## Rendered media

Outputs are 1920×1080 at 30 fps, H.264/yuv420p with AAC stereo at 48 kHz. Imported narration is normalized toward −16 LUFS / −1.5 dB true peak. Silent outputs include an intentional silent audio track. Captions, source issue time, source status, and media-context labels are burned into every scene. Long paragraphs are paginated without replacing their narration.

With no imported visual, the renderer draws source cards, pinned comparison measurements, or pinned geographic geometry against the bundled Natural Earth country map. Rendered maps are static schematic longitude/latitude views whose extent includes the scene geometry. Forecast and reported data retain their plan metadata. Maps and measurements are not invented for unavailable sources.

Video Production can collect actual NOAA GOES-19 GeoColor observations and use them as regional context for scenes without imported media. Saving the timeline pins the latest 12 chronological images, source URLs, checksums, credits, reuse terms, observation times, and their offsets from the advisory issue time. This requires an NHC reported storm center within the editorial Gulf/Atlantic bounds. It does not assert pixel geolocation or event attribution. Each scene plays its chronological sequence once, at a presentation speed set by the scene duration; it is not real-time video. The complete NOAA source image, including its footer, remains visible beside captions. Independent observation and advisory timestamps remain visible. Timeline-owned image copies survive visual-cache pruning and are checksum-checked before rendering and retry. Radar playback and animated map camera controls remain in Visual Director; those layers still use source-card fallbacks in exports. Cross-dissolves, background music, automatic word alignment, GPU encoding, and hourly programs are not included in this implementation.

## Persistence and checks

Migration `006_production.sql` adds media, immutable timelines, and durable render records. Files live beneath `<backend data directory>/production/`. Media records retain SHA-256 checksums and FFprobe measurements. Duplicate bytes reuse the existing record; conflicting license/provenance metadata is rejected. Corrupted or missing originals can be repaired by importing the same file with the same rights record.

Each job snapshots its timeline and asset metadata. Scenes are cached with checksums. Retry reuses intact completed scenes and recreates incomplete or corrupted intermediates. Restart marks unfinished jobs failed. Source-status changes require a new render; superseded scripts cannot start or retry a render. Unsupported claims, removed source-context openings, and changed evidence checksums are rejected.

Validation probes output dimensions, codecs, frame rate and duration, then decodes every output frame and audio sample. A quality pass rejects extended almost-black output and flags extended silence in imported narration. Output exports are checksum-verified and support byte-range playback. Successful encoding does not grant editorial approval or broadcast admission. Every output is visibly a production preview, and all broadcast eligibility remains false pending Phase 6.

Imports are limited to 250 MiB each, visual dimensions to 8192 pixels, source clips to one hour, and timelines to ten minutes. Local file protocols are restricted for media decoding; command arguments never pass through a shell. FFmpeg/FFprobe must be installed on the machine and available on the backend PATH. No executable, stock footage, voice model or broadcast service is bundled.

## Validation

```sh
npm test
npm run build
npm run test:ui
.venv/bin/python scripts/validate-production.py
```

The production tests use synthetic PNG, video and audio fixtures in isolated databases. They cover rights/provenance requirements, malformed media, upload limits, duplicates and repair, stale revisions, unsupported claims, scene preservation, audio timing, real FFmpeg assembly, byte-range exports, corrupted output, persistence, cancellation, interrupted jobs and cache-based retry. The browser test covers library import, timeline edits, unsaved-change protection, render progress, preview/download, and responsive layout.

The standalone validation script renders explicitly synthetic 30-second and five-minute silent previews into `.local/phase5-validation/`, with subtitle, provenance/license manifest and validation sidecars. It uses a temporary database and does not seed the user's workspace. These are technical demonstrations with manual timing, not real weather coverage or a production news program.

To generate a five-minute silent report from the running desktop app and its collected NOAA observations:

```sh
.venv/bin/python scripts/render-report.py --url http://127.0.0.1:DESKTOP_PORT
```

Use the actual port shown by the desktop backend. This refreshes NHC evidence, selects a source-linked Gulf/Atlantic report, saves a satellite timeline, renders and validates it, and exports MP4/SRT/source manifest files into `.local/exports/`. It uses the collected NOAA frames; collect them in Video Production first. No paid model or media-generation service is called. The report is an editorial preview; independent satellite observation times and regional-context limits remain visible.

## Weather Brief presentation

Choose **Weather brief** in the Video Style control for full-frame NOAA image crops, a restrained camera push, brief headlines, large source-measured stats, two-point advisory comparisons, individual warning-area beats and forecast excerpts. Structured facts come from the pinned advisory; comparison data comes from the scene plan. Numbers remain fixed at reported values; animation reveals presentation elements. Comparison extents are labeled, and connectors are explicitly presentation guides. Source and independent observation times remain visible. The uncropped original images remain preserved in timeline storage and the source manifest. The SRT retains the complete source-linked script. This style requires satellite context and excludes imported scene visuals.

An optional original instrumental pulse is synthesized locally by FFmpeg, with no samples, model calls or voice. Its creator/provenance is recorded in the export manifest. Imported narration and the instrumental bed are separate alternatives in this implementation.

```sh
.venv/bin/python scripts/render-report.py --url http://127.0.0.1:DESKTOP_PORT --presentation cinematic --music
```
