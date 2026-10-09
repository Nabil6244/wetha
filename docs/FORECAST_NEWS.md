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

The movie uses 48 short shots at 1080p/30 fps. Graphic movement reveals supplied source values and changes the camera; it is not simulated radar or a synthetic weather field. Six location-reviewed Florida recordings provide distinct illustrative trims. New Northwest Florida sources are Pexels 31040646 (Jabriel, Panama City Beach, source description) and 2425846 (Ruvim M, Panama City Beach, source location tag and matching visible beachfront). Existing Miami and West Palm footage appears as regional illustration. All footage is labeled illustrative, with unknown capture date, rather than current conditions.

The renderer verifies source checksums, source hours and units, footage ranges, per-shot and total frame counts, final picture duration, full decoding and sustained black frames. Captions use approximate sentence timing within measured narration paragraphs.
