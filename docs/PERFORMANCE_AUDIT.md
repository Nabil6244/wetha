# Local performance and reliability audit — 15 October 2026

Reviewed the React workspace and draft persistence, SQLite access, production job lifecycle, observation collection, FFmpeg encoding, render workers, and disk retention. Changes run locally without paid generation requests.

## Findings and fixes

| Finding | Change |
| --- | --- |
| Dashboard refreshed about 30 MB of alert polygons, text and repeated changes | Compact list responses; selected source packages load in full on demand |
| Each progress poll decoded every render snapshot | SQLite projects only status/progress fields |
| Geography rebuilt the whole weather archive for each bulletin story | One request-scoped intelligence snapshot is shared |
| Render validation, checksums and scene-cache reuse blocked the event loop | Async render startup runs these operations in a worker thread |
| Duplicate production submissions could compete for speech alignment | Active identical requests reuse their existing job; the UI prevents repeat submission |
| Estimated timing could trigger speech alignment again after collection | A confirmed fallback persists through replanning |
| Polls overlapped or discarded tracking after a temporary network failure | Serialized polls, resumable tracking, reconnect/retry controls and friendly field/network errors |
| A rendering exception could leave a blank workspace | Workspace error boundary offers reload without clearing stored drafts |
| Cached desktop HTML could load an older interface after a rebuild | Entry-point no-store header plus build-specific desktop URL |
| Four concurrent scene workers competed with the desktop for RAM/CPU | Default two workers; explicit override bounded to four |
| Short exports and footage still used software encoding | Actual encoder probe selects VideoToolbox, NVENC, QSV or Windows AMF where available; CPU fallback when probing fails |
| No storage cleanup controls; production folder about 16 GiB | Settings → Storage & performance lists usage, scene/temp/source-response cleanup, database compaction, free disk and encoder |
| Render caches grew indefinitely | Thirty-day terminal scene-cache retention on startup; manual clearing while idle; early disk-space estimate before rendering |
| Fast export omitted observation collection; satellite collection only covered Gulf/Atlantic latest images | Dated CONUS/Gulf GeoColor collection, story time/coverage checks, radar archive selection and graph overlays over matching satellite imagery |
| Optional sources could hold production indefinitely | Bounded observation requests and overall radar/satellite budget; provider failures become visible availability notes |

## Measurements on the existing workspace

4992 advisory records, 18 scripts, 173 media records and 22 completed videos.

| Request | Before | After |
| --- | ---: | ---: |
| Dashboard response | 29,822,688 bytes / 3.264 seconds | 10,238,352 bytes / 1.668 seconds |
| Render progress | 1.079 seconds | 0.191 seconds |

These are individual local measurements, not a controlled long-program benchmark. Source contents, disk pressure and simultaneous workloads affect results.

Safe scene-cache cleanup removed 7711 regenerable files, reclaiming 7,332,842,060 bytes. Scripts, source records, uploaded media, final videos and reports are excluded. Future retries may re-render cleared scenes. No project-history or credential deletion control was added.

## Validation

- Full backend suite: 365 passed before final small error/retention refinements; 20 focused performance/production/orchestration tests passed after the final changes; 14 storage/satellite/alignment/performance regressions also passed.
- Six browser regressions passed: storage controls, reconnect recovery, source detail loading, narration saving and narrow-screen settings.
- Strict TypeScript/Vite production build passed.
- Standalone runtime configuration test passed.
- Live NOAA test: six dated CONUS GeoColor frames around the Pecos County advisory; a 3-second 1080p H.264 graph/satellite clip encoded with Apple VideoToolbox in about 6 seconds. Proof: `.local/audit-proof/satellite-graph-proof.mp4`.
- Live archived-radar request timed out in its 30-second test budget. Source failures remain explicit; the app does not fabricate a radar layer.
- All 22 completed MP4 files are verified against pre-cleanup SHA-256 checksums; script revision/media IDs and source counts are compared before/after cleanup.

NOAA product/catalogue references: [CONUS GeoColor](https://www.star.nesdis.noaa.gov/GOES/conus_band.php?band=GEOCOLOR&length=12&sat=G19), [dated image catalogue](https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/GEOCOLOR/). Satellite pixels are native regional context with independent observation timestamps; they are not rainfall measurements or proof of a particular storm's identity.

## Practical limits

Map/chart drawing and local speech alignment remain on CPU. Hardware encoding is verified on this Apple Silicon Mac; Windows/NVIDIA/Intel/AMD selections need native-machine validation. A complete new 10/30/60-minute export has not been benchmarked during this audit. Existing MP4s keep their original edit; the restored observation selection applies to newly prepared productions. The previously built distribution DMG has not been repackaged with this source update.
