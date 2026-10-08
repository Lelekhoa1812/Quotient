# Quotient hardening ledger

Living record of the UX, evidence-integrity and reliability work. Status words are used strictly:
**verified** = reproduced before and checked after in the running app or by a test that fails without the fix;
**implemented** = changed and covered by a test or typecheck, not yet exercised end to end;
**open** = known, not fixed; **blocked** = needs a decision or a dependency.

Baseline: branch `main`, HEAD `20b8c7c`, plus ~50 uncommitted working-tree files from earlier work (treated as authoritative; nothing was reverted).
Local topology: portal `:3000` (Next dev), MCP API `:8080` (uvicorn, in-process worker port), MinIO container `engine-minio-1` `:9000`, bucket `axion-meeting-local`, ledger `.local/run/meetings.json`. Worker reads media from `derivatives/<object_key>` on disk and uploads a playback copy to MinIO.

## Verified baseline (before changes)

| # | Finding | Evidence | Source |
|---|---|---|---|
| B1 | The "black screen" is the fixture: `derivatives/local-synthetic-20m.mp4` is 160x90, 1 fps, every frame luma 0. All 5 local meetings used it. Playback itself works (206 Range, CORS, faststart, `readyState` 4, seeks). | ffprobe + decode of all 1200 frames; `<video>` state in the real browser; curl Range/CORS | observed |
| B2 | The player stretched any video into a ~967x218 box and remounted (losing position) on every `reload()`. | DOM measure; code `player.tsx` | observed |
| B3 | A run died after ~40 min of model work: `SchemaRejected: 'origin' was unexpected`. The fallback action draft added `origin`, which the shipped action schema forbids. Tests passed because the test fixture contracts allow `origin` (fixture drift). | `.local/run/meetings.json` failure_message; schema read | observed |
| B4 | The coverage and supplement stages were sent `span_ids`, but their contracts name other inputs, and nothing enforces `input.include`. The model could not see what it was asked to compare, so coverage never closed and `ready` was unreachable. | prompt yaml vs `quality.py`; 0 omissions across 3 ledgers | observed |
| B5 | A lens that fails or times out was stored as `none_in_transcript`. The API also reports `none_in_transcript` for any dimension without a *published* finding, so held findings read as "absent". | `quality.py`, `gate.py`; kSGSi: 38 supported commitment claims, commitment = none | observed |
| B6 | One failed extraction window ended extraction for the rest of the meeting; entailment ran on claims with no resolvable quote (~700 wasted calls/run). | `quality.py` | repository-confirmed |
| B7 | UI leaked internals: `none_in_transcript`, raw `decision_status`/stance/dimension, "Pegasus/Sonic", seam/coarse badges, speaker-hypothesis table, aggregation enums, "graph page", worker error text. 4 of 7 stored charts were hidden, seek buttons never rendered, durations were raw ms. | component audit + live DOM | observed |
| B8 | The Brief tab flashed "no brief" during load; the page had no loading state. | live capture | observed |
| B9 | There is no way to resolve a review item; copy implied one. | no MCP tool; UI copy | repository-confirmed |
| B10 | Local storage: 20 orphaned per-meeting uploads (265 MiB); no retention code anywhere. | bucket vs ledger diff | observed |
| B12 | The real 1280x720 recording (`derivatives/meeting-20m.mp4`) never completes: Sonic transcription is rejected at ~15 min with `validationException ... blocked by our content filters` (reproduced in 2 runs, 2026-10-08, task glKjhun4...). One rejected 6-minute segment failed the whole meeting and discarded the segments already transcribed. Cause of the filter itself: **unknown** (provider-side; audio of segment 3, 12:00-18:00). | `.local/run/bench-real20m-a.log` | observed |
| B13 | The MIT 18.06 slice (real content, 480x352) also fails in Sonic: `validationException: Invalid input request` at ~730 s, i.e. the 6-minute handoff into the third session (earlier meeting `OTixu4...` failed the same way). Ruled out by controlled probes (short silent sessions, same transport): history size (0, 5, 40, 120, 366 items, 12 KB), history as one blob. Not valid evidence: unpaced 60 s windows, which time out on TLS write (a flooding artifact, different error). Cause: **unknown**; paced Sonic-only reruns are in progress. | `scripts` probes in the session scratchpad | observed |
| B14 | **Real recordings were unplayable** (distinct from the black fixture): in local MinIO mode the worker uploads a playback copy to `derivatives/<meeting_id>-0.mp4`, but `media_url` signed the submitted `object_key`, which is only in the bucket if hand-uploaded (true for the synthetic fixture). Browser: `MEDIA_ERR_SRC_NOT_SUPPORTED`, HEAD 403 for `/axion-meeting-local/derivatives/meeting-20m.mp4`. | live browser on meeting `Miwaj8Ynp7EBtyZd` | observed |
| B15 | **Sonic transport bug**: the socket is non-blocking but all four writes used `sendall()`, which raises `SSLWantWriteError` when the send buffer is momentarily full. Two concurrent streams failed sessions with it (and with "send window did not open"). Earlier I mislabelled this as a flooding artifact; it is an application bug. | `wire.py:532`; failures in api.log | observed |
| B16 | Content-filter rejection of one segment is **deterministic** (same 6-minute audio, rejected twice with different leading errors); retrying it only wastes minutes. | diagnostic run, 2026-10-08 | observed |
| B17 | **Tool-declaring prompts were never executed.** All ten evidence lenses and the coverage supplement declare an `open_span` tool. The reasoner answers such a prompt with a tool call and an empty output; the callers read `{}` as a real answer. Lens: empty -> `none_in_transcript` (a false "nothing in the transcript"). Supplement: `answered 0, claims 0, omissions 0` on every batch, so coverage never closed. | api.log `coverage supplement batch N: ... answered 0`; direct lens probe returned `output {}` + 6 tool calls | observed |
| B18 | The lens payload gave the model no span ids although the contracts require `owner_span_id` / `agreement_span_id` / `due_span_id`; the commitment lens opened **claim ids** instead. | direct probe: `open_span('claim-0-5')` | observed |
| B11 | Gate semantic: meeting is `ready` only if zero held claims, full coverage, no gaps. 0/3 claim-bearing ledgers passed; held share was 83%. Policy is a documented partner contract (`MCP.md`). | ledger counts | observed |

