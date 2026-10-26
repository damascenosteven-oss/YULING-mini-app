# Visual approval trace — PPT Issue #1

## Scope and authority

The task owner explicitly approved the Public engine Windows nine pages, engine
WSL2 nine pages, and application Windows software-rendered twelve pages as visual
targets, then approved their adoption plan in this task on **2026-10-20**.
The application Linux twelve pages reuse the existing Public baseline, byte for
byte. The recorded approval source is the owner's task conversation; this document
does **not** claim a GitHub approval review has been submitted.

Owner confirmation on PR #5/#6 is still requested: confirm these manifest/image
sets and the page-eight coordinate change below. The agent cannot approve on the
owner's or Architect's behalf. No Mac target is included in this approval.

## Approved image sources

- Engine rendered source: `f2c33fe124e864114020d15b66749025c8bb0046`.
- Application rendered source: `d7508f77ed044ccc3ab9da40bf5a79076c33129e`.
- Original review index SHA256: `d9fc02767e8bc2ce47c540508ca9ce1aaaa240000d7d327f6585a97706e112b2`.
- Original candidate-a images were copied without regeneration. Application
  Windows geometry was accepted only after supplementary capture PNG hashes
  matched those approved originals. Linux app images reused the Public originals.
- Each manifest retains the platform environment, image hashes, source commits,
  approval date and original evidence references. Raw local logs remain outside
  the repositories. No personal absolute paths are required to identify a set.

## Exact manifest index

SHA256 below covers the **committed Git blob bytes**, avoiding checkout newline
conversion ambiguity. Each referenced PNG was checked against its manifest.

| Repository / platform | Pages | Manifest | Manifest SHA256 |
| --- | --- | --- | --- |
| yuling-ai-ppt / win32-x64 | 9 | `baselines/图元样板/platforms/win32-x64/manifest.json` | `414a71b03309c82957d4a7e671a0a125994a58285121686ca5e6c534c3e7ffd9` |
| yuling-ai-ppt / linux-x64 | 9 | `baselines/图元样板/platforms/linux-x64/manifest.json` | `a744c3e60b3ad0d7f74835a855fed6c708c076e5f90108ed8f83261daa60ffa6` |
| mini-app / win32-x64 | 12 | `tests/ppt-golden/baseline/platforms/win32-x64/manifest.json` | `5bd4ad5ea862c83ae055f3e45ba20b1061f7b0a7cf3b3dfae33e81a8e4277b5d` |
| mini-app / linux-x64 | 12 | `tests/ppt-golden/baseline/platforms/linux-x64/manifest.json` | `19420887a8cb53b344df0e51bc145d59007b531ce14c2581441c455201ab3ad1` |

## Page-eight coordinate approval

Scoped fix commit: `94830997b4e740f44c58622c421f39d5bfd136ca` (engine).
Only the sample hub's `data-at` changed from `9.615 3 4.77 6` to
`9.607143 3 4.785714 6`; the approved task plan kept center and height and preserved
the original one-pixel width/height assertion. General circle rendering was not
changed. This intentional visual change is included in the reviewed Public
engine targets above; historical root PNGs/manifests remain unchanged.

## Current continuation and remaining approvals

Mac compatibility and Python toolchain commits preserve all 69 existing Golden
and manifest files. They do not grant new image approval. Native Mac candidate
capture must identify its exact pair and environment; owner must review all
9 engine + 12 application pages and explicitly approve their hashes before any
`platforms/darwin-arm64` adoption. After adoption, full native regression remains
mandatory.

The engine final merge SHA is not yet known. Keep ENGINE_BASELINE.json unchanged
until the owner-approved engine merge, then update and verify the actual pair.
CI, Architect Review and owner approval remain independent release gates.
