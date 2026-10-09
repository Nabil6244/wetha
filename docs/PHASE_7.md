# Cinematic visual engine and historical benchmark

This upgrade extends the existing Phase 5 production pipeline. The repository does not yet contain a completed OBS/Phase 6 broadcast subsystem. No collection, script editing, imported narration or media-library workflow was replaced.

## Why the earlier output looked like a presentation

`cinematic.frames()` cropped the same newest twelve GOES images behind every narration block. Forecast sentences remained large foreground text. `Production.pin_observations()` had checked an editorial Gulf/Atlantic region but had not constrained the observation dates to the selected advisory. Regional context did not establish a storm attribution.

Legacy regional satellite previews now require observations within one hour of the advisory. Their independent timestamp/no-event-attribution labels remain. New broadcast scenes require a common event ID in their source contract; incompatible event years, historical/current status, projections, chronology, forecast times and missing source layers fail validation. Live NHC parsing also checks storm-ID year against issue year. This does not prove that an unregistered native image depicts a reported storm position.

## Implemented

- `backend/app/broadcast.py`: typed `SceneDirection`, `Camera`, `VisualSource`; deterministic easing and framing; native-image camera drift/zoom; geographic map targeting; Web Mercator cartography/raster registration; bounded genuine GIF sequences; original timestamp and legend insets; measured-endpoint weather graphics; official point/alert/cone geometry drawing when its metadata is present.
- Local semantic director in saved visual plans. It chooses source geography or sourced comparisons instead of displaying narration paragraphs. Forecast text remains in the script/SRT. Unsupported observation/cone/footage selections require an explicit fallback.
- New **Broadcast** video style in the existing revision-bound production queue. It preserves narration timing, source evidence and cache/retry/QC/export behavior. Fade selections become 0.3-second dissolves with overlap handles, preserving total duration. Cut selections remain cuts.
- `GET /api/visuals/scene-schema` exposes the versioned scene contract. Scene direction is visible in Visual Director.
- Cached map bases, raw RGB streaming rather than thousands of cached PNGs, immutable benchmark source checksums, scene-level incremental benchmark renders and existing production retry caches. Scene encoding defaults to software for predictable quality; `WETHA_VIDEO_ENCODER=auto` probes real VideoToolbox encoding and falls back to libx264.
- Templates for wind, pressure, supplied measured rainfall, supplied temperature, supplied category and supplied warning comparisons. Current adapters populate wind/pressure; missing measurements are never invented. Bars reveal two fixed source values; they do not animate fictitious intermediate meteorological readings.
- Historical benchmark preview/download and source manifest in **Video Production** whenever the locally rendered artifact exists.

## Reproduce the actual benchmark

From the repository root, with the installed virtual environment and FFmpeg:

```sh
.venv/bin/python scripts/render-benchmark.py
```

First run obtains fixed NOAA/NWS and NHC archive URLs. Later runs reuse checksum-pinned bytes. Changing the scene contract or renderer invalidates affected scene caches. No paid AI, TTS, generated storm footage or optical-flow weather interpolation is used. Music is an original locally synthesized instrumental.

Output: `.local/exports/phase7/phase7-isaias-30s.mp4`, `manifest.json`, `scene-schema.json`, scene clips and decode/QC log.

| Nominal time | Actual visual |
| --- | --- |
| 0–5s | Real GOES-16 enhanced infrared image; presentation zoom |
| 5–10s | 136 timestamp-validated original NWS frames; native UTC stamp/legend retained |
| 10–15s | Accurate Web Mercator map and NHC reported centers, advisories 26–28 |
| 15–20s | Wind 70 → 85 mph; pressure 998 → 988 mb, 03 Aug 15 UTC → 04 Aug 03 UTC |
| 20–25s | Explicit ground-footage-unavailable map fallback |
| 25–30s | Original KLTX radar reflectivity loop with its UTC timestamps and dBZ legend |

All 136 satellite and 136 radar frame timestamps were extracted locally from the original embedded labels and checked in order, with no reversals. `backend/app/data/isaias2020-frame-times.json` pins those records to each original GIF checksum; the renderer checks timestamp count and window against decoded frames. No observation times were inferred from playback speed.

All sources refer to **AL092020**, Isaias's August 2020 Carolina approach/landfall. NWS identifies the satellite/radar loops on its historical event page: https://www.weather.gov/ilm/HurricaneIsaias2020. NHC source URLs and preserved advisory text/checksums are in the manifest. Reported-center connectors are presentation guides, not a continuously observed path or forecast track. Historical warnings are not presented as active warnings.

## Limits and next engineering work

The source satellite GIF is 600×544 and the radar GIF is 794×446; 1080p export does not create additional source detail. Source-native infrared colors are enhancement, not a natural-color photograph or rainfall amount. The native viewports are not registered geographically against the separately rendered map. Camera drift is presentation framing; geographic storm-following on these native pixels is deliberately rejected.

No reusable authentic ground footage was verified, and no forecast cone was fetched for this benchmark. Those are declared fallbacks/omissions. General historical-event catalogue ingestion, verified event/date/location matching for imported media, additional measured rainfall/temperature adapters, registered satellite reprojection, automatic deadline scheduling and hour-long throughput qualification remain future work. Existing current radar and official cone ingestion/browser views are preserved. Ordinary new Broadcast timelines use safe source maps/statistics or imported footage explicitly labeled illustrative/archival; the benchmark CLI exercises verified historical satellite/radar asset directions explicitly.

Software rendering and full decode succeeded for the 30-second artifact. This is not evidence that a 60-minute program can be produced each hour. Production retains its ten-minute preview limit. Imported narration remains supported; local voiceover and OBS broadcasting remain outside this milestone.

## YouTube and stock media imports

Media Library now records `source_provider` (`local`, `stock`, `youtube`). YouTube imports require a local video file, a canonical original YouTube video URL, creator attribution, reuse basis (`permission`, `cc_by`, `creator_owned`) and a permission/license/ownership reference. The app records the operator’s declaration; it does not independently establish the rights, download from YouTube or treat short duration as permission. Source records remain immutable and checksum-deduplicated.

The preferred YouTube cut duration is configurable from 3 to 4 seconds (default 3.5). Selecting that asset in a scene applies this duration; Clip Start selects the source time. Broadcast footage gets a restrained illustrative/archival credit, and original clip audio is excluded in favor of the timeline’s chosen narration/music/silence. The complete reuse record is preserved in the output manifest. Imported footage is not automatically attributed to the named storm. Dissolve handles are checked against the source duration.
