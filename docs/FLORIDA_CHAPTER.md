# South Florida narrated chapter

The first regional chapter covers Isaias near South Florida on August 1–2, 2020. It is a historical documentary, not a current forecast. Its complete output appears at the top of Video Production after restarting the desktop app.

Run `.venv/bin/python scripts/render-florida-chapter.py` on macOS with FFmpeg/FFprobe installed. The script uses cached, checksum-pinned source files and the free installed Samantha voice through macOS `say`; no paid generation or TTS service is called. Each paragraph is synthesized separately and measured before assigning picture timing. The final movie is 1920×1080 at 30 fps with narration, a quiet locally generated music bed and separate sentence-level SRT captions. Sentence timing is approximate within each measured paragraph.

Outputs: `.local/exports/florida-chapter/south-florida-chapter.mp4`, `manifest.json`, `script.txt`, `captions.srt`, `narration.wav`, `contact.jpg` and `qc.log`. The manifest records exact footage trims, licenses, source URLs, checksums, station coordinates, measurement types and editorial limitations.

## Official data

- NWS Miami historical summary: https://www.weather.gov/mfl/Isaias2020
- Final NHC report, June 11, 2021: https://www.nhc.noaa.gov/data/tcr/AL092020_Isaias.pdf
- NHC public advisories 18, 20 and 22, from August 1–2, 2020.
- NHC geographic archive: https://www.nhc.noaa.gov/gis/forecast/archive/al092020_5day_018.zip
- Florida boundary: existing official Census 2024 state-outline catalogue.

Dania Pier's 50 kt gust converts to approximately 58 mph. Lake Worth's 36 kt sustained reading converts to 41 mph; Stuart Beach's 42 kt sustained reading converts to 48 mph. The readings have different averaging periods, heights and times. They are never described as successive storm-intensity changes. Coordinates and measurements come from NHC report table pages 26–27.

The NWS and NHC sources differ on the precise Dania gust time; it is omitted. NWS rainfall prose and the table header differ on the accumulation interval; those local totals are omitted. The rain graphic is explicitly the final NHC statewide summary of storm-total rainfall under three inches. It contains no inferred spatial rainfall field.

The warning and forecast geographic layers are the original advisory 18 product, issued August 1 at 15 UTC. Later warning decisions are stated separately on a dated timeline from NWS Miami. Animated map cameras and connectors are presentation, not intermediate observed positions. The wind/dry-air explanation is labeled a diagram with no modeled velocities.

## Footage

Pexels videos 15820691, 15999293, 9431769 and 33840195 have source descriptions identifying Miami Beach, Miami coastline or West Palm Beach. Their later publication dates are recorded separately from unknown capture dates. All are visibly labeled illustrative and never presented as an Isaias recording. Courtesy credits identify paashuu, Mikhail Nilov and Chris TheIsland. Pexels License: https://www.pexels.com/license/

No unrelated footage or unverified YouTube clips are included. Additional actual event footage can be added when its Florida location, event date and reuse permission are verified.

## Validation

The preparation stage validates official advisory identity/time, GIS issue time, exact station table excerpts, knot-to-mph conversions, source pins and distinct footage trims within source durations. The renderer checks every shot's frame count and the assembled picture duration/frame count. The final QC decodes the entire movie, checks for sustained black frames and measures audio loudness/true peak. Preview files are served only when their movie checksum matches the validated manifest.
