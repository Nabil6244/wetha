# Florida clips, statistics and maps

The finished 4-minute 44-second edit has 53 shots at 1920×1080 / 30 fps, synchronized narration and a local instrumental bed. Full video decode, frame-count and black-frame checks passed. No paid generation calls were made.

The combined edit interleaves the approved recorded forecast edition with short historical footage examples, rather than joining two complete videos end to end. Its forecast graphics retain the original immutable NWS/NHC sources, issue times and forecast valid times. Rendering does not refresh weather data.

The original 36-shot report contributes its 28 statistical and map treatments and eight illustrative coastal cuts. Four narrated archive sections add 12 short clips and four animated geographic context scenes. The new narration explicitly names the archived storms and dates, distinguishes images from measured rain/surge totals, and returns to the forecast story. Footage scenes show headlines and archive/illustrative context without source or creator text. Full creator credits appear on the final credit screen, with source URLs and reuse terms retained in the manifest. Final credits retain the DVIDS non-endorsement statement.

- Opening: recorded edition explained over dated Bradenton footage from Ian.
- After the surge forecast: Key West waves and Florida Keys aerial damage from Irma (2017), with no surge height inferred from imagery.
- After the rain forecast: rain, street water, damaged equipment and palms in Bradenton during Ian (2022).
- After the longer-range forecast: debris clearance after Ian, temporary roofs after Michael (2018), and relief supplies after Milton (2024).

The original report and footage preview remain available. The combined output is `.local/exports/florida-mixed-report/florida-clips-stats-maps-clean.mp4`, with a source/shot manifest, script, captions and decode/black-frame QA log in the same folder.

Reproduce with the existing reviewed local source files:

```sh
.venv/bin/python scripts/render-florida-mixed-report.py --archived-review
```

The renderer validates the approved base video checksum and footage bank checksums, reuses the approved graphic shots, generates additional narration with free macOS Samantha, and checks the complete 1080p/30 fps output before replacing the final file. Downloaded media and rendered outputs remain excluded from Git. Stock clips have unknown capture dates and remain illustrative. Historical scenes never serve as event evidence for the forecast storm.
