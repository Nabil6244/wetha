# One storm, one hour

The first long program is a historical Isaias deep dive. It needs a new hour-long editorial script and independent chapter material; the 60-second episode is the visual reference, not an hour's worth of content.

The desktop's Video Production page now shows the twelve-chapter blueprint, chapter content assignments and a content/repetition audit. Download the blueprint there. Six new motion graphic treatments are selectable per source-linked scene, under **MOTION GRAPHIC**, in Broadcast style. These choices persist in saved timelines and source manifests.

| Time | Chapter | Main question |
|---|---|---|
| 00:00–02:00 | Opening and roadmap | What changed before landfall? |
| 02:00–06:00 | Origins | How did the storm reach this point? |
| 06:00–12:00 | Final twelve hours | Which measurements changed? |
| 12:00–17:00 | Coastal warnings | Who was warned, and when? |
| 17:00–23:00 | Landfall | What do the actual observations show? |
| 23:00–30:00 | Rainfall | Where did totals and impacts differ? |
| 30:00–35:00 | Wind and coastal water | How did conditions vary by place? |
| 35:00–41:00 | Inland evolution | What happened as the storm moved north? |
| 41:00–46:00 | Forecast versus observation | What was known then, and learned later? |
| 46:00–52:00 | Reconstructing the record | Which facts can sources establish? |
| 52:00–57:00 | Reading weather graphics | What does each product actually mean? |
| 57:00–60:00 | Answers and conclusion | What did the whole record show? |

These are editorial allocations, not approved chapter scripts. A chapter's questions and source needs appear in the app. Avoid an identical question/answer rhythm in every chapter: interleave chronology, a geographic reveal, a comparison, a source explanation and a verified regional account. Answers must arrive before a new question replaces them. Suspense comes from the actual chronology and uncertainty; do not invent danger, urgency, impacts or measurements.

Pacing targets:

- Approximately 600 distinct visual beats across the hour, rather than one-minute loops.
- Footage cuts at 3–4 seconds; graphics usually 4–9 seconds, with enough time to read the displayed data.
- At least four visual families per chapter. No more than two consecutive shots from one family.
- A fresh question, reveal or meaningful change in viewpoint about every 45–90 seconds. Chapter transitions should introduce a new subject, not restart the same montage.
- No reused footage ranges. At least two minutes before the same recording returns; no more than three uses of one recording within a chapter. Matching topic tags alone do not verify storm attribution.
- Around 7,000–8,500 original sourced words is an editorial target. The audit requires at least 5,400 distinct edited words; this threshold cannot prove script quality or retention.
- Around fifteen minutes of independently varied footage would require 225–300 short cuts. This is an acquisition target, not permission to reuse a handful of sources repeatedly.

Graphics now available: reported track, warning geometry, observed radar, forecast cone, change dial, before/after split, advisory timeline, forecast time ladder, question/answer reveal and source spotlight. The existing historical episode additionally has the native post-event rainfall map. Each template displays only supplied source values. Animated shapes reveal fixed measurements; they do not create intermediate observations.

Change dials, split comparisons and question reveals require two source-reported measurements. Timelines require at least two reported center positions. The forecast ladder requires explicit source issue and valid times; missing layers block that choice. Forecast points never become observed positions. Source timestamps, attribution and context labels remain in the render.

The content audit flags missing chapter duration, recycled timelines, repeated passages outside the closing recap, excessive holds, insufficient visual diversity, overlapping clips, recording overuse and closely spaced returns. Chapter assignments must refer to source-linked saved timelines. It checks their evidence and imported file integrity. It is a planning check, not broadcast approval or final output validation. Unknown chapter IDs and duplicate chapter assignments are rejected.

Sources for the expansion include the [NHC Isaias post-event report](https://www.nhc.noaa.gov/data/tcr/AL092020_Isaias.pdf), [issued advisory archive](https://www.nhc.noaa.gov/archive/2020/ISAIAS.shtml), [NWS Wilmington event analysis](https://www.weather.gov/ilm/HurricaneIsaias2020), and [NHC explanation of its forecast cone](https://www.nhc.noaa.gov/aboutcone.shtml). Retrospective best-track estimates must be labeled separately from values available in issued advisories. Regional impacts require their own support. Educational diagrams must be labeled as explanations, not measured storm geometry.

Run `.venv/bin/python scripts/render-graphic-pack.py` to render the local sixty-second proof of ten treatments. Outputs are in `.local/exports/hour-graphics/`: video, source manifest, QC log and one-hour blueprint. This proof is not the full-hour video. All rendering is local, with zero paid generation and no local voiceover.

The full hour remains dependent on expanded chapter scripts, more independently filmed footage, regional evidence and completed chapter renders. The reviewed sample pool has four recordings; the app reports the actual imported library size. The general timeline renderer limits each chapter timeline to ten minutes. Audience retention ultimately needs editorial review and viewer testing; pacing rules alone cannot guarantee it.

Once chapters are completed, create a JSON file with `chapters` entries containing `chapter_id` and `render_ids`. Each ID must identify a successful local render. Run `.venv/bin/python scripts/assemble-hour.py --chapters /absolute/path/chapter-renders.json --check-only` first, then the same command without `--check-only` to assemble. The tool rechecks source evidence, media integrity, output checksums and the hour content audit. It rejects replayed renders and incomplete chapters. It preserves chapter audio, shifts all subtitles, embeds twelve chapter markers and validates 108,000 video frames plus a full decode and black-interval scan before writing the final manifest. It makes no paid generation calls. No full-hour export has been produced or validated yet; the real input set does not contain a complete hour of chapter content.
