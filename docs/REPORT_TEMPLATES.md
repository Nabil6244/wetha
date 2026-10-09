# 60- and 90-second reports

In Video Production, choose a source-linked plan, select **60-second report**
or **90-second report**, then Suggest, Apply, Check visuals & timing, Save,
and Render. Generation uses imported local media and FFmpeg; it makes no paid
model calls and generates no voiceover.

Reports preserve each script scene once, in order. Intro and closing cards
hold for three seconds; protected maps and statistics hold for six seconds.
Footage scenes contain multiple 3–4-second segments, with credits and context
labels for each source. Both templates have exact frame-based durations at
30 fps. Footage ranges never overlap or loop; still images appear once.

The editor lists source filenames, trim starts and durations. Clearing a
sequence allows manual editing. Suggested reports require 3–15 script scenes
and enough matching footage; an incomplete draft cannot be applied. Imported
footage remains contextual and does not become evidence of the reported storm.

The small sample library can reuse different ranges from the same source.
Those segments may look similar, particularly consecutive ranges from one
recording. More independently filmed clips will provide greater visual variety.
This phase adds duration templates, not automatic narrative expansion or new
weather observations. Short scripts should be expanded editorially before
making longer reports.

Validation: 117 backend tests, 12 browser checks, and a production build passed.
The actual desktop library produced valid 60- and 90-second drafts with 9 and
17 footage segments respectively. A 60-second preview is exported locally;
the 90-second draft is saved without an additional render.
