# Complete historical episode

The 60-second Isaias case study combines an original hook and payoff with fifteen shots, four licensed three-second footage cuts, measured statistics and official weather layers. This is a historical August 2020 report, not a current warning.

Run `.venv/bin/python scripts/render-complete-episode.py` from the project root. It reuses local source bytes, validates pinned checksums, caches scene renders and exports `.local/exports/complete-episode/episode-60.mp4`, `manifest.json`, `script.txt` and `contact.jpg`. The completed episode appears at the top of Video Production after restarting the desktop app. No paid generation or local voiceover is used.

Official layers:

- Reported centers and 70→85 mph / 998→988 mb comparisons: [NHC advisories 26–28](https://www.nhc.noaa.gov/archive/2020/ISAIAS.shtml). Map connectors are presentation guides.
- Actual forecast cone, five future center points and 21 coastal warning lines: [NHC advisory 28 geographic archive](https://www.nhc.noaa.gov/gis/forecast/archive/al092020_5day_028.zip). Issued 04 August 2020 at 03 UTC; forecast points extend through 06 August at 12 UTC. Original GCS_Sphere geographic coordinates are projected for display. Forecast points are distinct from observed positions.
- Real satellite and KLTX radar loops: [NWS Wilmington event analysis](https://www.weather.gov/ilm/HurricaneIsaias2020). Radar plays its first 68 frames, then its final 68 frames, in chronological order. Original UTC strips and reflectivity legends remain visible.
- [NWS post-event rainfall map](https://www.weather.gov/images/ilm/climate/events/HurricaneIsaiasRainfallTotals.png): complete native image and inches legend. The accumulation interval is not printed. The separate 6.80-inch gauge observation comes from station SC-GT-42, 2.4 miles northwest of Pawley’s Island, in the NWS event analysis; it is not read from radar pixels.

Footage provenance is in [MEDIA_POOL.json](MEDIA_POOL.json) and the output manifest. Pexels footage is illustrative. The YouTube-origin clip comes from its license-reviewed Wikimedia copy and shows Irma in St. Lucia in 2017, clearly labeled on screen. Its CC BY 3.0 attribution and modifications are retained.

Validation checks the video stream independently: 1920×1080, 30 fps, 1800 frames and 60 seconds. A full decode and black-interval scan must pass before the manifest is written. Straight cuts use the concat demuxer to preserve all frames across differing source color metadata. Music is synthesized locally; original footage audio is removed.

This completes one source-rich episode. General automated acquisition of these archive layers for other storms and a larger reusable footage library remain separate work.
