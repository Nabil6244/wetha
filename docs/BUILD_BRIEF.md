# MASTER BUILD PROMPT — WEATHER INTELLIGENCE STUDIO
## Professional AI Weather News Production & 24/7 Broadcasting Software

### YOUR ROLE

Act as a team of expert software architects, meteorological data engineers, AI automation developers, broadcast engineers, cinematic visualization specialists, UI/UX designers, and quality assurance engineers.

Your task is to **design and build a complete, standalone, cross-platform desktop application called Weather Intelligence Studio**.

This must be a real, working production application, not just a UI mockup, proof of concept, or technical proposal.

The software must run on:

- Windows 10/11 (64-bit)
- macOS Apple Silicon (M1/M2/M3/M4 and newer)
- macOS Intel (where dependencies remain compatible)

Build the application from a single shared codebase, with platform-specific installers.

## 1. CORE MISSION

Create a fully automated weather news production system that:

1. Collects fresh weather data from trusted official sources.
2. Identifies important weather developments.
3. Compares new information with previous advisories.
4. Verifies meteorological facts and source timestamps.
5. Generates professional, engaging English weather news scripts.
6. Creates scene-by-scene production instructions.
7. Generates realistic AI voiceovers.
8. Selects relevant, properly licensed stock footage.
9. Generates highly realistic cinematic weather visuals.
10. Produces complete 60-minute weather news programs.
11. Automatically delivers completed programs to a broadcast playlist.
12. Controls OBS for continuous YouTube Live broadcasting.
13. Produces the next program while the current one is broadcasting.
14. Supports future expansion to multiple independently branded channels.

**Start with ONE US Extreme Weather Channel. Architect for 40–50 channels in the future, without building unnecessary multi-channel infrastructure now.**

## 2. NON-NEGOTIABLE REQUIREMENTS

- No cartoon-style weather visuals.
- No fake satellite observations.
- No fictional storm tracks presented as real forecasts.
- No excessive text slides.
- No cheap-looking AI animations.
- No repetitive stock footage sequences.
- No unnecessary expensive cloud services.
- No mandatory paid APIs or subscriptions for the MVP.
- No dependence on an existing Semantic YT Studio installation.
- No publishing dangerous or unverified weather information.
- No unauthorized YouTube footage or copyrighted news clips.
- Do not claim a program is live reporting when its information is prerecorded or outdated.

Visual quality must be premium, realistic, cinematic, data-driven, and suitable for a professional international weather channel.

## 3. TECHNOLOGY ARCHITECTURE

Use the following initial stack:

| Layer | Technology |
|---|---|
| Desktop UI | Electron + React + TypeScript |
| Styling | Tailwind CSS |
| Backend | Python + FastAPI |
| Database | SQLite + migrations |
| Agent Orchestration | Python background workers |
| Weather Data | NOAA, NWS, NHC official feeds |
| Map Engine | MapLibre GL JS |
| Advanced Layers | deck.gl when needed |
| Satellite Processing | Python + FFmpeg |
| Video Rendering | FFmpeg |
| Narration | Kokoro TTS or equivalent local TTS |
| Speech Alignment | Whisper or compatible aligner |
| AI Scripting | Existing supported Gemini integration or optional local LLM |
| Live Broadcast | OBS Studio + OBS WebSocket |
| Packaging | Electron Builder |

Choose version-compatible, maintained dependencies and verify commercial licensing.

Provide a pluggable interface for each AI model, TTS engine, visual renderer and weather provider.

## 4. ARCHITECTURE

Implement these independent modules:

```text
Weather Intelligence Studio
│
├── Desktop Application
│   ├── Dashboard
│   ├── Weather Intelligence
│   ├── AI Newsroom
│   ├── Script Editor
│   ├── Voice Studio
│   ├── Visual Director
│   ├── Media Library
│   ├── Video Production
│   ├── Broadcast Scheduler
│   ├── OBS Controller
│   ├── Channel Manager
│   └── Settings
│
├── Python Backend
│   ├── Weather Data Providers
│   ├── Data Normalization
│   ├── Event Detection
│   ├── Fact Verification
│   ├── Editorial Agents
│   ├── Script Generation
│   ├── Voiceover Generation
│   ├── Media Matching
│   ├── Weather Visual Engine
│   ├── FFmpeg Renderer
│   ├── Production Queue
│   └── Broadcast Automation
│
├── Persistent Storage
│   ├── Weather Snapshots
│   ├── News Events
│   ├── Sources
│   ├── Scripts
│   ├── Voiceovers
│   ├── Visual Assets
│   ├── Rendered Videos
│   └── Broadcast History
│
└── Future Multi-Channel Support
    ├── Channel Profiles
    ├── Independent Editorial Rules
    ├── Branding
    ├── Voice Profiles
    └── Separate Broadcast Queues
```