## Changes (all in working tree, uncommitted)

### Backend / worker
- `apps/worker/loop/quality.py`: fallback action no longer sends `origin` unless the loaded schema declares it, and a rejected draft is skipped, not fatal (**verified**: new test runs against shipped contracts). Coverage stage rewritten: code-derived uncovered set is authoritative, contract-shaped payloads, 20-span supplement batches with unique claim ids (**implemented**, test `test_coverage_and_supplement_payloads_match_their_contracts`). Extraction continues after a failed window and stops after 3 consecutive failures; entailment skipped when no span contains the quote (**implemented**, tests). Lens failure returns `not_evaluated` (**implemented**, test).
- `apps/worker/sonic/client.py`: a rejected transcription segment is retried once on a fresh session (partial text dropped), then recorded as an `untranscribed` span; the quality loop turns it into a coverage gap, so the meeting finishes in review with the missing part named instead of failing (**implemented**, 2 tests; **not yet exercised against the live service**: the API must be restarted to load it, and a restart would have discarded the benchmark running at the time). The portal shows "Not transcribed" in the transcript and the To check list.
- `apps/worker/bedrock/wire.py`: writes wait for socket writability (`_send_all`), 2 tests. `apps/worker/sonic/client.py`: a segment rejected by the content filter is re-run in 90 s windows so only the rejected window is lost; per-session failures are logged. `apps/worker/quotient/port.py`: local playback signs the per-meeting upload when present (3 tests). **All three implemented and unit-tested; live verification pending the next restart** (restarting would have discarded in-flight runs).
- `apps/worker/graph/lenses.py`, `publish.py`, `quotient/port.py`, `apps/api/quotient/worker/memory.py`: `not_evaluated` dimension state persisted; blocks `ready`.
- `apps/api/quotient/graph/gate.py`: dimension rows carry `state` (`findings` | `none_in_transcript` | `not_evaluated`) and `held_findings` on none rows; any `not_evaluated` lens blocks `ready` (**implemented**, 2 API tests). **Contract change is additive**; `withheld` semantics and `MCP.md` are unchanged.
- `scripts/bench_meeting.py`: reusable benchmark harness (submit, poll, record graph + summary).

