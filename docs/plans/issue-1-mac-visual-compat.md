---
issue: YuLing-Ai-Tech/yuling-ai-ppt#1
status: accepted
base: ed8cbb8b316e5b572f45a93faca550a41a3b265e
starting_candidate: dbb0bf50f36e7ae353d7b89aafcca4b325be998a
adr: 0001-mac-visual-acceptance
---
# Restore Apple Silicon visual acceptance

Approved by the task owner on 2026-10-21 in the implementation request.
Use independent issue/1-mac-visual-compat worktrees, initially verified clean at
main, then fast-forwarded to the existing PR #6 candidate. Delivery remains
issue/1-reproduce-public-baseline. Never edit the primary checkout.

## Accepted implementation

Recognize darwin/arm64, separate application geometry from pixel baseline loading,
and provide non-destructive candidate CLI capture with two independent browser
launches. Missing Mac baselines fail pixel acceptance explicitly; no fallback,
skips, tolerance changes, or fabricated Mac results. Capture actual OS, browser,
font and source evidence. Preserve all existing baseline bytes and renderer APIs.
Mac font registration and browser provenance must be verified on the owner's Mac.
Candidate output must be new and outside repositories; retain failures.

## Verification and rollout

Red/green tests cover platform routing, missing/corrupt baselines, environment and
font drift, output safety and real command error propagation. Re-run Windows and
independent WSL2 complete engine/app suites, production-shaped Python calls,
geometry/pixels/mutations, builds and security scans. Deliver exact Mac commands
and expected results. Mac owner captures, reviews and separately approves images;
only then adopt exact originals and run full Mac acceptance.

## Task-specific workflow exception

User explicitly chose to continue existing PRs #5/#6 and shared PPT Issue #1,
without replacement Issues/PRs or an automatic Closes keyword. Preserve review
history; push fast-forward only after local checks. Owner approval, Mac evidence,
remote CI and final engine merge SHA remain gates. Update app ENGINE_BASELINE only
after engine merge and repeat paired verification. No merge/deploy/DVSK work.
No shared lifecycle hard gate is installed; equivalent checks are manual.
Rollback with a new revert PR; retain historical evidence and worktrees.
