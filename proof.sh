#!/usr/bin/env bash
# Three proofs, one command. Paste this on stage when someone asks "is it real?"
set -euo pipefail
cd "$(dirname "$0")"

NB_TENANT=346aa2cd-d511-4501-80ee-ae3c43a46885
PSQL=(docker exec nudgebee-probe-postgres-1 psql -U postgres -d nudgebee)

echo "== 1. A real kernel OOM (128 MiB limit, 512 MiB job) =="
docker rm -f proof >/dev/null 2>&1 || true
docker run --name proof --memory=128m -v "$PWD/oom_job:/j:ro" \
  python:3.12-slim python /j/oom.py 2>&1 | tail -3 || true
docker inspect proof --format '   ExitCode={{.State.ExitCode}}  OOMKilled={{.State.OOMKilled}}  Limit={{.HostConfig.Memory}} bytes'
docker rm -f proof >/dev/null 2>&1 || true

echo
echo "== 2. The recovery is a real container, not a printout =="
docker inspect "${JOB_NAME:-oom-job}" \
  --format '   name={{.Name}} image={{.Config.Image}} limit={{.HostConfig.Memory}} oom_killed={{.State.OOMKilled}} exit={{.State.ExitCode}}'
docker logs "${JOB_NAME:-oom-job}" 2>&1 | tail -2 | sed 's/^/   /'

echo
echo "== 3. NudgeBee metered every analysis (its own table) =="
"${PSQL[@]}" -c "select to_char(created_at,'HH24:MI:SS') at, provider, model,
                        status_code, input_tokens, output_tokens, latency_ms
                 from public.llm_gateway_usage order by created_at desc limit 5;"

echo "== 4. The decision trail =="
tail -6 out/ledger.jsonl 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    keep = {k: v for k, v in r.items() if k in ('verdict', 'reason', 'result', 'recovered', 'agent')}
    print('  ', r['ts'], r['stage'], keep)
"
