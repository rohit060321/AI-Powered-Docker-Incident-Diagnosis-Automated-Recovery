#!/usr/bin/env bash
# Fail the job, then run the pipeline. Any args are passed to pipeline.py.
#   ./demo.sh              agree -> one recovery -> verified
#   ./demo.sh --conflict   disagreement -> human review
#   ./demo.sh --proposals out/proposals.json   replay (survives a dead gateway)
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || cp .env.example .env
set -a
# shellcheck disable=SC1091
. ./.env
set +a

echo "== injecting OOM: ${JOB_NAME} --memory=${FAIL_LIMIT} =="
docker rm -f "${JOB_NAME}" >/dev/null 2>&1 || true
rm -f out/executed.lock 2>/dev/null || true

set +e
docker run --name "${JOB_NAME}" \
  --memory="${FAIL_LIMIT}" \
  -e ALLOC_MB="${ALLOC_MB}" \
  -v "${PWD}/oom_job:/j:ro" \
  "${JOB_IMAGE}" python /j/oom.py
rc=$?
set -e
echo "== job exited ${rc} (137 = OOM kill) =="

echo
python3 pipeline.py "$@"