Keep rendering and broadcasting independent so a production failure does not interrupt the currently running stream.

Use typed API contracts, structured logs, retry policies, job status tracking and resumable workflows.

## 5. MULTI-AGENT AI NEWSROOM

Implement six agents.

**Agent 1: Weather Data Collector**

Collect official information from:

- https://api.weather.gov/
- https://api.weather.gov/alerts/active
- https://www.nhc.noaa.gov/
- https://www.nhc.noaa.gov/index-at.xml
- https://www.nhc.noaa.gov/gis/rss.php
- https://www.star.nesdis.noaa.gov/GOES/

Support advisory polling, caching, retries, structured storage and deduplication.

**Agent 2: Change Detection**

Compare new advisories with previous versions.

Extract changes in storm position, intensity, pressure, warnings and forecast guidance.

Generate a structured "WHAT CHANGED?" summary.

**Agent 3: News Prioritization**

Prioritize events based on severity, recency, geographic relevance, potential impacts and available verified information.

**Agent 4: Fact Verification**

Preserve source links, issue timestamps, validity periods, units and confidence status.

Flag unsupported claims and contradictory information.

Do not allow an LLM to invent meteorological facts.

**Agent 5: AI Scriptwriter**

Generate natural, broadcast-quality English scripts based on verified source packages.

Each script should cover:

- What happened?
- What changed?
- Where is it happening?
- Why does it matter?
- What are official forecasters predicting?
- What should affected viewers know?

Create original analysis and explanations instead of merely reading alerts.

**Agent 6: Editorial Quality Controller**

Review factual correctness, repetitive phrasing, timing, voiceover suitability, source attribution and forecast uncertainty.

Require human approval when the reporting concerns ambiguous, high-impact emergency information.

All agents must communicate through structured JSON contracts.

Use deterministic Python code for routine tasks instead of unnecessary LLM calls.

## 6. AUTOMATED HOURLY NEWS PRODUCTION

The software must generate approximately one hour of programming every hour.

Initial editorial rundown:

| Program Section | Duration |
|---|---:|
| Top Weather Headlines | 5 minutes |
| Major Storm Coverage | 15 minutes |
| Severe Weather Updates | 10 minutes |
| US Regional Forecast | 10 minutes |
| Weather Science Explainer | 10 minutes |
| Historical Weather Documentary | 10 minutes |

The schedule must adapt dynamically to actual news availability.

Use clearly labeled evergreen features when breaking-news volume is low.

Preserve original advisory timestamps throughout production.

Do not treat prerecorded footage as current footage.

## 7. PREMIUM CINEMATIC WEATHER VISUAL ENGINE

This is the most important visual component.

The application's visual standard must resemble a high-end meteorological documentary combined with professional television weather journalism.

### A. Cinematic Moving Maps

Implement:

- Smooth zoom-in and zoom-out.
- Geographic camera tracking.
- Camera pans.
- Controlled rotation.
- Eased transitions.
- Regional location highlights.
- Satellite-to-map transitions.
- Continuous visual storytelling across scenes.

### B. Real Satellite Time Machine

Use actual timestamped GOES satellite imagery.

Show weather evolution across historical observation times.

Support animated satellite loops with camera movement.

Include observational timestamps and source attribution.

Never synthesize false weather observations.

### C. Radar and Rainfall Layers

Display authentic precipitation and radar data where available.

Support:

- Animated rainfall intensity.
- Geographic alignment.
- Proper color legends.
- Observation timestamps.
- Visual transitions from stock footage to radar.

Distinguish model forecasts from observations.

### D. Hurricane Tracking

Display official historical tracks and forecast cones.

Support:

- Storm position.
- Historical movement.
- Category changes.
- Wind-speed changes.
- Pressure changes.
- Official projected trajectories.
- Advisory timestamps.

Never fabricate forecast cones.

### E. Premium Statistical Graphics

Develop reusable animated templates for:

- Wind speed.
- Air pressure.
- Rainfall.
- Temperature.
- Storm category.
- Advisory changes.
- Forecast comparisons.
- Weather warnings.

The signature visual feature should be called:

**WHAT CHANGED?**

It should visually compare the previous official advisory with the latest verified advisory.

### F. Professional Visual Standards

Use:

- Authentic satellite textures.
- Accurate geographic coastlines.
- Realistic map color treatment.
- Subtle professional motion graphics.
- Minimal typography.
- High visual contrast.
- Clean broadcast layouts.
- Consistent lower thirds.
- Restrained transitions.
- High-quality compositing.

