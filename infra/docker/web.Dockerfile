# infra/docker/web.Dockerfile
# The JudgeMetrics web image: multi-stage build on the official node:22-alpine
# base with pnpm via corepack, the Next.js standalone output, a non-root
# user, no `.env`, a HEALTHCHECK on a static page, and `node server.js` as
# the command. NEXT_PUBLIC_API_BASE_URL is inlined at build time, so it is a
# build argument: the browser and the server components both read it.
#
#   docker build -f infra/docker/web.Dockerfile -t judgemetrics-web web
#   docker compose --profile app up

# --- dependencies ------------------------------------------------------------
FROM node:22-alpine AS deps

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable

WORKDIR /app

# The lockfile and manifest only (cache-friendly); `packageManager` in
# package.json pins the pnpm version corepack activates.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --frozen-lockfile

# --- build -------------------------------------------------------------------
FROM node:22-alpine AS builder

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

RUN corepack enable

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# --- runtime -----------------------------------------------------------------
FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# Apply Alpine security updates, drop the package managers the runtime never
# uses (npm's vendored modules are what image scanners flag; only `node` is
# needed to run the standalone server), and add the runtime user (uid 10001,
# like the API image).
RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx \
       /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn* \
    && addgroup -S -g 10001 judgemetrics \
    && adduser -S -u 10001 -G judgemetrics -h /home/judgemetrics judgemetrics

WORKDIR /app
COPY --from=builder --chown=judgemetrics:judgemetrics /app/.next/standalone ./
COPY --from=builder --chown=judgemetrics:judgemetrics /app/.next/static ./.next/static
COPY --from=builder --chown=judgemetrics:judgemetrics /app/public ./public

USER judgemetrics
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/methodology').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]

CMD ["node", "server.js"]
