# Thirty-minute multi-story bulletin

Use the **Create Video** tab throughout. The target is a flowing report, with
roughly 4,350 supported words at 145 words per minute. Actual uploaded audio
determines final duration. Selecting 30 minutes never pads a short script.

1. Choose 6–8 substantive, related reports, set **30 minutes**, and build the
   flowing bulletin. Review the source times and material-shortfall notice.
2. Review and save the complete narration. Add supported reporting where the
   selected advisories do not provide enough material, then copy the script.
3. Record the narration externally and upload the complete recording. Confirm
   it matches this saved revision, then match the video length to the audio.
4. Click **Build mixed bulletin edit**. It drafts footage from the reviewed
   local library, retaining source graphs and explicitly selected maps. Review
   the scene summary and footage gaps before export.
5. Check coverage, render, and inspect the resulting video before accepting it.

Bulletin paragraphs are divided into visual beats of at most 18 words, retaining
the original claim, source and geographic scope. Plans support up to 1,500 scenes.
Maps, radar and satellite shots cannot exceed 10 seconds, including transition
handles. A short narration cannot be stretched into 30 minutes using long maps.

The mixed draft aims for about 40% footage (12 minutes in a 30-minute program),
with 2.5–5-second cuts (beats under 2.5 seconds keep their graphic), unused source ranges and at least two minutes between uses
of a recording. Existing manually selected assets are reserved; new suggestions
do not reuse their ranges. Unknown-location footage is excluded from named
regional reporting. Archival and illustrative footage remain contextual.

The draft is not a guarantee of visual quality: source graphs, observations and
relevant footage must actually exist. A long bulletin with no footage fails
export checks. Footage shortfalls require more independently filmed, licensed
material. NOAA observation times remain distinct from advisory times; source
geography alone is not observed weather. No paid generation, automatic YouTube
download or voice synthesis is used by this workflow.

## Externally refined script and spoken timing

After building a bulletin, use **Copy source pack** to copy the preserved original
reports, locations, source links and issue times. Paste your rewritten narration
into **Paste final script**, keeping each paragraph about one story. Click
**Match paragraphs to sources**, inspect the suggestions, choose each paragraph's
source, and save. Suggestions use word overlap, not semantic verification.
Rewritten claims require the existing quote-based editorial review before final
export. The original source pack remains available after edits.

Upload audio recorded from this saved revision. Click **Align scenes to spoken
words**, then **Apply spoken timing**. The free English speech model runs locally
on CPU and compares recognized word timestamps with the script. Audio never goes
to a transcription API. The first use downloads the model; later runs use its
local cache. Mismatched recordings and unreliable boundaries are rejected;
interpolated boundaries are flagged for listening review. The fallback under
**Estimated timing fallback** fits duration proportionally and does not locate
spoken words.

For a fresh development setup, install the optional local speech dependencies:

```sh
.venv/bin/python -m pip install -r backend/requirements-speech.txt
```

Build the mixed edit after applying timing. Recordings are spread across the
library, with no overlapping ranges and a two-minute reuse gap. **Footage to add**
lists missing footage by location and weather topic. Its search controls stay in
Create Video; review usage terms and location references before importing, then
rebuild the edit. Footage must exist in the reviewed library; this does not buy,
generate, or automatically download arbitrary YouTube videos.

## New footage acquisition

**Find & add new footage for this script** searches new free video candidates
using each story's location and weather topics. A mixed edit with footage gaps
starts this search automatically. The tool imports up to 12 new recordings per
batch, skips known duplicates, preserves licenses and credits, and limits total
downloads to 500 MiB per batch. Run another batch to explore remaining queries.

Live acquisition currently covers Wikimedia-hosted CC BY and public-domain
videos, including licensed YouTube-origin archive copies. Pexels and direct
YouTube links remain available through manual discovery; arbitrary YouTube
uploads do not become reusable because only a few seconds are used.

Search titles are candidates, not verified capture locations. Newly acquired
clips for named regions remain excluded from the regional edit until their
capture-region reference is reviewed in the same tab. Review, save that evidence,
then rebuild the mixed edit. The workflow does not promise a fixed number of
usable clips when search providers are unavailable or return unrelated results.

When Wikimedia is unavailable, all-source discovery also tries NASA/JSC real ISS
camera video. It excludes animation and interview titles and preserves the dated
archive description and NASA usage reference. These clips are orbital context;
they are not current weather layers, ground footage, or proof of local impacts.
Location review remains required before placing them in regional reporting.