Avoid cartoon clouds, artificial spinning hurricane icons, excessive neon glows, fake weather particles and dramatic effects that misrepresent weather observations.

## 8. VISUAL STORYTELLING INNOVATIONS

Implement these reusable visual concepts:

**Weather Time Machine**

Travel visually through real historical satellite observations.

**What Changed?**

Show meaningful advisory differences through precise animated comparisons.

**Storm Journey**

Follow a cyclone's observed movement geographically.

**Weather Impact Explorer**

Focus on affected places and display relevant verified impacts.

**Forecast vs Reality**

Compare historical model forecasts with subsequent observed outcomes, clearly labeling both datasets.

**Satellite-to-Ground**

Transition from satellite or map imagery to authentic, appropriately licensed ground footage.

**Visual Evidence Timeline**

Show weather development with verified timestamps and source evidence.

Visual innovation must improve understanding, not merely make the video more dramatic.

## 9. STOCK FOOTAGE ENGINE

Build a searchable, reusable media library.

Support:

- Local video imports.
- Licensed stock footage.
- Public-domain government media.
- Asset metadata.
- License records.
- Keyword tagging.
- Scene matching.
- Cached downloads.
- Duplicate detection.
- Video trimming.
- Automatic aspect-ratio adaptation.

Use approximately 60–75% relevant footage, 15–25% weather data visuals and the remainder statistical graphics as an initial editorial target, not a fixed rule.

Never download and republish arbitrary YouTube footage without appropriate rights.

Clearly label archival footage where necessary.

## 10. VOICEOVER ENGINE

Implement a professional AI narration pipeline.

Requirements:

- Natural American English.
- Consistent news-anchor voice.
- Clear pronunciation of US locations.
- Correct handling of meteorological terminology.
- Natural pauses.
- Adjustable delivery speed.
- WAV export.
- Audio normalization.
- Script-to-audio timing alignment.
- Retry support.
- Optional multiple voice profiles.

Prefer a commercial-use-compatible locally executable TTS model to avoid recurring API fees.

Provide an audio preview before final rendering.

## 11. AUTOMATED SCENE DIRECTOR

The AI Visual Director must turn verified scripts into structured scene instructions.

Supported scene types:

```text
stock_footage
satellite_timelapse
radar_animation
cinematic_weather_map
storm_track
forecast_cone
weather_stat
what_changed
weather_timeline
lower_third
news_intro
historical_footage
```

Every scene must contain:

- Scene ID.
- Script segment.
- Target duration.
- Asset type.
- Visual instructions.
- Structured parameters.
- Source references.
- Advisory timestamp.
- Camera movement.
- Transition type.
- Fallback asset.
- Voiceover alignment data.

Allow export and import of scene CSV files.

All timing must be derived from actual voiceover duration where possible.

## 12. VIDEO RENDERING ENGINE

Use FFmpeg and compatible rendering components.

Support:

- 1920×1080 output.
- 30 fps initially, optional 60 fps.
- H.264 video.
- AAC audio.
- Consistent audio levels.
- Subtitle generation.
- Scene transitions.
- Background music mixing.
- Output validation.
- Resume failed renders.
- Intermediate asset caching.
- Parallel asset preparation.
- Final program assembly.

Optimize for local CPU and GPU resources.

Provide hardware acceleration where supported and tested.

Do not assume a particular GPU is installed.

## 13. 24/7 BROADCAST AUTOMATION

The central operating model is continuous hourly production.

Example:

```text
12:00 — Program A begins broadcasting
12:00 — Program B production begins
12:35 — Program B rendering completes
12:40 — Program B passes quality control
12:40 — Program B enters broadcast queue
13:00 — Program B begins broadcasting
13:00 — Program C production begins
14:00 — Program C begins broadcasting
```

These times are illustrative targets, not guaranteed performance.

Implement:

- Automatic playlist scheduling.
- OBS WebSocket integration.
- Seamless program transitions.
- Next-program readiness checks.
- At least one emergency fallback program.
- Broadcast watchdog.
- Failed-render recovery.
- Error notifications.
- Automatic stream continuity monitoring.
- Safe handling of expired weather warnings.
- Manual override controls.

Never publish a stale emergency forecast as a current warning.

The broadcast process must remain operational even when the production process fails.

## 14. CROSS-PLATFORM APPLICATION

Deliver native desktop installers.

**Windows**

- Windows 10/11 compatibility.
- Appropriate FFmpeg binaries.
- Supported GPU acceleration.
- Installer and update handling.

**macOS**

- Apple Silicon support.
- Intel support where feasible.
- Appropriate FFmpeg binaries.
- Apple Silicon optimizations where supported.
- macOS permissions handling.
- Signed/notarized distribution options.

