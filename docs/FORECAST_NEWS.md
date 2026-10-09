# Florida forecast news

This first edition is a recorded, source-linked bulletin collected October 9, 2026 at 07:13 UTC. It covers the current NHC Isaias event **AL092026**, separately from the previous **AL092020** historical chapter. It is an editorial preview; it does not publish or broadcast automatically.

## Sources and scope

The collection script resolves eight Florida city coordinates through the official NWS points endpoint, then follows each returned hourly forecast URL. It preserves wind ranges, Fahrenheit temperatures, nullable precipitation probabilities, source issue times and hourly valid periods. Shared checkpoints are the next full UTC hour and +6, +12, +24, +48 and +72 hours. These are individual forecast grid points, not complete city or county weather fields. UTC makes the comparisons consistent across Florida's Eastern and Central time zones.

Current Florida alerts come from the official state-filtered NWS alert feed. Expired, future-effective, canceled, non-Actual and non-Florida records are excluded. Only polygons supplied by the source appear on the map. Alerts with zone-only coverage remain in the manifest; their geometry is not invented.

The NHC Atlantic RSS feed supplies the latest public bulletin. Its matching full advisory and official geographic archive are fetched separately. The current edition uses the 06 UTC intermediate public bulletin and the 03 UTC full-advisory forecast/warning map. Their issue times are shown separately. NHC printed time zones are honored, including CDT, rather than treating every product as Eastern time.

The narration separates reported storm-center wind, forecast city wind, precipitation probability, regional rainfall amount, conditional storm-surge range and active warning information. It does not make forecast-change claims because no comparable previous forecast edition was collected.

## Reproduce and refresh

1. `.venv/bin/python scripts/collect-forecast-news.py`
2. `.venv/bin/python scripts/render-forecast-news.py`
3. Restart the desktop app and open Video Production.

Collection requires network access. Rendering uses cached official data, local FFmpeg, licensed Pexels footage and the installed macOS Samantha voice. No paid generation, TTS or image service is called.

Each collection also archives its exact source bytes under `.local/forecast-news/sources/snapshots/`, with URL, retrieval timestamp and SHA-256 checksum. Later collection does not overwrite that edition's archived evidence.

The script is deliberately specific to this sourced first story. A changed event, issue date or unsupported hazard wording stops rendering and requires a new editorial script. The underlying hourly collection, horizon extraction, forecast maps, timestamp validation and snapshot status can be reused for subsequent stories. Do not relabel the existing recording as a new forecast.

The app marks a recording as needing refresh 30 minutes after collection. This status does not modify the movie, which always retains its original dates. Recollect and review sources before publication. Render preparation rejects an old snapshot; archived editions remain viewable for review.

## Output

`.local/exports/forecast-news/florida-forecast-bulletin.mp4`, `manifest.json`, `script.txt`, `captions.srt`, `narration.wav`, `contact.jpg` and `qc.log`.

The revised movie uses 36 shots at 1080p/30 fps, lasting about 3 minutes 8 seconds. Each of the 28 graphic treatments appears once; eight distinct 3.5-second footage trims are disjoint. Twenty-one statistical and explanatory designs replace the repeated city-list maps: rain ranking and contrast, a 48-cell forecast-hour heatmap, wind ranges and rankings, compass directions, thermal dials, regional rainfall and conditional surge scales, alert-record counts and source clocks. Graphic movement reveals supplied source values and changes the camera; it is not simulated radar or a synthetic weather field. Six location-reviewed Florida recordings provide distinct illustrative trims. New Northwest Florida sources are Pexels 31040646 (Jabriel, Panama City Beach, source description) and 2425846 (Ruvim M, Panama City Beach, source location tag and matching visible beachfront). Existing Miami and West Palm footage appears as regional illustration. All footage is labeled illustrative, with unknown capture date, rather than current conditions.

The renderer verifies source checksums, source hours and units, footage ranges, per-shot and total frame counts, final picture duration, full decoding and sustained black frames. Captions use approximate sentence timing within measured narration paragraphs.

## Visual revision and archived review

Revision 2 adds the storm's sourced pressure and forward speed, an explicitly derived
percentage-point rain-chance comparison, all eight local point forecasts at six
valid-hour checkpoints, and active alert-record counts. Record counts may overlap
and are never presented as counts of people, cities or unique covered areas.
Graphical reveals happen once per shot; the plan rejects repeated graphic kinds.
Forecast matrices contain discrete supplied values, rather than interpolated fields
or comparisons with a newer edition. Every shot retains source times and units.

To revise this **recorded edition** without relabeling it as current, use
`.venv/bin/python scripts/render-forecast-news.py --archived-review`. This explicit
review mode preserves the old collection date and marks the export as archived
review. The normal command still rejects an expired snapshot. This exception is
for editing the recording, not publishing it as a new weather update.

The manifest includes `visual_audit` and `statistical_summary`. Shot cache keys
include source values and the statistical renderer, preventing old charts from
surviving a data or design change. A revised movie is validated before replacing
the prior dashboard export.
