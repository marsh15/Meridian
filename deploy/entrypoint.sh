#!/bin/sh
# Both processes, one machine — if either dies the container exits and the
# platform restarts it (never serve a half-broken app).
set -u

cd /srv/api
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8393 &
API_PID=$!

cd /srv/web/apps/web
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
WEB_PID=$!

echo "meridian: api(pid $API_PID) on :8393, web(pid $WEB_PID) on :3000"

trap 'kill $API_PID $WEB_PID 2>/dev/null; exit 0' TERM INT

# portable wait -n: first process to exit takes the container with it
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
echo "meridian: a process exited — shutting down" >&2
kill "$API_PID" "$WEB_PID" 2>/dev/null
exit 1