### Portal (`apps/web`)
- New presentation layer `lib/present.ts` (one map per contract enum; unknown values fall back to neutral wording, never the raw code) and `lib/insights.ts` (charts derived only from stored entities). 13 unit tests (`npm test`).
- Rewritten: Brief (partial-brief notice, evidence on click), Key points (topic tabs, "Not mentioned in the video" only when the lens looked and found nothing; otherwise "N points not yet confirmed" / "could not be analysed"), Transcript (one searchable conversation, original wording on demand, corrections report real failures), To check (grouped by reason, repeats merged), Insights (4-5 purpose-built charts with table views), Status (plain steps, confirmed stop), Downloads, evidence panel (only when something is selected).
- Player: aspect ratio fixed; a recording with no picture plays in a native audio control with an explanation (**verified** in the browser on the black fixture); no remount on reload.
- Removed from ordinary view: timeline strip with seam/coarse markers, speaker-hypothesis table, raw/synthesized dual panes, aggregation names, worker ids. Underlying data and exports are untouched.
- Smaller fixes: loading states, "Remove from list" confirmation, home list no longer drops rows past 20, settings and navigation wording.

### Local storage (approved by the user)
- Deleted 20 orphan objects (264.96 MiB) from `axion-meeting-local` by explicit key, and 16 regenerable scratch files (~70 MB) under `.local/run` and `derivatives`. Ledger backed up as `.local/run/meetings.json.bak-*`. Bucket 41 -> 21 objects. Other buckets and containers untouched.

## Test evidence
- `.venv/bin/python -m pytest tests/worker -q` -> 83 passed (was 78)
- `tests/api` -> 30 passed (was 28), `tests/contracts` -> 11, `tests/jev` -> 21 (run each directory separately; the two `conftest.py` files collide when combined)
- `cd apps/web && npm test` -> 13 passed; `npx tsc --noEmit` -> clean

## Round 2: pressure testing (adversarial reviews, failure injection, rubric evaluation)

Method: two independent read-only reviewers (security/robustness; correctness of the round-1 changes), a rubric-based evaluator (reads the full transcripts against the Briefs), live failure injection on the running pipeline, and browser audits. Each finding was verified before fixing; two reviewer claims were wrong and are not acted on (the ledger file is already mode 600; `ReportFindings` was not needed).

### Defects found and fixed (all with tests; "live" = also verified in the running app)
| # | Defect | Fix |
|---|---|---|
| R1 | **CSRF on `/api/settings`**: any web page could POST text/plain to 127.0.0.1:3000 and rewrite `.env` (the model credentials). Confirmed live (HTTP 200 from a foreign Origin). | Same-origin + `application/json` required; now 403 (live). Only the two keys the worker reads are writable. |
| R2 | **Cross-tenant replay**: checkpoint store keyed by the raw client idempotency key in a process-wide store; two subjects with the same key shared one analysis. | Key scoped by subject. |
| R3 | **Auth bypass failed open** when `QUOTIENT_ENVIRONMENT` was unset or misspelled. | Env flag honoured only when the environment is exactly `local`. |
| R4 | Misconfiguration hidden: my Sonic recovery treated `NotInvocable` and HTTP 401/403 as "not transcribed". | Permanent failures fail the meeting; all-windows-rejected fails the meeting. |
| R5 | Cancel did not stop spending (Sonic stream and ~1,500 model calls continued). | Stop signal through ingest, Sonic frames and the quality budget. **Live:** cancelled meeting stayed cancelled, 0 further calls. |
| R6 | Restart re-ran every unfinished meeting forever. | Resume capped at 2. **Live:** a meeting killed mid-run resumed and finished. |
| R7 | Failure messages leaked local paths and `ffprobe` command lines; "no audio track" read as "unreadable". | Plain sentences; raw detail goes to the log only; `NoAudioTrack`; legacy rows masked at the API. |
| R8 | ffmpeg/ffprobe/aws calls had no timeouts; failed silence detection read as "all speech". | Timeouts; fail closed. |
| R9 | **Activity chart counted silence and untranscribed windows as speech** (276 silence spans per run). | Allowlist of transcribed speech. |
| R10 | **"Not mentioned in the video" asserted when statements were merely unconfirmed or audio was missing.** | Wording only when nothing is unconfirmed and nothing missing; otherwise "No confirmed points on this topic" + pointer to To check. |
| R11 | Actions marked **accepted** with no agreement span (the commitment lens contract says such a row stays proposed). 5 of 6 lecture "actions" were teaching moves. | Accepted requires owner span AND an agreement span in this meeting. |
| R12 | **False "contradicted" labels**: any counter-search quote condemned a claim, even a quote that supports it. | A contradiction needs a verbatim quote that does not itself entail the claim. |
| R13 | Lens failure after a provider error aborted the whole analysis. | Failure -> `not_evaluated`; missing model access still fails loudly. |
| R14 | Coverage stage and gate defined "covered" differently. | Same definition (the span a quote resolved to). A failed auditor call no longer skips the supplement. |
| R15 | The downloads for a meeting needing review (PDF, web page) were an empty "withheld" page although the portal showed 15 confirmed sentences. | Partial brief with a notice; MCP brief resource unchanged. |
| R16 | Caption cues overlapped (two captions on screen). | Cue ends cut at the next cue's start. |
| R17 | Actions showed a whole transcript line as "Owner". | Shows what was said and when, labelled as such. |
| R18 | Settings page edited model/region values the worker never reads. | Read-only, with an explanation. |
| R19 | Home list showed "Queued" for finished meetings while loading, used first-seen times, only looked up the 20 newest rows, and named every meeting "Untitled meeting". | Every row is looked up (newest first, in batches); no placeholder status; `get_meeting` returns `updated_at` and `source_name` (additive); verified live: 32 of 32 rows resolved, titles are file names. |
| R20 | Portal: seek reset on every tab change; clicks raced; failed edits reported success; a meeting opened mid-run never refreshed; invisible keyboard focus on the upload control; tab keyboard support; focus lost on closing the evidence panel; nested interactive Brief sentences; in-progress player said "could not be loaded". | Fixed individually; verified in the browser (arrow keys, focus, in-progress view). |
| R21 | Unbounded request bodies (buffered before the size check) and unbounded MCP sessions. | Bounded (413); session cap. |
| R22 | CSV export formula injection. | Cells starting `= + - @` are neutralised. |
| R24 | **Long runs lost all progress** on a failure; credential expiry mid-run was reported as a generic failure. | Credentials re-read once; actionable message; per-owner transcript cache (implemented, unit-tested, not yet live-verified). |
| R23 | Question/gap topics said things "remain unanswered" that later parts of the recording answered. | Topic renamed "Questions raised"; Brief sentences resting only on those topics carry a note. Prompt change pending (below). |

