# Phase 3 — AI newsroom

Phase 3 connects the official weather evidence desk to six recorded newsroom roles, editable script revisions, paragraph-level source tracking and named editorial review. It does not produce audio, render a video, or start broadcasting.

## A recorded run

The Newsroom page accepts a stored advisory, writer engine and an optional refresh of that advisory's official provider. The selected evidence remains fixed: if refresh discovers a newer advisory, the selected older evidence is labeled superseded rather than silently replaced. Select the newer evidence for a current-news draft.

Each role has a versioned Pydantic JSON output and persisted input/output, timestamps and status:

| Role | Output |
|---|---|
| Weather data collector | Immutable selected/previous advisories, original provider payloads, feed health and optional refresh result |
| Change detector | Linked predecessor, comparison provenance and field differences |
| News prioritizer | Event identity, deterministic priority score/tier and reasons |
| Fact verifier | Source/time/validity checks and an ID/URL/time/checksum evidence manifest |
| Scriptwriter | Source-backed English narration, paragraph claims and estimated timing |
| Editorial quality controller | Claim coverage, source restrictions, fixed opening context, repetition/timing/uncertainty notes and review gate |

The collector reads existing persisted evidence by default. It does not pretend to perform a network request. Runs and stage failures persist; interrupted runs/stages become failed on startup. A script and successful run completion are committed together only after all six stages complete. A failed model/source request produces no partial script and no silent engine fallback. Provider error messages are sanitized before storage to avoid copying credential-bearing request information.

The local writer includes source attribution, measurements/location, linked advisory changes, original official forecast wording and watch/warning coverage when present. Missing forecast information is stated explicitly. NWS instructions remain available in the preserved source text. Narration never infers a future track from an observed position or claims a meteorological cause from a pressure change. Timing is an estimate at 145 words/minute; it is not measured audio.

## Script versions and claims

Every script starts at revision 1. The editor requires an editor name, revision note and the expected current revision for each text save. The backend uses an immediate SQLite transaction to prevent concurrent stale writes. A conflict returns HTTP 409 and leaves both the stored revision and unsaved UI text intact. Selecting an older revision displays its exact immutable text; editing/approval controls are available only for the latest revision. Scene CSV exports accept an explicit revision and use that revision's narration.

Each paragraph has a stable text-derived claim ID and source references:

- `generated_grounded`: a deterministic source-backed narration block. This is not a claim that a model independently proved the weather.
- `source_quote`: an exact quotation found in the preserved evidence (whitespace normalized).
- `requires_verification`: new or edited prose that lacks support. It blocks editorial approval.
- `human_attested`: a named reviewer supplied an exact supporting source quote and explained why it supports the paragraph. Recording support creates another immutable revision and clears editorial approval.

An attestation may cite only an advisory already in the script's evidence package. The quote must occur in that preserved source text, and all numerical values in the edited paragraph must occur in the quote. These checks do not prove the meaning, units, attribution, temporal context or forecast certainty of arbitrary prose. The named reviewer is responsible for those judgments; the UI states this limit. Editing an attested paragraph clears its support, while an unchanged paragraph retains it. Unsupported numerical values cannot be approved using an unrelated quote.

The opening provenance/freshness context must remain intact. Historical, training, unverified, expired, cancelled, withdrawn, stale-feed, superseded and conflicting evidence remains blocked. Comparisons also require official prior evidence. Every approval belongs to an exact revision and evidence manifest. Edits clear approval; subsequent source updates, source expiry or failed freshness checks invalidate it while preserving its audit record. High-impact information is flagged for careful human review. All drafts require a named human editor and remain `broadcast_eligible=false` after approval.

## Optional model composition

The grounded local writer is the default and requires neither a model nor an API key. No model assets are installed by Phase 3.

The optional Ollama and Gemini adapters accept a JSON response containing only an `order` array of existing block IDs. Every block must appear exactly once, and the opening/closing context must stay fixed. Extra prose, unknown IDs, omitted blocks and duplicates are rejected. Models cannot write or modify meteorological claims. This intentionally limits model assistance to the composition of vetted narration; free-form AI weather prose remains outside the verified contract.

