# Meridian — single-machine production image (docs/deploy.md).
# One container runs both halves on the same loopback:
#   uvicorn app.main:app on 127.0.0.1:8393  (API + SSE)
#   Next standalone node server on 0.0.0.0:3000 (edge; /api/* rewrites to 8393)
# Kafka/Temporal are intentionally not part of this profile — the API runs
# SETTLEMENT_MODE=inline and SSE uses per-client pg LISTEN (single instance).
#
# The runtime base is node (the standalone web server needs it); the API's
# Python is a uv-managed CPython copied in at a fixed path so the venv's
# interpreter symlink and script shebangs stay valid.

# ---------- stage 1: workspace deps (pnpm, cached by lockfile) ----------
FROM node:22-alpine AS web-deps
WORKDIR /repo
RUN corepack enable
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN pnpm install --frozen-lockfile --ignore-scripts

# ---------- stage 2: Next standalone build ----------
FROM node:22-alpine AS web-build
WORKDIR /repo
RUN corepack enable
COPY --from=web-deps /repo ./
COPY apps/web apps/web
COPY packages/contracts packages/contracts
# MERIDIAN_API_URL is read by the /api/* rewrite at server start; the
# entrypoint exports the same loopback before node boots
RUN pnpm --filter meridian-web exec next build

# ---------- stage 3: API venv (uv-managed python, final paths) ----------
FROM node:22-bookworm-slim AS api-deps
# pinned like every other tool in this file: release-phase migrations must
# not depend on whenever the image was last built
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.13
WORKDIR /srv/api
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# ---------- runtime ----------
FROM node:22-bookworm-slim
WORKDIR /srv

COPY --from=api-deps /opt/uv-python /opt/uv-python
COPY --from=api-deps /srv/api/.venv /srv/api/.venv
COPY services/api /srv/api
ENV PATH="/srv/api/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# standalone preserves the workspace layout (tracing root = repo root):
# server.js lands at /srv/web/apps/web/server.js with the pnpm store at
# /srv/web/node_modules — keep it exactly as generated
COPY --from=web-build /repo/apps/web/.next/standalone /srv/web
COPY --from=web-build /repo/apps/web/.next/static /srv/web/apps/web/.next/static

COPY deploy/entrypoint.sh /srv/entrypoint.sh
RUN chmod +x /srv/entrypoint.sh

# least privilege: both servers only read /srv, so they run as a dedicated
# non-root user (the entrypoint and children inherit it)
RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /srv
USER app

# goes through the Next server's /api/* rewrite to the API loopback, so it
# proves both halves are actually serving
HEALTHCHECK --interval=30s --timeout=3s --start-period=25s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

EXPOSE 3000
ENTRYPOINT ["/srv/entrypoint.sh"]