Handle backend process lifecycle correctly on both operating systems.

Use platform-safe paths and avoid hardcoded Windows-specific assumptions.

## 15. CONTROL CENTER UI

Create a premium dark-themed broadcast control dashboard.

Include:

- Active weather events.
- Source freshness.
- New warnings.
- AI agent activity.
- Current script.
- Next scheduled program.
- Voiceover generation status.
- Asset download progress.
- Render progress.
- OBS connection status.
- Live broadcast status.
- Fallback playlist status.
- Error notifications.
- Channel settings.

The interface should feel like professional broadcast operations software, not a generic AI dashboard.

## 16. QUALITY AND SAFETY

Implement automated checks for:

- Missing or stale source information.
- Unsupported weather claims.
- Incorrect source timestamps.
- Expired warning replay.
- Broken footage.
- Missing audio.
- Incorrect video duration.
- Black frames.
- Audio clipping.
- Duplicate content.
- Failed rendering.
- Missing broadcast files.
- Unsafe transitions.

Do not insert content into the live queue until essential checks pass.

Use manual review for uncertain high-impact weather reporting.

## 17. FUTURE MULTI-CHANNEL EXPANSION

The initial application must run one channel.

Design future channels as independent configurations.

Each channel should have:

- Channel ID.
- Geographic focus.
- Language.
- Branding.
- Voice profile.
- Editorial rules.
- Visual style.
- Production schedule.
- Broadcast queue.
- YouTube streaming configuration.

Shared weather intelligence and media caches should prevent unnecessary duplicate processing.

Future channels must create genuinely distinct editorial programming rather than minor variations of identical videos.

## 18. IMPLEMENTATION PLAN

Build the system in phases.

**PHASE 1 — Application Foundation**

Create the Electron/React desktop app, Python backend, database, configuration, logging and packaging foundations.

**PHASE 2 — Weather Intelligence**

Implement official weather data ingestion, event storage, change detection and verification.

**PHASE 3 — AI Newsroom**

Build multi-agent orchestration, script generation, source tracking and editorial review.

**PHASE 4 — Cinematic Visual Engine**

Implement real geographic maps, satellite time machines, radar, camera movement and statistical graphics.

**PHASE 5 — Video Production**

Connect voiceover generation, stock footage management, visual timeline assembly and FFmpeg rendering.

**PHASE 6 — Live Broadcasting**

Implement OBS automation, hourly playlist generation, fallback handling and continuous broadcast monitoring.

**PHASE 7 — Production Hardening**

Test reliability, performance, installer builds, restart recovery, resource usage and continuous operation.

## 19. FIRST PRODUCTION MILESTONES

Before claiming the application is production-ready, demonstrate:

1. Import a historical official hurricane advisory.
2. Detect verified changes between two advisories.
3. Generate a fact-grounded English news script.
4. Generate natural AI voiceover.
5. Produce a professional 30-second realistic visual demonstration.
6. Produce a complete five-minute weather news video.
7. Generate a full 60-minute program.
8. Complete the next program while the previous program plays.
9. Successfully test continuous OBS broadcasting for 24 hours.
10. Build and test Windows and macOS installers.

Use historical weather data for reproducible early tests.

Do not label a visual prototype as live meteorological coverage.

## 20. REQUIRED DEVELOPMENT BEHAVIOR

Before coding:

- Examine the existing repository and environment.
- Identify available dependencies and hardware limitations.
- Present the architecture and file structure.
- Define database schemas and service interfaces.
- Establish clear acceptance criteria.
- Identify licensing or operational risks.

Then begin implementing the first working vertical slice.

**Do not stop after providing documentation. Write real source code, configuration files, database migrations and tests.**

Run available tests after each milestone.

Never claim a feature works without testing it.

Do not invent completed integrations, successful renders, live streams or installer builds.

If a feature requires credentials, hardware, an external binary, or human approval, implement everything possible and clearly identify the remaining blocker.

Keep implementation modular, maintainable and cross-platform.

## FINAL OBJECTIVE

Deliver **Weather Intelligence Studio**, a professional Windows and macOS weather news production platform capable of transforming official meteorological data into realistic cinematic video programs and operating a continuously updated YouTube Live channel.

Our distinguishing strengths must be:

**REAL WEATHER DATA + CINEMATIC VISUAL JOURNALISM + AUTOMATED AI NEWSROOM + CONTINUOUS HOURLY BROADCASTING.**

Start with one reliable, high-quality channel. Build the foundation for future expansion.

**NOW BEGIN PHASE 1: Inspect the development environment, define the project architecture, generate the full project structure, and implement the first working application milestone.**