Tests added or hardened this round: 118 worker (was 95), 38 API (was 30), 21 web (was 14). Three tests that passed vacuously were rewritten so they fail without their fix.

### Independent rubric evaluation (scores 1-5, by an evaluator who read the full transcripts)
| Criterion | Sales call | Lecture |
|---|---|---|
| Faithfulness of Brief and findings | 2 | 2 |
| Citation accuracy (15 claims) | 4 (14/15) | 4 (15/15) |
| Completeness (recall of the 7-8 key points) | 1 (about 1.5/8) | 1 (about 1.5/7) |
| Usefulness to someone who did not attend | 1 | 1 |
| Actions | 2 | 1 |

**Reading this honestly:** the evidence layer is sound (every cited quote, 243 of 243, appears verbatim in its span) but the *selection and framing* layer is weak. The Brief is built from the 19-58 confirmed claims; most substantive content (for example "about 1,000 orders a day", "pivots 1, 2 and 5", "determinant is 10") sits in the 63-69 claims that end "unresolved". Findings of type question/gap assert "unanswered" without seeing the later answer. A reader would not learn what either recording was about. The score for faithfulness would be higher with R11, R12 and R23 in place; this has not been re-measured.

### Soak test: the user's 84-minute recording (`src/meeting.mp4`, 14 segments)
| Result | Evidence |
|---|---|
| **Failed at 54 minutes** (3,272 s) with `sonic HTTP 403` | `.local/run/bench-long84.log`; `aws sts get-caller-identity` returned `ExpiredToken` at 10:29Z. The AWS session on this machine lapsed mid-run; `export-credentials` still advertised a later expiry, so the app's refresh margin did not help. |
| 7 of 14 segments had completed; two needed recovery | segment 2 content-filtered (only the 90 s window 900-990 s lost, as before); segments 5 and 7 hit a transient `Invalid input request` and recovered on retry |
| All 54 minutes of finished transcription were discarded | results were kept only when the whole analysis completed |
Consequences implemented: credentials are re-read once on 401/403 and the failure message says to sign in again; finished segments are cached per owner and audio so a retry streams only the missing ones (`sonic/cache.py`, 3 tests, not yet live-verified). **Blocked:** no further live Sonic run is possible until the AWS sign-in on this machine is renewed; this is outside the app and outside what I may do (it is a credential). The 84-minute analysis (Brief and UI at scale) therefore has **not** completed once.

