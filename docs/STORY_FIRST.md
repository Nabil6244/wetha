# Story-first script and storyboard

Choose an original scene plan in Video Production, then **Build story draft**.
The local drafter creates a separate immutable plan: it leads with a measured
pressure or wind change when available, establishes the source context, shows
reported geography, names source-listed warning coverage, quotes a short
forecast sentence when available, and closes with what to watch next.

Review the rewritten beats, then Suggest a 30-, 60- or 90-second edit, Apply,
Check, Save and Render. Original claim IDs, original claim wording, evidence
manifests and source URLs remain pinned to each derived beat. Changing the
original script invalidates its derived plans. A derived draft remains an
editorial preview and does not inherit approval of the original prose.

The renderer adds readable story captions and beat labels over real footage,
animated bars for source measurements, playback progress on graphic captions,
and source-position map reveals. Maps automatically frame supplied source
geometry when no explicit bounds exist. Intermediate animation frames are
presentation effects, not additional weather measurements. Context beats can
use varied rain, wind, sea and storm clips, with attribution and illustrative
or archival labels retained.

This is a deterministic first version. It does not generate new footage,
voices, forecast paths, new impacts or unsupported numerical claims. It uses
existing imported media, local Pillow animation and FFmpeg with no paid model
calls. Short rewritten scripts and limited footage can still produce similar
shots in longer templates. The warning beat summarizes the first source-listed
area; the original claim and source contain the full coverage. Forecast quotes
retain their issue-time context and must be reviewed before publication.

Validation: production build, 120 backend tests and 13 browser checks passed.
Straight-cut broadcasts now use direct scene concatenation. Output checks
validate video duration and frame count independently from audio, preventing
a long audio track from masking an early-ending picture. The corrected sample
contains 1,800 video frames across the full 60 seconds.

The corrected local 60-second sample is stored in
`.local/exports/story-first/story-first-60.mp4`, with captions, original claim
wording and source/license manifest alongside it.
