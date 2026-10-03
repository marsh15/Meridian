# Deploying Meridian (single machine on Fly.io)

This profile runs the whole exchange on one Fly machine plus managed
Postgres: Next (standalone) serves the edge on :3000 and rewrites
`/api/*` to uvicorn on loopback :8393 inside the same container. Verified
locally: the exact image boots, migrates, serves the app, and streams SSE
ticks through the rewrite without buffering (the check is scripted at the
bottom).

What this profile deliberately excludes: Kafka, the relay/consumers, and
Temporal. `SETTLEMENT_MODE=inline` runs settlement in-request (identical
code path to the worker, ADR 0008), and SSE uses per-client Postgres
LISTEN, which is correct for exactly one API process. Redis is optional:
with `REDIS_URL=""` the rate limiter, markets cache, and Redis fan-out
all fail open. Scale-out notes at the end.

## One-time setup

```sh
flyctl auth login                 # the only manual step
fly launch --no-deploy            # accept the name; do NOT add databases/regions
fly postgres create --name meridian-db --region iad --initial-cluster-size 1
fly postgres attach meridian-db   # sets DATABASE_URL (postgres://…) as a secret
```

The app normalizes `postgres://` / `postgresql://` DSNs to the asyncpg
scheme (`app/config.py`), so the attached URL works as-is.

```sh
fly secrets set CORS_ORIGINS=https://<your-app>.fly.dev
fly deploy
```

`fly deploy` runs the release phase (`cd /srv/api && .venv/bin/alembic
upgrade head`) in the new image before traffic shifts, so migrations
always deploy with the code that expects them.

## Post-deploy verification

```sh
curl https://<your-app>.fly.dev/api/health            # {"ok":true}
# SSE: this must print a tick line within a couple of seconds;
# a blank hang means a proxy between you and the app is buffering
curl -N https://<your-app>.fly.dev/api/markets/<some-slug>/stream
```

`fly.toml` keeps `min_machines_running = 1` and `auto_stop_machines =
"stop"`: with zero machines, SSE listeners drop and the first request
pays a cold boot. One always-on machine is the SSE-correct shape.

## Why Fly and not Vercel

Vercel's functions are request-scoped: an SSE stream dies with the
function's timeout, and there is no always-on process to hold Postgres
LISTEN connections. Meridian's live prices are *push*, so the deploy
target must allow long-lived connections from a resident process. A
single Fly machine (or any always-on container host: Railway, Render, a
VPS) is the right shape; the Fly proxy streams responses unbuffered.

## Cost ballpark

shared-cpu-1x / 1 GB machine ≈ $5 to $7/mo, Fly Postgres single-node ≈
$2 to $5/mo. Play money, no compliance surface; this is the cheapest
honest deployment.

## Verify the image locally (no Fly account needed)

The same checks the post-deploy section asks for, against compose
Postgres:

```sh
docker compose up -d --wait db
docker build -t meridian-single .
# env flags go BEFORE the image name; the entrypoint deliberately runs no
# migrations (Fly's release phase owns them), so a non-Fly host applies
# them explicitly here before first boot
docker run --rm --entrypoint sh \
  -e DATABASE_URL="postgresql+asyncpg://meridian:meridian@host.docker.internal:5434/meridian" \
  meridian-single -c "cd /srv/api && .venv/bin/alembic upgrade head"
docker run -d --name meridian-verify -p 127.0.0.1:8400:3000 \
  -e DATABASE_URL="postgresql+asyncpg://meridian:meridian@host.docker.internal:5434/meridian" \
  -e REDIS_URL="" meridian-single
curl -N localhost:8400/api/health                     # {"ok":true}
curl -N localhost:8400/api/markets/<slug>/stream      # ticks arrive unbuffered
docker rm -f meridian-verify
```

On any host that isn't Fly (which runs `alembic upgrade head` in its
release phase), run the migration command above once per deploy before
starting the container; the entrypoint never migrates.

## Free tier: Render + Aiven (the $0 deployment)

The same image runs on [Render](https://render.com)'s free web service
with Postgres on [Aiven](https://aiven.io)'s free plan, and no card gets
charged anywhere. Trade-offs vs the Fly profile: 512 MB RAM, the service
sleeps after ~15 min of idle (first visitor pays a ~50s cold start), and
free Render runs no pre-deploy hooks, so migrations happen from your
machine.

One-time, in order:

1. GitHub: push the repo; Render deploys from it (`render.yaml` is
   the Blueprint at the repo root).
2. Aiven: create a free PostgreSQL service (PG 16), copy the
   service URI. It looks like
   `postgres://avnadmin:…@pg-…aivencloud.com:…/defaultdb?ssl-mode=require`.
3. Prepare the database (migrations + demo seed + a LISTEN/NOTIFY
   round-trip proof: the SSE backbone, verified before anything else):

   ```bash
   uv run --project services/api python scripts/prepare-remote-db.py "<AIVEN URI>"
   ```

   It prints the normalized `DATABASE_URL` to paste into Render
   (`postgresql+asyncpg://…?sslmode=require`).
4. Render: New → Blueprint → pick the repo; set `DATABASE_URL` as the
   one secret (the rest of the env comes from `render.yaml`:
   `SETTLEMENT_MODE=inline`, `COOKIE_SECURE=true`,
   `TRUST_PROXY_HEADERS=true`, `REDIS_URL=""`). Deploy.
5. Verify live (same checks as the Fly section):

   ```bash
   curl -s https://<app>.onrender.com/api/health        # {"ok":true}
   curl -s https://<app>.onrender.com/api/markets | head -c 200
   curl -N --max-time 5 https://<app>.onrender.com/api/markets/<slug>/stream
   # → `event: tick` + a snapshot line arrive unbuffered
   ```
6. Pinger: a free uptime monitor (cron-job.org or UptimeRobot)
   requesting `/api/health` every 10 minutes keeps both the service
   awake and the database marked active. This is the free-tier health
   story: Render's native health checks are a paid feature.

Database upgrades on later deploys: re-run step 3 (idempotent;
migrations stop at head, the seed skips itself).

## Scaling past one machine

- A second API process: set `REDIS_URL` (e.g. Upstash) and rate limits
  and the markets cache become shared, and the SSE tick fan-out moves
  from per-client Postgres LISTEN to the Redis bridge (ADR 0009) so any
  instance's clients see every tick. Keep Postgres LISTEN as the
  origin; Redis is fan-out only.
- Event backbone: bring up the compose Kafka + relay + consumers with
  `OTLP_ENDPOINT` pointed at a collector; the outbox contract is
  unchanged.
- Durable settlement: run `python -m worker` against managed Temporal
  (Tempo Cloud or self-hosted) and flip `SETTLEMENT_MODE=temporal`.
