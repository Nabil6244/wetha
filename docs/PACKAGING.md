# Native distribution foundations

Electron Builder is configured for Windows x64 NSIS and macOS DMG. **No native installer has been built or tested in this Linux cloud environment.** The scripts fail preflight if the required native backend runtime is absent; a package containing only the UI is not treated as a working standalone app.

Development uses the project's virtual environment. Distribution must bundle a relocatable Python runtime at:

- Windows: `backend-runtime/python.exe`
- macOS: `backend-runtime/bin/python3`

The bundle must include SQLite and the backend dependencies pinned in `backend/requirements.lock`. A virtual environment symlinked to a developer's Python is not a standalone runtime. Python runtime redistribution notices and dependencies must travel with the installer. Build separate macOS arm64 and x64 bundles on the corresponding architecture. Do not combine one Python architecture with a different Electron target.

Build on the target operating system using `npm run package:win` or `npm run package:mac`. The macOS script builds for its native host architecture; run it on both arm64 and x64 hosts. A future release pipeline should acquire authoritative Python binaries, verify their published checksums/signatures, run backend/UI tests with the bundled interpreter, and validate installation on a clean machine.

Electron 44 supports Windows 10+ and macOS Ventura+. Older macOS releases are not claimed. Intel Macs must support the selected macOS/Electron version. Windows/macOS signing certificates, macOS notarization, upgrade behavior, firewall/permission handling, and auto-update distribution are not configured in Phase 1.

Acceptance includes launch on a clean target machine without a system Python, verified backend readiness, persistent app data, source fetching, renderer isolation, shutdown without orphan processes, uninstall behavior, and signed/notarized installer checks. FFmpeg and voice model distribution are future requirements with separate integrity and licensing review.