- Ollama: run your existing local server on `http://127.0.0.1:11434` and set `WETHA_OLLAMA_MODEL` to an installed model name. Requests stay on loopback and bypass the external proxy. There is no arbitrary model endpoint input.
- Gemini: set `WETHA_GEMINI_MODEL` to a supported model identifier and supply `WETHA_GEMINI_API_KEY` through secure runtime configuration. Allow `generativelanguage.googleapis.com` in the environment's network settings if using the remote adapter. A remotely selected run sends source-backed narration blocks to that service. Credentials are sent in a header, never saved in run documents or source manifests. No credentials are requested or required for the default workflow.

Configured status means configuration is present, not that the model service was tested. Both adapters have mocked protocol/constraint/error tests. No real Ollama or Gemini service was available in this instance; real model integration remains unverified. TLS checks and redirect restrictions remain enabled for remote requests. Model responses are bounded to 256 KB and requests time out after 45 seconds.

## API additions

| Endpoint | Behavior |
|---|---|
| `GET /api/newsroom` | Recent runs and writer configuration status |
| `POST /api/newsroom/runs` | Execute six roles and return a draft; legacy `POST /api/scripts` uses the same pipeline |
| `GET /api/newsroom/runs/{id}` | Recorded JSON handoffs and stage status |
| `GET /api/scripts/{id}?revision=N` | Exact saved revision with current evidence/review evaluation |
| `POST /api/scripts/{id}/revisions` | Save text with expected revision, editor and note |
| `POST /api/scripts/{id}/claims/support` | Save a named quote/explanation attestation as another revision |
| `POST /api/scripts/{id}/review` | Approve the latest supported current-source revision by name |
| `GET /api/scripts/{id}/scenes.csv?revision=N` | Export that revision's aligned scene text and claim IDs |

Migration 004 adds newsroom runs, agent steps, immutable script versions and review audit records. Existing scripts are preserved as revision 1. They acquire conservative source/claim tracking when read; pre-Phase 3 review metadata remains in the preserved original document and does not automatically establish Phase 3 approval. Only one backend process per local database is supported.

## Validation

Run `npm test`, `npm run build`, and `WETHA_CHROMIUM=/usr/bin/chromium npm run test:ui` from the repo root. Browser tests use their own temporary database and own both server ports. Captured official NHC responses prove exact forecast retention and real 5A→6 measurement comparisons; synthetic cases explicitly cover revision conflicts, unsupported claims, source attestations, review invalidation, engine failures and restart recovery.

Validated in this cloud instance:

- **74 backend tests** passed, including legacy-database upgrade, optimistic revision conflicts, quote/numeric support, review invalidation, model constraints/redaction, requested-refresh failure and source updates during model composition.
- **5 Chromium browser workflows** passed, covering evidence-to-script, module state, polling/timeline, six-role handoffs and revision history, and named source attestations that remain training-only.
- Strict TypeScript checking and the production Vite build passed.
- A fresh real refresh collected **402 NWS records and one NHC bulletin** with no rejected records in that refresh. Counts change as official feeds update.
- A real NHC advisory 6 draft completed all six roles, retained both official source checksums and timestamps, and included the actual 5A→6 comparison (+5 mph wind, −6 mb pressure) with original forecast wording. It contained seven supported narration paragraphs with **226 seconds estimated** timing. It remained unapproved and ineligible for broadcast.
- A Chromium check against the actual-data workspace verified all six handoffs, advisory comparisons, original forecast wording, revision selection and responsive layout.

A graceful stop released both owned service ports. Restart preserved 501 advisory records, original script text/revisions, the completed six-stage run, feed preferences and the built renderer. Synthetic test databases separately verified multi-revision approvals and interrupted-run recovery. Historical NHC archive-page 403 and native Electron sandbox/runtime limitations from Phase 2 remain. Phase 4 is the geographic and cinematic visual engine; voices, media, FFmpeg production and broadcasting follow later.
