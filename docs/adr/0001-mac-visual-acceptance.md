---
issue: YuLing-Ai-Tech/yuling-ai-ppt#1
status: accepted
---
# Platform-specific visual acceptance with Mac owner handoff

Decision approved in the 2026-10-21 task. Product interfaces stay unchanged;
only QA command capability and platform acceptance policy change.

## Critic Loop

Problem: Windows/Linux-only QA rejects Apple Silicon; app geometry loads a pixel
manifest before it can run. Direct calls with darwin/arm64 reproduce the rejection.
The reviewer requested restoring Mac without claiming Windows is Mac evidence.

- Keep behavior: no implementation cost, Mac remains blocked at entry; 20/100.
- Borrow another platform's images: small change, invalid visual evidence; 0/100.
- Restore execution and collect native Mac targets separately: adds capture and
  owner review cost but preserves strict comparison and provenance; 95/100, accepted.

Mac support does not mean Mac acceptance. Geometry needs no approved PNG; pixel
checks require the exact approved platform manifest and environment. No automatic
baseline adoption. Windows/Linux byte-level baselines and launch settings remain.
Mac native runtime, fonts and browser source are evidence prerequisites; missing
or unreadable inventory fails acceptance. macOS/arm64 is the only added platform.
