# Phase 2: Weather intelligence

The weather pipeline now performs live ingestion, source normalization, event grouping, change detection, prioritization, field/provenance verification, and durable automated polling. It operates independently of the still-unimplemented rendering and broadcast pipelines.

## Sources and retained evidence

- NWS: `https://api.weather.gov/alerts/active`, with validated pagination restricted to the same official endpoint.
- NHC: `https://www.nhc.noaa.gov/index-at.xml`. Public advisory descriptions contain the actual bulletin text, including intermediate advisories, observations, movement, watches/warnings, and forecast wording.
- NHC archive imports/fetches continue to work at the contract level. The tested Milton archive URL is denied by CloudFront in this instance; no successful historical archive fetch is claimed.
- GOES imagery, GIS cone processing, and radar visualization belong to the visual-engine phase. This milestone invents no tracks or observations.

Advisories retain original issue/expiry times, source references, full original provider payloads, normalized facts, and SHA-256 evidence checksums. The cache retains the latest official HTTP response per URL with its conditional validators. A 304 response reuses checksum-validated evidence and updates the source-check time, never the observation's issue time.

Official responses captured on 2026-10-08 are stored in `backend/tests/fixtures/`. Each NHC RSS file is an unmodified full response, covering advisories 5A and 6 of the same storm. The NWS file is a subset of unmodified complete alert features; the reduced wrapper is declared in `provenance.json`. Their hashes are checked in tests. These captured snapshots are not replayed as current live weather in the app. Separate synthetic fixtures test edge cases and remain labeled training material.

## Collection and polling

Each provider has an owned asynchronous worker. Enabled state, interval (60–3600 seconds), due time, last attempt/success, failure count, and collection totals persist in SQLite. Defaults are paused. Enabling schedules an immediate first check; restarting resumes a saved enabled schedule. Pausing stops future checks and lets a running collection finish.

Manual and scheduled refreshes share the same in-flight task per provider, so overlapping requests do not duplicate collection work. Transient connection failures and HTTP 429/5xx responses receive bounded retries; access denials do not retry unchanged. Consecutive failures increase polling delay up to one hour. Shutdown cancels owned workers and records interrupted jobs.

HTTPS trust stays enabled, redirects are refused, and decompressed response size is limited to 8 MB per page. NWS pagination is limited to 20 pages and checked for cycles/unapproved destinations. Incomplete paginated collections do not replace active membership or admit partial new records. One malformed alert is quarantined without discarding other valid alerts in a complete response. Immutable ID/content conflicts are retained in quarantine instead of overwriting evidence.

Recovered source evidence resolves earlier quarantine entries by official identity/source URL. The original rejected payload and its first/last observation times are retained, with a resolution timestamp; resolved entries leave the active review list. Recurring failures reopen the corresponding entry.

## Event changes and verification

NWS CAP references link alert/update/cancellation versions, including predecessors arriving out of order. Unrelated alerts are not merged merely because their title or county matches. NHC versions group by official storm ID. Source timelines preserve chronological issue times and original references.

Only the latest unambiguous operational evidence can be current. An alert absent from a completed active refresh becomes `not_active`; a replaced record is `superseded`; cancellations/test messages are non-operational. A failed or old source check yields `stale_feed`. NWS validity follows its official expiry rather than a six-hour issue-age cutoff. NHC keeps its six-hour issue-age limit. The maximum feed-check age is the greater of 15 minutes and three configured polling intervals.

`What changed?` covers measurements, warning summaries, forecast wording, CAP severity/area/certainty/urgency, and source instructions. Full text comparisons retain context. Comparisons involving manual/training evidence are explicitly unverified and cannot pass source-grounded script review.

Editorial priority is deterministic: official NWS CAP severity (or clearly described editorial thresholds from NHC's reported wind), recency, US alert relevance/watch coverage, official certainty/urgency, and changes between officially fetched versions. Restricted evidence scores zero. This is a newsroom ranking, not an invented forecast or emergency risk scale.

Verification checks distinguish official retrieval, timezone-aware issue times, operational status, source freshness, and latest unambiguous version. Source/field verification does not establish the correctness of every meteorological claim. Named human review remains required, and no script is broadcast eligible.

Event projections are stored for subsequent newsroom work; current API statuses are recomputed against time and feed state rather than trusting a stale stored priority. Original advisory evidence remains immutable.

## Validation evidence

The live API refresh stored **397 valid NWS records and one NHC public advisory** in the first Phase 2 check. One NWS alert lacked its description and was quarantined. The repeated refresh inserted zero duplicate records; NHC returned a successful HTTP conditional-cache revalidation. Counts change as the real feeds change and are not an acceptance constant.

A subsequent live background poll collected NHC advisory **6**, following stored advisory **5A**. The API and browser verified actual official changes: wind **65 → 70 mph**, central pressure **994 → 988 mb**, latitude **22.8 → 22.9**, longitude **−92.4 → −91.9**, and upgraded watches/warnings. The earlier version became superseded. A source-linked draft carried both original timestamps and references and remained ineligible for broadcast. The parser supports the padded advisory-number format used by regular bulletins; both captured official versions form a regression test.

Validation completed with **53 backend tests**, **3 Chromium workflow tests**, and a strict TypeScript/production UI build. Real source collection and the actual background worker were checked separately from mock HTTP tests. Restart recovery retains the database, source schedules, caches, and evidence, and the services restart from the documented commands.

Automated coverage includes source fixture integrity, NHC measurement/warning/forecast extraction, CAP update/cancel grouping, disappeared alerts, long-duration validity, stale feed review blocking, quarantine, duplicate/conflicting evidence, source priority, cached response integrity, pagination, overlapping refresh coalescing, worker restart recovery, and polling persistence. Browser coverage exercises the source controls, search/provider/version filters, evidence verification/timeline, paused schedule persistence, drafting, and review blocking.

Limitations: no NWS reference backfill before the first collection; unseen earlier versions cannot be compared. Geographic ranking currently uses official NWS US coverage and NHC watch presence rather than polygon-level impact modeling. Historical archive access, native Electron lifecycle, Windows/macOS installers, advanced scripting, TTS, visual rendering, and OBS are not claimed complete.
