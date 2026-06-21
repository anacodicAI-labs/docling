#!/usr/bin/env bash
# End-to-end Phase 0 demo: create job → upload PDF → start → poll until complete.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API="${API_BASE:-http://localhost:8000/api/v1}"
PDF="${1:-input/2508.19093v2.pdf}"

if [[ ! -f "$PDF" ]]; then
  echo "PDF not found: $PDF"
  exit 1
fi

echo "==> Health"
curl -sf "$API/health" | python3 -m json.tool

echo "==> Create job"
CREATE=$(curl -sf -X POST "$API/jobs" -H "Content-Type: application/json" -d '{}')
echo "$CREATE" | python3 -m json.tool
JOB_ID=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
TOKEN=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

echo "==> Upload $PDF"
curl -sf -X POST "$API/jobs/$JOB_ID/files" \
  -H "X-Job-Token: $TOKEN" \
  -F "files=@${PDF}" | python3 -m json.tool

echo "==> Start processing"
curl -sf -X POST "$API/jobs/$JOB_ID/start" \
  -H "X-Job-Token: $TOKEN" | python3 -m json.tool

echo "==> Poll status (Ctrl+C to stop watching)"
while true; do
  STATUS=$(curl -sf "$API/jobs/$JOB_ID" -H "X-Job-Token: $TOKEN")
  JOB_STATUS=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['progress'])")
  echo "$(date +%H:%M:%S) $JOB_STATUS"
  echo "$STATUS" | python3 -c "import sys,json; s=json.load(sys.stdin)['status']; raise SystemExit(0 if s in ('completed','partial','failed') else 1)" && break
  sleep 3
done

echo "==> Final job"
curl -sf "$API/jobs/$JOB_ID" -H "X-Job-Token: $TOKEN" | python3 -m json.tool

OUT="data/storage/jobs/$JOB_ID/output"
echo "==> Output tree under $OUT"
find "$OUT" -maxdepth 3 -type f | head -30
