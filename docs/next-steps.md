# Next steps (hand-over, 2026-10-09)

Read this first. [quality-ledger.md](quality-ledger.md) holds the full evidence; this file says what to do next.

## Where the walkaway stands
- **Not enterprise-grade yet.** Latest blind scores (Round 13, SBC meeting and sales call): completeness 3, usefulness 3, no 5. Actions improved on the SBC meeting (7 to 14 listed, 11 of 14 valid, none wrong); the sales call did not change.
- **Never completed:** the 84-minute soak. **Not re-run since round 11:** the lecture and the hearing.
- **Two prompt changes are in place and untested on the production model** (both digest prompts, `contracts/prompts/meeting.digest.v1.yaml` and `meeting.digest_review.v1.yaml`, bodies kept identical):
  1. The action-recall wording (a second pass for follow-ups plus precision guards). Measured live in Round 13.
  2. The "Claim check" paragraph. Only Haiku-proxy tested: faulty clauses with against without the check were 0 against 6 and 1 against 7 on the hearing (two independent pairs; the first count had a year my own prompt supplied), a wash on the sales call (7 against 7 over two pairs: 2 against 4, then 5 against 3), and 2 against 4 and 0 against 4 on the SBC meeting (two pairs; the second also showed higher action recall, 13 of 17 against 11, and decisions matched 13 of 14 against 10), with completeness level; on the lecture it was a wash across two pairs (2 faults against 2) after a first wording that over-hedged a confirmed result was fixed. **Its live effect is unmeasured.**

## What is blocking
The AWS account's budget hard cap is active. `BedrockBudgetHardCapDeny` is attached to the group `bedrockbudgetcap` (the IAM user is a member) and denies every Bedrock invoke action. Every pipeline run fails at the first model call with `sonic HTTP 403` (the portal text, "did not accept this computer's sign-in", is misleading). **Lifting it is the owner's decision** (raise the budget, or wait for the reset). Check it with:

```bash
aws iam list-attached-group-policies --group-name bedrockbudgetcap --no-cli-pager
```

When that returns no `BedrockBudgetHardCapDeny`, model calls work again.

## The confirming run (about 90 minutes, both recordings concurrently)
```bash
cd /Users/liamle/Downloads/Axion/meeting
# the stack must be up: ./scripts/stop-local.sh && ./scripts/start-local-minio.sh
nohup .venv/bin/python scripts/bench_meeting.py derivatives/meeting-20m.mp4 r15-sales > .local/run/bench-r15-sales.log 2>&1 &
nohup .venv/bin/python scripts/bench_meeting.py derivatives/sbc-checkpoint.mp4 r15-sbc  > .local/run/bench-r15-sbc.log 2>&1 &
```
Prompts are read per run, so no restart is needed after a prompt edit. `derivatives/sbc-checkpoint.mp4` is a scratch copy of the owner's SBC upload from local MinIO and can be deleted.

## How to score it (same method as Rounds 12 and 13, so numbers compare)
1. Build each recording's transcript and walkaway text with `scripts/build_eval_inputs.py` (it reads the API projection, so read-time filters are included, and prints an empty owner or decider as "(not stated)", the portal's meaning). Example: `/tmp/quotient-worker-venv/bin/python scripts/build_eval_inputs.py /tmp/eval sbc=<meeting id> sales=<meeting id>`. **Do not print an empty owner or decider as "unknown"**: my first formatter did, an evaluator scored that, and Round 13's attribution result was partly my error (see the correction in the ledger).
2. One blind Haiku evaluator per recording: it writes its own eight key points and an exhaustive action list from the transcript before opening the walkaway, classifies every listed action as valid, questionable or wrong, and scores faithfulness, completeness, usefulness, actions, attribution and noise from 1 to 5.
3. Compare with the Round 13 table in the ledger.

## Revert criteria for the claim-check paragraph
Remove it (the old text is in git history) if the confirming run shows summaries that are vaguer or shorter in a way that lowers completeness, or fewer valid actions than Round 13 (SBC 14 listed, 11 valid; sales 2).

## Open defects, in the order worth fixing
1. **Missed follow-ups on the sales call.** Soft vendor offers are excluded by design (running the demo is not an action); decide whether that is right for sales calls.
2. **Completeness stays at 3** on every recording: detail and some positions are missed. The lever is probably chapter and perspective coverage, not grounding. `scripts/audit_coverage.py` (no model) shows detail density falls with length: 6 to 8 items per ten minutes on the 55-minute meetings against 9 to 13.5 on the 20 to 25 minute ones, with the longest uncited stretch growing from about 1 to 3 minutes to 3.7. The summary is fixed at three to five sentences whatever the length. Leading hypothesis to test on the confirming run (ledger, "Where the walkaway is thin"): scale summary and chapter count with length, and keep it only if blind completeness rises without more faulty clauses.
3. **Diarizer errors** (one person split across ids, or two people merged) drive attribution and the empty "decided by" lines.
4. **A proposal nobody confirmed can show as a "tentative" decision** (1 to 2 per meeting). A stricter prompt rule and a code-side cap were both measured and rejected: each made recall or labels worse.
5. **Security and operations still open:** no per-user rate limit or upload quota, no script/connect CSP (needs the production hosts and a report-only trial), the converter has no memory limit, prompt-injection defence for context documents is soft, the ledger is one JSON file.
6. **Accessibility:** axe (full WCAG 2.2 and best-practice set) passes on every audited screen in light and dark, and a real-key keyboard pass is done on every screen and dialog (ledger: "Real keyboard traversal ..." onward; five focus-loss defects and a missing skip link were found and fixed). **Not done:** a screen-reader pass, the native file picker by keyboard, and saving a Settings value by keyboard; they need a person or an irreversible action.

