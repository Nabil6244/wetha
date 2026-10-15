# Self-contained desktop distribution

Windows distribution is a **single portable EXE**. The user double-clicks it; its internal application files are unpacked automatically. No separate Python, Node.js, FFmpeg, speech package or model installation is needed. Normal projects, media and settings are stored in the user's application-data folder.

macOS distribution is a DMG containing the complete `.app`. Build separate Apple Silicon and Intel versions. Live weather/media collection needs internet; local speech alignment uses the included model without downloads.

## Build-time setup

Build on the matching operating system and architecture. The build machine needs Node.js 24 and Python 3.12; the Windows build also uses the licensed Visual Studio redistributable files already available on GitHub Windows runners. Recipient computers do not install these tools.

```sh
npm ci
python scripts/prepare-standalone.py
node --test scripts/runtime.test.cjs
npm run package:win   # Windows x64 portable EXE
npm run package:mac   # macOS DMG for the host architecture
```

`package:win:setup` additionally supports a conventional setup EXE. The default requested Windows delivery is `portable`, not an installer or source ZIP. Outputs go into `release/`.

The preparation script downloads only source-pinned, SHA-256-verified components listed in `scripts/standalone-sources.json`:

- Relocatable native CPython 3.12 from Astral python-build-standalone.
- FFmpeg and FFprobe with distribution notices.
- The pinned English Whisper model and its notices.
- On Windows, app-local C++ runtime DLLs from the licensed Visual Studio build host, verified as Microsoft-signed and recorded in the bundle manifest.
- All backend/speech dependencies from `backend/requirements-standalone.lock`, installed with hash verification and binary wheels only.

`backend-runtime/` is generated and excluded from Git. It includes the offline model, rendering tools, interpreter, dependencies and a bundle manifest. A development virtual environment is not used as the distributed runtime. The packaging preflight rejects missing components, changed pinned assets, wrong architecture and native-import failures.

Packaged startup ignores developer Python/model paths and uses only its own runtime and tools. The speech model is opened by local path with `local_files_only=True`. Existing local scripts, uploaded audio, API secrets and `.local/` development files are excluded from the installer.

## Automated builds

`.github/workflows/package-standalone.yml` is a manually triggered workflow for Windows x64, macOS ARM64 and macOS Intel. It builds portable EXE/DMG artifacts, then runs a fresh-data smoke test against the packaged resources with developer tools removed from PATH. It does not publish releases. A GitHub repository is required to run this workflow; a runner smoke test does not establish clean-machine acceptance.

## Acceptance and current status

The Apple Silicon DMG has been built locally, mounted read-only, copied into a separate installation directory, and its desktop window opened with an empty test profile. The packaged-resource test passed bundled FFmpeg/FFprobe execution, offline speech inference, backend startup and a synthetic 1080p render with full decode and output validation. Detailed results are written to `release/standalone-smoke-macOS-arm64.json`.

Windows EXE and Intel DMG have not been built or tested yet. True clean-machine installation tests, Windows DLL/runtime acceptance, macOS Developer ID signing/notarization, and Windows signing remain separate release checks. The current Mac artifact is an unsigned private test build; it is not a signed public release.

Before distribution, test each artifact on an appropriate clean target machine: app launch, fresh projects, script/audio import, offline speech alignment, an actual narrated render, saved-state recovery, shutdown and reopening. Preserve the bundled component licenses and source/build notices.

## macOS test-build signatures

Test DMGs use explicit ad-hoc signing (`mac.identity: "-"`) with strict bundle verification. Skipping signing after Electron is renamed leaves its original linker signature invalid and can produce the misleading “damaged” message. CI now checks `codesign --verify --deep --strict` before uploading a Mac artifact, in addition to the runtime/render smoke test.

Ad-hoc signing repairs bundle integrity; it does not provide a Developer ID or Apple notarization. macOS can still require explicit security approval for downloaded test builds. Normal trusted distribution requires Developer ID signing and notarization. No Gatekeeper or quarantine bypass is included.
