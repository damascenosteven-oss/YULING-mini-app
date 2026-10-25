# Collaboration workflow

The public baseline root commit is the only direct push to `main`.

1. Claim an approved GitHub Issue.
2. Create `issue/<number>-<short-slug>` from `main`.
3. Run the documented checks and include evidence in the pull request.
4. Wait for the repository owner's approval before merging.
5. Never commit credentials, customer content, private keys or account exports.

## Review-copy status

This repository is an owner-requested review copy of
[YuLing-Ai-Tech/mini-app PR #6](https://github.com/YuLing-Ai-Tech/mini-app/pull/6),
imported under [this repository's Issue #1](https://github.com/damascenosteven-oss/YULING-mini-app/issues/1).
The owner approved initializing the empty main with the original public baseline;
the candidate changes are submitted through a separate review branch and PR.

The import does not install or verify this repository's branch-protection rules,
shared engineering guard, collaborator permissions, or CODEOWNERS enforcement.
The inherited app-checks workflow must be checked against its actual run results.
Manual lifecycle and source checks cover this approved import; automated guard
installation is a separate task. Existing hooks must not be bypassed.

Historical plans, approval records, Issue/PR numbers and test reports refer to
the original YuLing-Ai-Tech repositories unless explicitly qualified otherwise.
They do not establish approval or successful CI for this review copy. Native Mac
retesting and approval remain pending. See the
[accepted import plan and current verification](docs/plans/issue-1-review-import.md).

Contributions submitted for inclusion are licensed under Apache-2.0 unless
explicitly marked otherwise before submission.