## Do not do
- Do not detach or edit `BedrockBudgetHardCapDeny` from this machine without the owner saying so.
- Do not adopt the stricter decisions wording or the code-side decision cap; both were tested and rejected (ledger, "Fourth proxy experiment" and the code-side note).
- Do not add a general "coverage pass" instruction to the digest prompts: tested on the SBC meeting, it added one detail and three faulty clauses (ledger, "Sixth proxy experiment").
- Do not add a "vendor claims" paragraph to the digest prompts as tried: across two pairs it cut faulty clauses a little (average 2 against 3.5) but both writers dropped Lee's promised mobile scanner demo from the actions, and actions are already the weakest dimension (ledger, "Eighth proxy experiment" and its replicate). The narrower variant that only reclassifies question statuses was also tested and fixed nothing (the faults sit in the summary), so the whole line is closed.
- Do not add a "signal only" or anti-padding rule to the digest prompts: it cut padding by two thirds but lost a must-know item and three actions (ledger, "Seventh proxy experiment"). If noise must fall, do it in the display (collapse answered or near-duplicate questions), not by removing content.

## State of the repository (2026-10-09, after the owner approved committing in logical groups)
- **Branch `quotient/walkaway-digest-and-hardening`** (off `main`, **not pushed**), 29 commits ahead of `main`. The first five are the logical groups the owner approved (stop tracking compiled Python files; worker and contracts; API; portal; docs and the audit script). The rest are measured follow-ups, each with its ledger entry: the claim-check and action-recall prompt rounds, then this session's offline hardening (read-time filter fixes, hidden-text stripping, fuzz-found crashes, two independent reviews, ledger and isolation checks). `git log --oneline main..HEAD` lists them. `main` is unchanged.
- **Left uncommitted on purpose:** `apps/web/tsconfig.json`. The diff predates this work and is the Next dev server reordering its own include list. Do not `git add apps` or `git add -A`; add paths by name (I once swept it into a commit and had to redo it).
- **Suites on the committed tree:** worker 247, API 65, contracts 11, Jev 22, web 73, typecheck clean.
- **Product behaviour changed on purpose** (each is in the ledger with its revert): clicking a moment now plays it (a `?t=` link still does not); the "Promised" label for an owner's own first-person commitment; owner, decision and commentary filters at read time; the claim-check and action-recall prompt wording; security headers on the portal; magnitude words ("million", "billion", "k") are part of a number in the shared grounding scan; a key figure must contain a checkable number; identical digest items collapse; an action's due weekday or month must have been said near its lines; outside an ordinary meeting an action needs a named owner; hidden Unicode (Tags block, bidi overrides, variation selectors, C1 controls) is stripped from context documents and file names; a damaged or wrong-shaped ledger file is refused at start and left as found (it used to be read as empty and then overwritten).
- **What offline evidence exists for those changes (no model calls):** the number-scan change moves none of 2,120 stored claims; the read-time changes leave all 8 stored digests identical; fuzz of the digest, the API, the portal parser and graph data, and the exports found and fixed the crashes listed in the ledger. **What does not exist:** any live measurement of the worker-side rules. They only apply to new analyses, so the confirming run is what tests them.
- **The API and portal were restarted** several times from `scripts/stop-local.sh` and `scripts/start-local-minio.sh`; the running stack may predate the latest commits, so restart before the confirming run. Two failed meeting rows (`r14-sales`, `r14-sbc`) sit in the list from the run the budget cap refused.
- **The budget cap** (`BedrockBudgetHardCapDeny` on the group `bedrockbudgetcap`) is the owner's to lift: raise the AWS Budget, or detach the policy yourself. I will not change IAM policies. Detaching it without raising the budget removes the spending guardrail, and the budget action may re-attach it. The AWS CLI sign-in (`aws login`) also expires and has to be renewed by the owner.

## Still open after this session (not blocked on AWS, not done)
- A hard memory limit for the document converter: `RLIMIT_AS` is not enforced on macOS, so it needs a measured ceiling on the Linux host.
- A file-size or per-user upload quota: the product owner has to choose the limit; the API only checks that a declared size is a non-negative integer.
- Non-English meetings lose due dates (the time-word list is English); revisit if non-English meetings matter.
- A key figure's explanatory `what` text is not grounded (needs meaning, not lexing); several-speaker owner binding accepts any voice that spoke a cited line; a speaker name is not checked against a self-introduction.
- The ledger is one JSON file rewritten whole on every save; fine at this size, not for many users.
- A screen-reader pass, the native file picker by keyboard and saving a Settings value by keyboard (need a person).
