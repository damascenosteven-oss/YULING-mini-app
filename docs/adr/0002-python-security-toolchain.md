---
issue: YuLing-Ai-Tech/yuling-ai-ppt#1
status: accepted
---
# Pin the repaired Python toolchain

Approved 2026-10-21. Public product APIs and builder invocation remain unchanged.

## Critic Loop

Actual audit found eight Pillow 12.3.0 advisories and one uv 0.13.1 advisory.
Official patched versions are Pillow 13.0.0 and uv 0.13.4. The source builder
uses Pillow for decoding, resizing and re-encoding images, not just comparison.

- Keep old versions: low effort but cannot meet zero-alert acceptance; 20/100.
- Upgrade only these versions: major-version compatibility verification required,
  while keeping browser/render variables fixed; 90/100, accepted.
- Upgrade all tools/browser: broader risk and invalidated visual environment; 40/100.

Use separate audited environments and provenance-checked artifacts. Preserve exact
Golden bytes and strict assertions. Audits happen before full regression. New
unsupported behavior or new findings block acceptance; do not add exemptions.
