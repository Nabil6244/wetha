# Mixed-footage sample

The first mixed-footage edit is `.local/exports/mixed-sample/weather-mixed-30s.mp4`.
It is a historical Isaias AL092020 visual report, with clearly labeled contextual
footage. It does not depict a current warning. No local voiceover or paid media
generation is used.

## Edit

| Seconds | Visual |
|---|---|
| 0–4 | Illustrative rain and wind, Startup MrParag / Pexels |
| 4–8 | Official Isaias satellite loop |
| 8–12 | NHC reported storm positions |
| 12–16 | Reported wind 70 → 85 mph and pressure 998 → 988 mb |
| 16–20 | Archival Irma waves, St. Lucia, 5 September 2017 |
| 20–24 | Illustrative rough sea, Peggy Johnson Philip Waikoloa / Pexels |
| 24–28 | Official Isaias radar loop |
| 28–30 | Historical 85 mph takeaway, advisory 28 |

Cuts are four seconds for the ground clips. The original local instrumental is
retained; source footage audio is removed. The output is H.264/AAC, 1920×1080,
30 fps, exactly 30 seconds, with full FFmpeg decode and black-frame checks.

## Sources and reuse

The durable source catalogue is [MEDIA_POOL.json](MEDIA_POOL.json). Each record
includes SHA256, provider, source URL, credit, license and reuse evidence.

- [Rain and wind](https://www.pexels.com/video/strong-rain-and-wind-4436187/),
  Startup MrParag, [Pexels License](https://www.pexels.com/license/).
- [Storm at sea](https://www.pexels.com/video/storm-at-sea-1879456/),
  Peggy Johnson Philip Waikoloa, Pexels License.
- [St. Lucia Irma Waves](https://www.youtube.com/watch?v=f5mtyHSyUp8), Bruce and
  Tammy Swart, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
  Retrieved from the [license-reviewed Wikimedia archive](https://commons.wikimedia.org/wiki/File:St._Lucia_Irma_Waves.webm),
  with the published SHA1 checked. Changes: trimmed, resized, labeled, audio removed.
  Attribution, original URL, license URL and changes are also displayed on screen.
- Isaias satellite, radar and NHC records: see [PHASE_7.md](PHASE_7.md).

The stock clips have no verified capture location/date for matching to Isaias.
The Irma clip belongs to a different storm. All three receive illustrative or
archival labels; none is used as evidence of Isaias conditions.

The clips were also imported into the running desktop app's Media Library using
the existing media import endpoint. YouTube downloading was not added: the
YouTube-origin media came from its licensed archive.

## Reproduce locally

With the benchmark and reviewed clips already downloaded:

```sh
.venv/bin/python scripts/render-mixed-sample.py
```

The script reads `.local/media-pool/catalog.json`, checks asset checksums and the
validated benchmark checksum, then reuses cached cuts when inputs are unchanged.
The output folder includes the final video, manifest, source credits, QC log and
contact sheet. The original benchmark is preserved.

## Remaining work

This completes the first manually selected mixed-footage sample. Automatic media
search, ranked story matching, reusable templates, missing-asset UI checks and
longer-report qualification remain separate implementation steps. OBS and
scheduling are not implemented by this change.
