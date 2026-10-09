# Documentary edit

The current desktop preview is `.local/exports/documentary/isaias-documentary-90.mp4`: a complete 90-second historical Isaias sequence, 1920×1080, 30 fps, 2,700 video frames, with locally synthesized instrumental music and no voiceover. This supersedes the graphics demonstration as the first production preview.

The 24-shot edit uses 36 seconds of licensed footage, 36 seconds of genuine advancing NWS satellite/radar imagery, and 18 seconds of traveling maps. Footage cuts last three seconds and use distinct, nonoverlapping source ranges. Each native observation sequence progresses through all 136 original frames once, with its timestamp and legend retained. Map animation uses official reported positions, coastal warning lines and the forecast cone/points as issued. Camera movement and connecting lines are presentation effects.

Statistics appear over the action: NHC reported winds of 70→85 mph and pressure of 998→988 mb over twelve hours; an NWS post-event gauge reading of 6.80 inches is separately attributed. There are no full-screen text cards or synthetic observation frames. Stock footage is labeled illustrative; the single YouTube-origin Irma clip is a labeled 2017 comparison with CC BY attribution. The manifest carries sources, licenses, frame ranges, geometry and checksums. Captions and the shot script are adjacent to the video.

Rebuild using `.venv/bin/python scripts/render-documentary.py`. Assets are reused locally, with no paid generation, TTS or new media download. The reusable renderer is `backend/app/documentary.py`; the desktop serves the video, source manifest and SRT through `/api/production/documentary/{video|manifest|subtitles}`. Rendering validates every shot's frame count, the final video stream's length, a full decode and a black-frame scan.

This is a short completed documentary edit, not the one-hour program. The four-source footage library is still too small for independent scene variety across an hour. The twelve-chapter plan and hour assembler require completed sourced chapters and additional distinct footage; repeating this preview does not meet those requirements.
