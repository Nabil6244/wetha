# Automatic short edit

Video Production now offers **Suggest 30-second edit**, **Apply 30-second draft**
and **Check visuals & timing**. The draft uses the local media library, without
network searches, downloads, AI generation or voiceover. It preserves every
source-linked script scene once and in order. It does not create a universal
eight-shot storyboard by discarding or duplicating script claims.

## Footage catalogue

In Media Library, expand **Tag footage for automatic suggestions**. Add weather
tags, optional event ID, capture location/date, the source documenting those
details, and a preferred video trim point. Unknown details can remain blank.
The three reviewed sample clips have been tagged in the running app.

Catalogue edits do not alter original license/provenance records or media
checksums. The catalogue used when saving a timeline is retained with each
selected scene. A matching declaration does not establish event attribution;
the existing illustrative/archival labels remain on footage and in manifests.

## Selection and timing

The selector normalizes weather vocabulary such as rainfall/rain, gusts/wind
and surf/waves, then ranks matching clips and images. Declared matching event,
capture date and location improve ranking; different events are identified in
the reasons. Each scene shows up to five candidates and their reasons.

The short template preserves map, statistics, satellite and radar scenes, plus
the closing scene. It automatically uses an unused matching clip for other
scenes, with the preferred trim and a 3–4 second duration. Unavailable or corrupt
files, audio, insufficiently long clips and unrelated weather topics are
excluded. Source graphics fill missing footage slots, with explicit notices.

Graphic time is allocated in whole 30-fps frames according to script length,
with a normal six-second cap so a long quotation cannot dominate the edit.
Sparse plans that require longer holds are flagged.
The saved timeline is exactly 900 frames / 30 seconds. All scenes remain
present. Plans over 30 scenes require manual timing. For dense plans, footage
slots revert to graphics rather than forcing clips below three seconds.

The draft uses Broadcast style, cuts, and the existing original local music.
It clears imported narration. Applying individual candidates or changing scene
timing switches the timeline to manual editing. Saving retains the short template
identifier when the exact 30-second draft is used.

## Before rendering

The check uses the same validation as saving: revision and claim integrity,
selected file checksum, trim length and dissolve handles, audio timing and
template duration. It also identifies source graphic and missing-observation
fallbacks. Checks do not save a timeline. Editing invalidates displayed check
results. Saving automatically checks again; rendering rechecks revision and media.

## Validation

- 110 backend tests passed, including ranking, dense-plan fallback, non-repeating
  choices, metadata preservation, corrupt media and non-mutating checks.
- 10 browser workflows passed, including catalogue editing, suggestions,
  applying the short template, checking and saving, and stale-check removal.
- TypeScript and production build passed.

Automatic external asset discovery, permission acquisition, content-aware trim
analysis, source-geographic observation registration, longer-report qualification,
scheduling and OBS remain outside this phase. Suggestions operate on imported
local media; a preferred start is used rather than analyzing footage for its
most dramatic moment.
