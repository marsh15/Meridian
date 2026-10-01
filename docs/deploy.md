# Deploying Meridian (single machine on Fly.io)

This profile runs the whole exchange on **one Fly machine + managed Postgres**:
Next (standalone) serves the edge on :3000 and rewrites `/api/*` to uvicorn on
loopback :8393 inside the same container. Verified locally: the exact image
boots, migrates, serves the app, and streams SSE ticks through the rewrite
without buffering (the check is scripted at the bottom).

What this profile deliberately **excludes**: Kafka, the relay/consumers, and
Temporal. `SETTLEMENT_MODE=inline` runs settlement in-request (identical code
path to the worker — ADR 0008), and SSE uses per-client Postgres LISTEN,
which is correct for exactly one API process. Redis is optional: with
`REDIS_URL=""` the rate limiter, markets cache, and Redis fan-out all fail
open. Scale-out notes at the end.

## One-time setup

```sh
flyctl auth login                 # the only manual step
fly launch --no-deploy            # accept the name; do NOT add databases/regions
fly postgres create --name meridian-db --region iad --initial-cluster-size 1
fly postgres attach meridian-db   # sets DATABASE_URL (postgres://…) as a secret
```

The app normalizes `postgres://` / `postgresql://` DSNs to the asyncpg scheme
(`app/config.py`), so the attached URL works as-is.

```sh
fly secrets set CORS_ORIGINS=https://<your-app>.fly.dev
fly deploy
```

`fly deploy` runs the release phase (`cd /srv/api && .venv/bin/alembic upgrade
head`) in the new image before traffic shifts — migrations always deploy with
the code that expects them.

## Post-deploy verification

```sh
curl https://<your-app>.fly.dev/api/health            # {"ok":true}
# SSE: this must print a tick line within a couple of seconds —
# a blank hang means a proxy between you and the app is buffering
curl -N https://<your-app>.fly.dev/api/markets/<some-slug>/stream
```

`fly.toml` keeps `min_machines_running = 1` and `auto_stop_machines = "stop"`:
with zero machines, SSE listeners drop and the first request pays a cold boot.
One always-on machine is the SSE-correct shape.

## Why Fly and not Vercel

Vercel's functions are request-scoped: an SSE stream dies with the function's
timeout, and there is no always-on process to hold Postgres LISTEN
connections. Meridian's live prices are *push* — the deploy target must allow
long-lived connections from a resident process. A single Fly machine (or any
always-on container host: Railway, Render, a VPS) is the right shape; the
Fly proxy streams responses unbuffered.

## Cost ballpark

shared-cpu-1x / 1 GB machine ≈ $5–7/mo, Fly Postgres single-node ≈ $2–5/mo.
Play money, no compliance surface — this is the cheapest honest deployment.

## Verify the image locally (no Fly account needed)

The same checks the post-deploy section asks for, against compose Postgres:

```sh
docker compose up -d --wait db
docker build -t meridian-single .
docker run --rm --entrypoint sh meridian-single \
  -e DATABASE_URL="postgresql+asyncpg://meridian:meridian@host.docker.internal:5434/meridian" \
  -c "cd /srv/api && .venv/bin/alembic upgrade head"
docker run -d --name meridian-verify -p 8400:3000 \
  -e DATABASE_URL="postgresql+asyncpg://meridian:meridian@host.docker.internal:5434/meridian" \
  -e REDIS_URL="" meridian-single
curl -N localhost:8400/api/markets/<slug>/stream   # ticks arrive unbuffered
docker rm -f meridian-verify
```

## Scaling past one machine

- **Second API process** → set `REDIS_URL` (e.g. Upstash): rate limits and the
  markets cache become shared, and the SSE tick fan-out moves from per-client
  Postgres LISTEN to the Redis bridge (ADR 0009) so any instance's clients
  see every tick. Keep Postgres LISTEN as the origin — Redis is fan-out only.
- **Event backbone** → bring up the compose Kafka + relay + consumers with
  `OTLP_ENDPOINT` pointed at a collector; the outbox contract is unchanged.
- **Durable settlement** → run `python -m worker` against managed Temporal
  (Tempo Cloud or self-hosted) and flip `SETTLEMENT_MODE=temporal`.
