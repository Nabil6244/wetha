# Free media discovery

Media Library now includes **Discover free weather footage**. Initial results are
the three reviewed sample sources: two Pexels stock clips and a CC BY 3.0
YouTube-origin Irma clip from its Wikimedia archive. Existing local imports are
used for previews and are identified as already in the library.

Search by weather terms and optionally select a scene plan to compare declared
event and capture date. **Use script weather topics** derives search terms from
the plan. Results show preview controls, creator credit, license, source links,
source-declared date when available, and matching reasons. Catalogue declarations
remain contextual; matching a name or date does not verify event attribution.

## Available sources

- **Reviewed stock clips:** the fixed, previously reviewed Pexels catalogue.
  These are not live Pexels API results. **Search Pexels** opens a broader search
  for manual selection and local import; no API key is configured.
- **Wikimedia Commons:** live key-free MediaWiki search, video and still images,
  using Imageinfo/Videoinfo metadata. Supported candidates must have a suitable
  original file, creator credit and CC BY, CC0 or public-domain declaration.
  Unsupported license/file types are excluded. This is a declared-license filter,
  not an independent rights investigation.
- **YouTube-origin licensed archives:** Wikimedia candidates whose credit links
  to an original YouTube video under CC BY, plus the reviewed Irma sample.
  **Search YouTube** opens a broader search for manual license review. The app
  imports approved archive copies; it does not download arbitrary YouTube URLs.

The initial catalogue and **Include live Wikimedia search** toggle allow use
without live network requests. Network failures show a visible message while
reviewed results and external search links remain available.

## Import

After reviewing the source and usage terms, select **Import selected source**.
The backend looks up the server-preserved candidate ID rather than accepting a
download URL from the client. Downloads use HTTPS to the approved Wikimedia and
Pexels media hosts, without following redirects, with a 250 MiB limit. Source
checksums are checked where recorded; changed bytes abort before media is saved.
Existing library files are reused without another download.

The normal media import validates dimensions, actual file format and duration.
Credits, license, original URL and reuse evidence are retained. Weather tags and
known catalogue facts are attached for automatic short-edit suggestions; unknown
capture dates and locations remain blank. File upload dates are never treated as
capture dates. Existing source/rights records are preserved on duplicates.

## Validation and limits

The build passed, along with 114 backend tests and 11 browser workflows. New
tests cover metadata normalization, license filtering, YouTube-origin detection,
host restrictions, caching, imports with actual synthetic image bytes, duplicate
reuse, changed-checksum cleanup, offline fallback and mobile layout.

Live network verification on 9 October 2026 encountered DNS resolution failure
for the Wikimedia API. The live path is tested with HTTP fixtures, and the
reviewed catalogue is available independently. No paid generation, accounts,
subscriptions, API keys or voiceover were used.

MediaWiki reference: [Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)
and [Videoinfo](https://www.mediawiki.org/wiki/Extension:TimedMediaHandler/API).
Source records for the reviewed clips are bundled in
`backend/app/data/discovery-seeds.json` and described in [MIXED_SAMPLE.md](MIXED_SAMPLE.md).

## Expanded Florida local bank

[Footage bank](FOOTAGE_BANK.md) documents seven new official archival recordings, six existing location-reviewed stock recordings, and a checksum-validated importer. The curated bank is separate from live discovery seeds; it does not widen the remote downloader allowlist. Its licensed Miami Shores YouTube candidate remains pending download and is not counted as usable footage.
