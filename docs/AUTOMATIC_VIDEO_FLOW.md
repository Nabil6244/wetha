# Automatic local video preparation

In Create Video, paste the final narration and select **Save script & prepare automatically**. This maps chapters to the preserved reports without requiring a source dropdown for each paragraph. An optional editor name records authorship, not source approval.

Upload the matching voiceover, then select **Make final video**. The app:

1. Audits the preserved source package, numerical values, ranges and units. Unsupported values identify the paragraph needing correction.
2. Reuses completed speech alignment tied to this exact script, plan and audio checksum. Otherwise it starts local alignment and continues preparation automatically when it completes. Matches below 95% require confirmation.
3. Subdivides aligned narration into visual shots of up to four seconds, keeping the original audio frames and source claim IDs. Internal visual cuts are editorial boundaries, not new speech recognition.
4. Repairs chapter geography from the source mapping, adds source-derived rainfall/surge/wind range charts, and mixes available licensed footage. It preserves manually selected footage. Repeated charts for the same claim are suppressed.
5. Checks map holds, media rights/ranges, narration duration and evidence checksums, then queues the local 1080p MP4 render.

Automatic source matching is **not semantic verification or human broadcast approval**. Claims retain their original editorial status. The timeline records the automatic audit, supporting source excerpts, alignment lineage and checksums. Expired warnings retain their expired label. Missing radar/satellite observations and insufficient matching footage remain visible limitations; the app does not create observations or invent footage locations.

Rendering, source matching and local speech alignment do not call a paid AI API. No Groq key is required for this workflow.
