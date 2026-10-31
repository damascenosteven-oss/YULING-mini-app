FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS runtime
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates xz-utils fontconfig \
       libnss3 libnspr4 libatk-bridge2.0-0t64 libgtk-3-0t64 libcups2t64 \
       libgbm1 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libasound2t64 \
       libdrm2 libxkbcommon0 libatspi2.0-0t64 libpangocairo-1.0-0 libxshmfence1 \
       fonts-noto-cjk=1:20240730+repack1-1 fonts-liberation=1:2.1.5-3 \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/test/runtime-lock.json /tmp/runtime-lock.json
COPY deploy/test/install-runtime.py /tmp/install-runtime.py
COPY --from=runtime_downloads / /tmp/runtime-downloads/
RUN python /tmp/install-runtime.py \
    && rm -rf /tmp/node /tmp/runtime-downloads /tmp/install-runtime.py \
    && node --version && pnpm --version \
    && /opt/chrome/chrome-linux64/chrome --version
COPY deploy/test/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements-runtime.txt \
    && rm /tmp/requirements-runtime.txt
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PYTHONUNBUFFERED=1 \
    PPT_HOST=0.0.0.0 PORT=5000 PPT_ENGINE_ROOT=/opt/yuling/engine \
    PPT_PYTHON_PATH=/usr/local/bin/python PPT_CHROME_PATH=/opt/chrome/chrome-linux64/chrome
WORKDIR /opt/yuling/app

FROM runtime AS build
ENV NODE_ENV=development
COPY package.json pnpm-lock.yaml ./
COPY patches ./patches
COPY --from=dependency_store / /tmp/dependency-store/
RUN --network=none npm_config_offline=true pnpm install --offline --frozen-lockfile --store-dir /tmp/dependency-store \
    && rm -rf /tmp/dependency-store
COPY --from=engine / /opt/yuling/engine/
COPY . .
RUN pnpm validate && pnpm test:portable
RUN pnpm test:ppt | tee /tmp/integration.log
RUN python -c "import pathlib,re; s=pathlib.Path('/tmp/integration.log').read_text(); assert re.search(r'# skipped 0\b',s), 'Full integration suite skipped tests'"
RUN pnpm test:ppt:golden:geometry \
    && env -u NODE_ENV pnpm build \
    && node deploy/test/build-smoke.mjs
# Fresh full/production audits are mandatory in build-image.py, outside cached layers.
# Normalize public runtime data before the final COPY, avoiding a duplicate
# application layer when the relay's source checkout inherits umask 077.
RUN pnpm prune --prod && chmod -R a+rX,go-w /opt/yuling

FROM runtime AS application
ENV HOME=/home/ppt XDG_CONFIG_HOME=/home/ppt/.config XDG_CACHE_HOME=/home/ppt/.cache
ARG APP_SHA
ARG SOURCE_DIRTY=true
LABEL dev.yuling.application="yuling-ppt-test" \
      dev.yuling.model-settings="v1" \
      org.opencontainers.image.revision=$APP_SHA \
      dev.yuling.engine.revision="be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192" \
      dev.yuling.source.dirty=$SOURCE_DIRTY
COPY --from=build /opt/yuling/app/.next ./.next
COPY --from=build /opt/yuling/app/dist ./dist
COPY --from=build /opt/yuling/app/public ./public
COPY --from=build /opt/yuling/app/node_modules ./node_modules
COPY --from=build /opt/yuling/app/package.json ./
COPY --from=build /opt/yuling/app/dist/next.config.mjs ./next.config.mjs
COPY --from=build /opt/yuling/engine /opt/yuling/engine
COPY deploy/test/runtime-lock.json /opt/yuling/runtime-lock.json
RUN APP_SHA="$APP_SHA" SOURCE_DIRTY="$SOURCE_DIRTY" python -c \
    "import json,os,pathlib,re; sha=os.environ['APP_SHA']; assert re.fullmatch('[0-9a-f]{40}',sha); pathlib.Path('/opt/yuling/release.json').write_text(json.dumps({'app_sha':sha,'engine_sha':'be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192','source_dirty':os.environ['SOURCE_DIRTY']!='false'}))" \
    && chmod 0644 /opt/yuling/runtime-lock.json \
    && mkdir -p /opt/yuling/app/.next/cache /home/ppt/.config /home/ppt/.cache /var/lib/yuling-ppt/model-settings \
    && chown -R 10001:10001 /opt/yuling/app/.next/cache /home/ppt /var/lib/yuling-ppt/model-settings \
    && chmod 0700 /var/lib/yuling-ppt/model-settings
USER 10001:10001
EXPOSE 5000
CMD ["node", "dist/server.js"]
