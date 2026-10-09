# Phase 4 — geographic visual engine

The Visual Director replaces the Phase 4 placeholder with a MapLibre geographic preview, reported storm-center journey, advisory comparison graphics, official observation adapters and script-revision-bound scene plans. It remains a preview/directing workflow. Audio generation, FFmpeg rendering, ground footage and broadcasting belong to later phases.

## Geographic evidence

The locally served basemap contains 177 Natural Earth 1:110m country geometries. Its coordinates are copied unchanged from the official Natural Earth GitHub distribution; unrelated properties are omitted. Attribution, original and bundled SHA-256 checksums, source URL and public-domain licensing are recorded in `backend/app/data/provenance.json`. No paid tiles, external fonts or map account are required. This coarse global map is suitable for regional previews, not street-scale or evacuation-boundary decisions. MapLibre 6.13.0 is pinned; its worker is explicitly bundled for both Vite development and production. The visual module loads separately from the initial application bundle.

NHC points come from officially fetched advisory latitude/longitude and preserve advisory issue time, source URL, checksum, wind and pressure. Lines connect reported centers; camera interpolation and line segments are not observations of a continuous track. Dateline-crossing connectors are omitted rather than drawn incorrectly across the globe. Selecting an older advisory does not reveal later centers as evidence already known then. NWS areas use the selected advisory's original GeoJSON polygon only. Missing polygons, area names, invalid/unclosed coordinates, training data and unverified imports are not turned into invented map areas. Old alert polygons are not overlaid as if they were the selected current warning.

Camera controls support pan/zoom, rotation, tilt, regional reset and eased travel between reported centers. The Storm Journey and What Changed graphics preserve source times and units. Wind, pressure and position comparisons are based on actual extracted advisory values, not a future prediction. Magnitude bars are labeled explicitly; pressure bars do not imply an impact scale.

## Observation adapters and current access limits

GOES collection reads the official GOES-19 Gulf/Atlantic GeoColor 12-frame page. Image URLs must contain an actual dated filename from that page; `latest.jpg` and guessed observation times are rejected. Julian timestamps are checked, timezone-aware and preserved. Cached frames support scrubbing and looping, with restrained viewport motion. Images stay in their native NOAA projection in a separate viewport: they are **not** falsely draped over a Mercator map. GeoColor nighttime infrared enhancement is labeled and never described as rainfall intensity.

Radar collection uses NOAA nowCOAST time-enabled reflectivity WMS capabilities. Only explicit advertised times or an advertised minute interval are selected. GetMap requests use a known CONUS extent and EPSG:3857; the rendered raster is aligned to the corresponding geographic image quadrilateral. The source-provided color legend must be cached to display radar. Reflectivity is labeled in dBZ and is not rainfall accumulation. Rainfall accumulation products and forecast-vs-observation analysis are not implemented in this phase.

Forecast cones use the official regular NHC advisory's matching archived 5-day KMZ URL. The parser requires inline cone polygons and an issue timestamp within 30 minutes of that advisory. Linked KML is rejected, ZIP members are read without extraction, and archive size/count are bounded. Forecast geometry is labeled as a forecast, not an observation or an impact boundary. Unexpected/unmatched formats remain unavailable; no inferred cone is generated. This conservative KMZ adapter has synthetic format tests, but live NHC KMZ ingestion is unverified.

Current-instance checks found:

- Natural Earth geometry and the official GOES catalogue are accessible. The full captured GOES HTML fixture contains 12 real dated frame references and retains a source checksum.
- Initial requests to `cdn.star.nesdis.noaa.gov` and `nowcoast.noaa.gov` were denied by the cloud proxy. Both domains were added to the environment draft. Later runtime probes succeeded: 12 dated 1000×1000 GOES JPEGs, six dated 1200×720 radar PNGs and the official reflectivity legend were collected. Saving a draft alone does not establish access; these successes were verified separately.
- Actual nowCOAST GetMap requests revealed that the server rejects equivalent `+00:00` UTC offsets. Requests now serialize validated UTC times with `Z`; a regression assertion and live collection verify the correction.
- NHC GIS RSS and the tested archived KMZ return source-side HTTP 403. Allowing another domain does not fix that source response. Existing public advisory RSS collection remains available.

