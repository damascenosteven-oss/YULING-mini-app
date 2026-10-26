---
issue: YuLing-Ai-Tech/yuling-ai-ppt#1
status: accepted
base: ed8cbb8b316e5b572f45a93faca550a41a3b265e
adr: 0002-python-security-toolchain
---
# Python security supplement

Approved by the user on 2026-10-21. Continue existing independent worktrees,
Issue #1 and PRs #5/#6 under the recorded continuation exception.

Pin Pillow 13.0.0 and uv 0.13.4 only. Update active test requirements, CI invocation,
README and third-party notices; preserve historical records and all Golden bytes.
Keep setup-uv action version, pin its installed uv version. Bootstrap new isolated
Windows/WSL2 tool, test and builder environments using official artifacts and
verified hashes without the old uv. Audit each actual environment separately,
including the auditor; fail closed on findings or unavailable audit data.

Add synthetic real-builder tests for RGB/RGBA, resizing, lossless QR PNG and corrupt
input. Prove assertions with deliberate mutations, then restore source and verify
Pillow 13. Do not silently change product behavior or image tolerances.

After clean audits, rerun complete Windows/WSL2 suites, production-shaped calls,
strict visuals/repeatability/mutations, builds and secret scans. Preserve interrupted
logs. Record exact source/environment/log hashes, finish the Mac owner runbook and
approval index, then fast-forward existing PR branches under existing push authority.
Mac owner approval and final engine SHA pairing remain separate gates. No merge,
deployment, DVSK changes, Golden replacement or formal engine lock update now.
Rollback is a new revert PR; returning to vulnerable versions restores Blocked status.
