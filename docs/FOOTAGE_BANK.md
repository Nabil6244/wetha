# Florida footage bank

The reviewed catalogue is [FLORIDA_FOOTAGE_BANK.json](FLORIDA_FOOTAGE_BANK.json). It records local checksums, source URLs, credits, capture regions, archival events, transformations and 3.5-second cut ranges. Downloaded videos stay in `.local` and are excluded from Git.

Seven newly collected DVIDS recordings cover neighborhood rain and wind, coastal waves, aerial damage, debris clearance, temporary roofing and humanitarian relief. Six previously reviewed Pexels coastal recordings are also imported into the dashboard, rather than remaining only in export folders. Offshore Gulf footage has no Florida land-region attestation.

The 13 library entries contain 18 minutes 52 seconds of source material. The catalogue marks 46 non-overlapping 3.5-second cut ranges (2 minutes 41 seconds of selected footage); all ranges passed a decode check. A 51-second silent preview is saved at `.local/footage-expansion/florida-footage-preview.mp4`. The running app import was verified against each checksum, event and location attestation.

These are historical recordings from Irma (2017), Michael (2018), Ian (2022) and Milton (2024). Never substitute them for footage of Isaias, or present them as today's weather. The Fort Myers source has conflicting dates: its description says September 30, 2022, while its Date Taken field says October 1. Its exact capture date remains unset. The Pexels files have unknown capture dates and remain illustrative.

Source audio is removed from new archival copies, including the edited Milton package. The large Bradenton source is resized to 720p to fit the app's 250 MiB file limit; its original checksum is retained. Lower-resolution archive sources are not claimed to be native 1080p.

A licensed YouTube-origin Miami Shores recording is documented under `pending`. Wikimedia's source page records Sonny A's CC BY 3.0 license review. Its download was unavailable in this environment; it is not imported or counted. It is portrait footage and should eventually appear in an inset beside a graphic.

## Import into a running local app

Read the backend port from the desktop app's runtime connection. Then, from the project root:

```sh
.venv/bin/python scripts/import-footage-bank.py --api http://127.0.0.1:PORT --check-only
.venv/bin/python scripts/import-footage-bank.py --api http://127.0.0.1:PORT
```

The script validates all local checksums, media contracts and cut bounds before importing. Imports use the application's normal rights and duplicate checks. The local `import-result.json` maps catalogue source IDs to media library IDs for timeline construction. Existing media with identical bytes are reused.

## Editing longer programs

Source minutes are not the same as unique finished coverage. The initial cut bank deliberately samples short ranges rather than padding an hour with repeated camera positions. Range IDs and camera families are recorded for episode-wide tracking. Use a cut once per episode, separate similar camera views, and alternate location-appropriate footage with measured local statistics, explanatory graphics and evidence maps.

This bank adds variety; a finished one-hour episode still needs a chapter-specific footage selection and additional sources for uncovered subjects. Rain, active wind, aftermath and recovery belong at different points in the story. Archived radar screens remain archived images, never current forecast maps.

For DVIDS sources, retain credited authors, the source URL and the source's non-endorsement statement in production credits. Current statement recorded at review:

> The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.

Sources: [DVIDS public use terms](https://www.dvidshub.net/about/copyright), [licensed Miami Shores archive](https://commons.wikimedia.org/wiki/File:Hurricane_Irma.webm), [Pexels license](https://www.pexels.com/license/).

## Combined edit

The [combined clips, statistics and maps report](FLORIDA_MIXED_REPORT.md) interleaves this bank with the approved recorded forecast and adds explicit historical context narration.

## Picture-area quality review

A stricter review excludes nine of the original 46 cut ranges because the source recordings contain short black sections inside them. There are **37 cleared ranges**. Rejected IDs remain documented for provenance and must not be selected. The default Bradenton trim now starts at a cleared range. Picture-area checks exclude overlay headers, which can hide a blank image from whole-frame tests.
