# YuLing AI PPT Mini App

Open-source, mobile-first Next.js workspace for generating, reviewing and sharing
YuLing HTML presentations.

## Boundary

- This repository owns the user interface, API routes, structured generation,
  storage, preview and share workflow.
- [`YuLing-Ai-Tech/yuling-ai-ppt`](https://github.com/YuLing-Ai-Tech/yuling-ai-ppt)
  owns the Python/HTML presentation runtime and visual engine.
- The application invokes the engine through `PPT_ENGINE_ROOT`; the two
  repositories must be checked out as siblings for local development.
- `ENGINE_BASELINE.json` records the exact compatible engine commit and tag.

## Local setup

```bash
cp .env.example .env.local
pnpm install --frozen-lockfile
PPT_ENGINE_ROOT=../yuling-ai-ppt pnpm dev
```

Use recipient-owned credentials only. Never commit `.env`, private keys,
account exports or customer material.

## Checks

Issue #1's candidate pair and native Mac owner procedure are documented in
[MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md) and
[BASELINE_REPRODUCTION.md](BASELINE_REPRODUCTION.md). Mac pixel acceptance still
requires separately reviewed native candidates.

```bash
pnpm validate
pnpm test:portable
PPT_ENGINE_ROOT=../yuling-ai-ppt pnpm test:ppt
PPT_ENGINE_ROOT=../yuling-ai-ppt pnpm test:ppt:golden:geometry
pnpm build
```

## Local-only production configuration

`deploy/` contains a placeholder-only Caddy example, systemd application and
cleanup units, a secret-free environment template, and an interactive helper
that writes `/etc/yuling-ai-ppt.env` with mode `0600` without echoing secrets.
Copy the Caddy example to `/etc/caddy/Caddyfile` and fill in the address only on
the server. A real domain or public IP must never be committed to this repository.

Production releases are assembled outside Git as immutable directories under
`/opt/yuling-ai-ppt/releases/<timestamp>-<app-sha>-<engine-sha>/`, with `app/`
and `engine/` subdirectories. The service runs through the atomic
`/opt/yuling-ai-ppt/current` symlink and reads the engine from
`PPT_ENGINE_ROOT=/opt/yuling-ai-ppt/current/engine`.

This safe baseline intentionally excludes the former AI training course site
and its personal/contact material.

## License and package status

The code is licensed under Apache-2.0. Brand names and logos are not licensed
for reuse; see `TRADEMARKS.md`. `package.json` intentionally keeps
`"private": true` to prevent accidental npm publication; it does not describe
the GitHub repository visibility.
