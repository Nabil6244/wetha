# Automatic local video preparation

In Create Video, paste the final narration and select **Save script & prepare automatically**. This maps chapters to the preserved reports without requiring a source dropdown for each paragraph. An optional editor name records authorship, not source approval.

Upload the matching voiceover, then select **Make final video**. The app:

1. Audits the preserved source package, numerical values, ranges and units. Unsupported values identify the paragraph needing correction.
2. Reuses completed speech alignment tied to this exact script, plan and audio checksum. Otherwise it starts local alignment and continues preparation automatically when it completes. Matches below 95% require confirmation.
3. Subdivides aligned narration into visual shots of 2.5–4 seconds (sections under five seconds stay whole), keeping the original audio frames and source claim IDs. Cuts move up to half a second to land on a recognized word start, each shot's caption holds the words spoken during it, and shots from one section continue a single camera move and chart reveal instead of restarting it.
4. Repairs chapter geography from the source mapping, adds source-derived rainfall/surge/wind range charts, and mixes available licensed footage. It preserves manually selected footage. Repeated charts for the same claim are suppressed.
5. Checks map holds, media rights/ranges, narration duration and evidence checksums, then queues the local 1080p MP4 render.

## Visual variety

With automatic graphs on, every automatic map shot is given one visual state:

- **Map moves:** regional overview, pan, closer look (push in), wider view (pull out), and following the storm track.
- **Place callout:** a named place zoomed and ringed.
- **Source facts:** a facts panel beside the map.
- **Key numbers:** a card with the source values.
- **Original wording:** a card quoting the source.
- **Motion graphics:** the change dial, before/after split, question reveal, advisory timeline and source card.

A state is offered only when its data is pinned to the scene: reported positions, catalogued places, source facts, two measured values, or source wording. A state never returns within four shots. Two cards never play back to back, and a card never follows a chart. The same card for the same story waits at least twelve shots. Footage, charts, observations and anything you chose by hand are kept as set, but they count toward the rhythm.

Footage runs up to two beats in a row before a graphic. Still images get a slow push, pull or drift instead of holding static.

## Transitions, sound and finish

- **Transitions:** graphic shots enter with a third-of-a-second transition drawn inside the shot, so each scene keeps its exact length.
  - A change of story gets a branded push.
  - A map going into a card gets a push.
  - A card or chart going back to a map gets a soft wipe.
  - Map-to-map changes alternate between dissolves and hard cuts.
  - Footage always cuts, and a continuous camera hold is never interrupted.
- **Sound:** with a voiceover in Broadcast style, an original instrumental bed plays underneath. It ducks whenever the voice speaks and fades in and out. Each transition gets a soft, locally synthesized whoosh. Turn this off with **Quiet music bed under the voiceover**.
- **Look:** all footage and stills get one mild, cool grade so different sources sit together.
- **Captions:** each caption page is at most two lines of 42 characters, and holds the screen in proportion to its words.

## Long programs

- **Parallel scenes:** several scenes render at once, up to four by default and about half the CPU cores. Set `WETHA_RENDER_WORKERS` to change this.
- **Constant-cost joins:** each fade is built as a short dissolve piece between its two neighbours. The cost per fade stays the same however long the program is, and no step grows with the scene count.
- **One continuous encode:** the full program is encoded in one pass, so there are no decoder resets at cuts.
- **Hardware encoder:** programs of 10 minutes or more use the Mac hardware H.264 encoder when it's available. Set `WETHA_VIDEO_ENCODER=software` or `auto` to choose.
- **Resume:** completed scenes are checksummed and saved as the render goes. A render interrupted by a crash or restart can be retried and reuses them.
- **Limits:** timelines run up to two hours and 1,500 scenes.

Automatic source matching is **not semantic verification or human broadcast approval**. Claims retain their original editorial status. The timeline records the automatic audit, supporting source excerpts, alignment lineage and checksums. Expired warnings retain their expired label. Missing radar/satellite observations and insufficient matching footage remain visible limitations; the app does not create observations or invent footage locations.

Rendering, source matching and local speech alignment do not call a paid AI API. No Groq key is required for this workflow.
