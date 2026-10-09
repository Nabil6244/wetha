# Four animated map treatments

Each scene in Broadcast style now offers **Map type**. Choose a planned graphic
with no imported footage, then select a map treatment, Check, Save and Render.
A saved timeline retains the selected map type and its pinned source layers.

- **Reported track & motion compass:** reveals source-reported centers in time
  order and shows the advisory's bearing and speed. Connectors join reported
  positions; the compass arrow is not a predicted route.
- **Warning areas & coverage:** fills and reveals original official warning
  polygons. Without polygons, it displays named source coverage and explicitly
  avoids inventing a boundary from place names.
- **Radar observations:** plays cached NOAA radar frames within one hour of the
  advisory, retaining UTC observation labels and the source legend when present.
  Reflectivity is dBZ; it does not show accumulated rainfall or expected rain.
- **Forecast outlook & uncertainty:** reveals source-provided cone geometry only
  with a matching advisory checksum, issue time and explicit source valid time.
  Forecast geometry differs in styling from reported centers. Missing geometry
  falls back to source forecast wording, without drawing a predicted route.

Collection remains in Visual Director. Radar collection caches current regional
observations; it does not retrieve past weather automatically. Cone collection
supports regular officially fetched NHC advisories. An intermediate advisory
such as 7A cannot be substituted with an unrelated regular cone. KMZ packages
without an explicit end/valid timestamp remain wording-only forecast scenes.

Animation progress describes scene playback. Observed times, advisory issue
and forecast validity remain separate. Layers and legends are checksum-checked;
changed pinned observations block rendering. These remain local editorial
previews. No paid generation or voiceover is involved.

Validation: build, 122 backend tests and 14 browser checks passed. Tests exercise
all four scene treatments, fallback rendering, save/reload, source radar frames,
legend checksums and timestamped forecast geometry using synthetic fixtures.
The desktop sample at `.local/exports/maps/map-treatments-30.mp4` uses the saved
prerecorded report. Its radar and forecast cone are unavailable; these scenes
show labeled availability and source wording rather than generated weather.