The UI shows missing frames, failed source collection and explicit scene fallback states. It never creates substitute observations. Model-free maps, advisory tracks, comparisons and plans work independently of imagery access. Synthetic 1x1 image transport fixtures are used only inside isolated tests and never added to the production database.

## Cache and provenance

Migration 005 adds `visual_assets`, `visual_sources` and `visual_plans`. Media bytes remain local in SQLite, with dated source URL, timestamp, MIME type, dimensions, metadata, retrieval time and SHA-256. Source catalogues/capabilities are cached with checksums. Asset reads and reuse check content integrity. Changed content at an existing dated URL is rejected; failures preserve previous evidence. Requests enforce official host/path allowlists, no redirects, normal TLS validation, an 8 MB body limit, a 25-second timeout and bounded transient retries. Manual overlapping collections share the same in-flight task; no background visual collection is enabled.

Retention evicts unpinned assets beyond 120 records or 256 MB. Assets referenced by saved scene plans are retained, so pinned media can exceed that cache budget; lifecycle/cleanup controls remain production-hardening work. Image signatures/dimensions are validated at collection, and browser decode errors remain visible. This is not a substitute for future full media quality validation.

## Scene direction

A plan pins script ID, immutable revision, narration checksum, claim IDs, evidence manifest and source status at creation. It contains source-linked scenes with estimated target duration, asset type, structured parameters, advisory timestamp, camera motion, cut/dissolve transition, fallback and null voiceover alignment. Edits to the script make its existing plan visibly superseded; current source labels and review validity are re-evaluated on reads. No plan is rendered or broadcast eligible.

Maps and reported-center scenes require geographic evidence. What Changed scenes use the linked source comparison. Satellite/radar scenes require cached observations within one hour of the script's issue time and current source evidence; otherwise they retain a source-card fallback. Satellite selection also requires an NHC center in a documented broad Gulf/Atlantic editorial region, which is a relevance filter, not pixel geolocation. Radar direction requires an official alert polygon. Scene imagery provides regional context and does not prove attribution to an individual event.

Scene CSV exports preserve narration, claims, data parameters, source references and timestamps, with spreadsheet formula escaping. Imports may change only supported camera movement and cut/dissolve transitions. Changing meteorological data, narration, units, timing or source attribution is rejected. An import creates a new plan and preserves its parent. Actual voiceover-derived timing and media rendering arrive in Phase 5.

## Validation

`npm test`, `npm run build`, and `WETHA_CHROMIUM=/usr/bin/chromium npm run test:ui` exercise the implementation. Browser tests enable Chromium's software WebGL renderer for this container; they do not disable the native Electron sandbox. The map test requires rendered country features, exercises camera controls, missing imagery/radar, training restrictions, scene direction/export, restart-style reload and narrow-screen layout. Production dependencies pass `npm audit --omit=dev` after upgrading to patched MapLibre.

88 backend tests and six real Chromium workflows passed; strict TypeScript/production build passed and the production dependency audit found zero vulnerabilities. The lazy MapLibre bundle triggers Vite’s size advisory.

Actual NWS/NHC refresh retained 699 advisories and two scripts. A production-served Chromium session rendered the real basemap and reported Isaias centers (22.8N/92.4W → 22.9N/91.9W), 65→70 mph and 994→988 mb comparisons. The old advisory and its scene plan correctly remained historical after a newer source update; no approval was invented. Production satellite playback decoded real dated frames and advanced through the 12-frame loop without browser alerts. Six real radar frames and their source legend were cached; production Chromium displayed the georeferenced radar loop, UTC frame labels and official dBZ legend without browser alerts. UTC request compatibility was verified against NOAA. Graceful restart preserved advisory data, scripts, the revision-bound plan and GOES cache.

Native Electron/Windows/macOS installers and continuous media production remain unvalidated milestones.
