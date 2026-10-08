# Dependency and content licensing

Direct package license declarations were inspected in the installed packages during Phase 1. Permissive licenses permit commercial use subject to their notice and redistribution obligations. This is an inventory, not completed release compliance.

| Component | Version | Declared license |
|---|---|---|
| React / React DOM | 19.3.0 | MIT |
| Electron | 44.7.0 | MIT; bundled Chromium/Node notices also apply |
| Vite | 8.3.3 | MIT |
| Tailwind CSS | 4.3.3 | MIT |
| Lucide React | 1.52.0 | ISC |
| Electron Builder | 26.15.3 | MIT |
| FastAPI | 0.135.4 | MIT |
| Uvicorn | 0.42.0 | BSD-3-Clause |
| HTTPX | 0.28.1 | BSD-3-Clause |
| platformdirs | 4.9.4 | MIT |
| SQLite | Python runtime library | Public domain |

Dependency lockfiles record the installed graph. Transitive package declarations include permissive licenses and MPL-2.0; release work must preserve all required notices and handle file-level MPL obligations where applicable. No voice model or stock asset is installed, and no commercial model license is assumed.

The onboarding npm audit found no production-dependency advisories and no high/critical advisories in the final installed graph. Eight moderate development-graph entries trace to Electron Builder's `global-agent` / `roarr` / `sprintf-js` chain. The registry offers no patched `sprintf-js` release in that chain. These must be revisited before using the packaging tooling for a release; no installer is produced here. A local development launcher avoids the unnecessary shell-command dependency chain.

The cloud's FFmpeg 7.1.5 build enables GPL components including x264. It is currently only detected, not bundled or used to produce media. Distribution must select an appropriate verified FFmpeg build, satisfy its actual LGPL/GPL obligations, and assess codec patent obligations where relevant.

Official weather text and government-produced observations require attribution and timestamp preservation. Do not assume that every NOAA-hosted image, third-party contribution, logo, or linked asset is public domain. Asset-level rights records are required before media use. No YouTube footage or external stock media is downloaded in Phase 1.

The project is private in package metadata; no open-source license for the application itself has been chosen by the owner.

## Phase 4 geographic dependencies

MapLibre GL JS 6.13.0 is BSD-3-Clause licensed and pinned in the npm lockfile. Natural Earth 1:110m country geometry is public domain; its source, transformation and content checksums are in `backend/app/data/provenance.json`. NOAA/NESDIS/STAR and NOAA nowCOAST visual products retain source URLs, timestamps and attribution. Availability does not override product-specific licensing/credit terms. No private tiles, paid map service or third-party ground footage is bundled.
