---
issue: YuLing-Ai-Tech/mini-app#7
status: accepted
base: ed8cbb8b316e5b572f45a93faca550a41a3b265e
starting_candidate: 18814e8e19bcddd74f9c54690ce0838c3879a875
adr: not-required
---
# Stabilize Apple Silicon capture arguments

Approved by the owner in this task on 2026-10-21. Issue #7 is open and assigned;
its owner-reported native M5 results are source evidence, not a local Mac run.

## Accepted change and Critic Loop

The shared browser argument function adds --disable-gpu only for win32 today;
the Mac test explicitly requires the Linux argument list. Issue #7 reports
small gradient-channel differences across independent Mac candidate captures.

- Keep arguments: no implementation risk but Mac remains blocked; 45/100.
- Add --disable-gpu for darwin, preserve exact Windows/Linux lists: focused
  change with native confirmation still required; 92/100, accepted.
- Change all platforms: unnecessarily invalidates Linux evidence; 60/100.
- Relax pixel assertions or replace Golden: weakens acceptance; 20/100, rejected.

Update the existing shared function and exact platform tests. No new interface,
dependency, module boundary or irreversible decision is introduced, so a new
ADR is not required. Preserve missing-Mac-baseline failure, two independent
12-page captures, zero tolerance, Golden files and ENGINE_BASELINE.json.

## Verification and delivery

First prove the new Mac assertion fails against the old implementation. Then
run frozen installation, targeted tests, validate, portable and cross-repository
tests, geometry, formal Windows pixels, a fresh external candidate capture,
build and full/production dependency audits. Record actual counts, exit codes,
source SHAs and evidence hashes. Candidate capture uses committed clean sources.
Update the Mac handoff and report separately from the tested code commit.

The owner explicitly approves continuing the existing independent worktree
issue/1-mac-visual-compat and PR #6 remote branch
issue/1-reproduce-public-baseline for Issue #7. Do not create another worktree,
Issue or PR merely to renumber this continuation. Link Issue #7 and preserve
the existing umbrella Issue #1 association; no automatic closure before Mac
acceptance. This is the approved branch/Issue workflow exception.

After all required Windows checks pass, ordinary fast-forward push to PR #6,
post the exact results on Issue #7 and PR #6, and request zhaobeamsoon-coder
review on PR #6 and paired engine PR #5. Do not merge or deploy. Native Mac
repeatability and final acceptance remain owner-run gates, not Windows claims.
Rollback uses a new inverse commit, preserving evidence and prior history.