### What this round did not fix (open, with the evidence)
1. **Completeness.** Roughly half of all claims end "unresolved"/"gap". The rules that decide this are strict (both models must agree; the set of spans the counter-search reports must equal the set opened; the quote must sit in one span). Claim rows now persist the verdict (`sol`, `luna`, search/open match, quote resolved) so the cause can be measured on the next run instead of guessed. Loosening any of them is a threshold decision for the owner, not something to change unmeasured.
2. **Educational content** (no concept summary; teaching moves read as commitments). Needs a content-type aware mode. Not started.
3. **Prompt wording** for the question and gap lenses ("open question", "unresolved") and the synthesis step. Edited after the 84-minute soak so the running analysis is not contaminated.
4. Speaker attribution is absent on every run; every line reads "Unnamed speaker".
5. The JWKS fetch blocks the event loop on an outage; the brief.html loads mermaid from a CDN without SRI; the Mermaid sanitiser is hand-rolled. Not local-development issues; recorded for release.

## Completion gates (strict status)
| Gate | Status | Evidence / reason |
|---|---|---|
| Black-screen video fixed and verified in the running frontend | **met** | Real 1280x720 recording plays and seeks (5:00 and 18:26 checked) in the portal; picture-less recording plays as audio with a note. Two separate causes: black fixture, and a missing playback object. |
| No unnecessary engineering instrumentation or raw machine terms | **met for the meeting workspace** | Presentation layer + code sweep; 13 unit tests. The Assistants (MCP connection) page still shows connection headers by design. |
| Layout and interactions validated | **partly met** | Browser-checked at desktop and 375 px (no overflow), evidence navigation, empty/loading states. No automated accessibility audit and no keyboard-only walkthrough was run. |
| Charts communicate real validated data | **met** | Derived only from stored entities, table alternative, tests; verified on the 20-minute meeting data. Not verified with multi-speaker data (no run had speaker attribution). |
| Brief is meaningful, traceable and handles unsupported conclusions | **partly met** | Real meeting: grounded and traceable (click -> exact quote and time, verified). Lecture: not meaningful as a summary of the concept; spurious "commitments"; some model-suggested actions are auto-accepted when an owner span resolves. |
| Local processing succeeds through the configured storage and workers | **met** | 5 full runs of each recording through MinIO, worker port and portal; last two completed. |
| Critical regressions, failure conditions and evidence-integrity checks pass | **partly met** | 95 worker, 30 API, 11 contract, 21 jev, 13 web tests pass; 0 citation mismatches in about 730 citations across runs. Silence, unavailable-media and interrupted-processing cases are unit-tested, not executed end to end. |
| Acceptance thresholds met with reproducible evidence | **not met** | No thresholds were authorised or set. Meetings still end `needs_review` (coverage incomplete). |
| No release-blocking defect | **not met** | See Open below: deterministic content-filter rejection loses audio, review items cannot be resolved, ~12% of speech spans remain unaccounted for, scenarios C/D/E not run. |

**Conclusion: not declared commercially ready.**

## Open / blocked
- Content-filter rejection of one 90 s window of the real recording (900-990 s) is deterministic and cannot be recovered; it is named as "Not transcribed". Cause is on the provider side.
- 11-13% of speech spans end with no claim, gap or omission; the supplement answers every batch but not every span, and the API and worker still define coverage differently.
- Auto-accepted model actions: an action with a resolved owner span is stored `accepted` without a person; the UI now says "Owner stated in the recording" for those. Whether that should stay `proposed` is a product decision.
- Speaker attribution is absent on all runs (0 spans attributed), so every line reads "Unnamed speaker".
- No automated accessibility audit; no keyboard-only walkthrough.
- Review items cannot be resolved by a person (no tool). Product decision needed before building one.
- Quote resolution requires a single span; 84% of Sonic spans end mid-sentence, so many claims lose their citation. Fixing this changes the citation model; deferred pending real-content numbers.
- `numeric_failed` is never produced by the worker; `gap` is collapsed into `unresolved` by the API.
- Cancel does not stop in-flight model calls; restart re-runs all queued/working rows from scratch.
- The Assistants page (formerly "MCP") still shows connection headers; it is an integration screen by design.

## Benchmark results
### Scenario A: real meeting recording (`derivatives/meeting-20m.mp4`, 1280x720, 20:00)
| Run | Code | Outcome |
|---|---|---|
| a (04:53Z) | before recovery | **failed** at 940 s in transcription (content filter); whole meeting lost |
| b (05:16Z) | session retry only; two streams concurrent | completed `needs_review` in 23 min. 419 spans (141 speech, 276 silence, 2 untranscribed = 12 of 20 min lost to the transport bug + content filter), 43 claims (19 confirmed, 24 not yet confirmed), 42 citations, **0 offset or verbatim mismatches**, 12 findings, 7 brief sentences, 1 action, 30 coverage gaps (72 spans), 33 speech spans with neither citation, gap nor omission |
Content: a software-vendor sales call. Brief sentences are grounded (spot-checked against spans); thin because 60% of the audio was not transcribed.

### Scenario B: educational lecture (MIT 18.06 L2, Strang, 20-min slice from 3:00; source archive.org/details/MIT18.06S05_MP4, CC BY-NC-SA)
| Run | Outcome |
|---|---|
| first (04:09Z) | failed at ~12 min (`Invalid input request`, transient provider error at a handoff) |
| second (04:53Z, concurrent with A-b) | completed `needs_review`. 218 speech spans, 1 untranscribed segment (360-720 s, transport bug), 82 claims (36 confirmed, 38 gap, 7 unresolved, 1 contradicted), 78 citations, **0 mismatches**, 10 findings, 8 brief sentences, 4 actions |
Transcript fidelity vs the OCW captions (ground truth is itself imperfect): **on the transcribed portion WER 0.16, word recall 0.92, precision 0.87** (1,652 reference words). Whole slice: WER 0.43 / recall 0.66, dominated by the lost segment.
**Intelligence-quality finding (observed):** the Brief for the lecture is a list of "Progress" and "Question raised" lines ("What is the multiplier?"). It does not state the concept being taught (elimination via matrices). The ten lenses are meeting-oriented (decisions, commitments, risks); nothing summarises explanatory content. This is a product gap for educational content, not a transcription gap. No change made (new analysis capability = scope decision).

### Scenarios C, D, E
Not run. Only scenario B was approved for download; the candidates are recorded here for a later decision: C1 CC/Berkman "The Commons" panel (archive.org/details/CC-BerkmanPanel.m4v, 351 MB, CC BY), C2 US v. Skrmetti oral argument (supremecourt.gov, audio + transcript), D1 2007 NCLB joint hearing (archive.org/details/house.hbs.mars.hrs06ED_W2175_070313, 1.07 GB, uploader's public-domain claim). The silent-period and unavailable-media failure cases are covered by unit tests only, not executed runs.

### Iteration table (same two recordings, both runs concurrent each time)
| Run (code) | Real meeting: speech spans / untranscribed / claims (confirmed) / brief / omissions | Lecture: speech spans / untranscribed / claims (confirmed) / brief / omissions |
|---|---|---|
| b/2nd (session retry only) | 141 / 12 min / 43 (19) / 7 / 0 | 218 / 6 min / 82 (36) / 8 / 0 |
| c/3rd (+ transport fix, 90 s window recovery) | 310 / 90 s / 110 (43) / 13 / 0 | 315 / 0 / 96 (34) / 7 / 0 |
| d/4th (+ tool executor for lenses and supplement) | 312 / 90 s / 127 (54) / 12 / 32 | 313 / 0 / 127 (54) / 7 / 15 |
Run d: supplement `asked 20, answered 20, claims 9, omissions 11` per batch (was `answered 0`). Commitment lens (and Stakeholder on the real meeting) reported `not_evaluated` (honest) because the model opened claim ids (B18). 0 citation mismatches in every run (about 490 citations in total).
| e/5th (+ lens payload carries span ids, claim ids resolve to spans) | 313 / 90 s / 126 (56) / 15 / 31 | 315 / 0 / 123 (58) / 13 / 34 |
Run e: **all ten dimensions evaluated** (none `not_evaluated`); Commitments and Stakeholders now return findings on the real meeting; findings 25 and 25; actions 5 and 6; 36 of 313 and 41 of 315 speech spans still have neither a citation, gap nor omission (11-13%); coverage still `incomplete`, so both stay `needs_review`. 0 offset mismatches in 243 citations. Elapsed 35 and 33 minutes.

**Speed:** the full pipeline took 23-38 minutes per 20-minute recording (transcription is paced in real time, about 6 minutes per segment, then roughly 1,500 model calls).
