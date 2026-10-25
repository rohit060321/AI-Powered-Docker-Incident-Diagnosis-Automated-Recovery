# OOM acceptance-bridge MVP

The disposable Docker image allocates 192 MiB. It fails under a 128 MiB memory limit and succeeds under 384 MiB. The same image runs as a KinD Job. The collector freezes logs, pod/container OOM state, resource limits, and events in a hash-bound incident task. Project-owned A2A HTTP+JSON wrappers deliver that task to the Kepler/RubixKube and NudgeBee branches. The bridge compares their independent assessments, automatically creates one fixed recovery Job only when both agree and live preconditions pass, and verifies completion. Anything else is held for human review.

`mvp/.env.local` contains local random bridge tokens and is ignored. It is loaded when starting the bridge from the project root. Do not copy it to a public repository. The bridge defaults to `EXECUTION_MODE=dry-run`; set `live` only for the disposable KinD test after validating the cluster.

## Local run

```sh
docker build -t oom-lab:0.1 mvp/fixture
kind create cluster --name agent-mvp --config mvp/kubernetes/kind.yaml
kind load docker-image oom-lab:0.1 --name agent-mvp
kubectl --context kind-agent-mvp apply -f mvp/kubernetes/namespace.yaml
kubectl --context kind-agent-mvp apply -f mvp/kubernetes/job-oom.yaml
python3 -m mvp.bridge.server
```

In another terminal from the same project root:

```sh
python3 -m mvp.cli collect-k8s
python3 -m mvp.cli dispatch INCIDENT_ID
python3 -m mvp.adapters.draft_rubix INCIDENT_ID
```

Read [Kepler’s war room run card](adapters/KEPLER_WAR_ROOM.md), then submit its reviewed assessment with `python3 -m mvp.adapters.kepler_submit INCIDENT_ID mvp/evidence/rubix-assessment.json`. Configure the [NudgeBee workflow](adapters/NUDGEBEE_WORKFLOW.md) to send its own assessment callback. The review page is at `http://127.0.0.1:8765/`; paste the **local** `BRIDGE_TOKEN` from `.env.local` into the page, then choose the incident.

For self-hosted NudgeBee, the [official source and deployment options](nudgebee/README.md) are included. The remote Helm path needs a larger Kubernetes cluster. The official GitHub Compose stack can be used as a **local development** login/UI rehearsal with the loopback-only override here; that does not meet the published full self-hosted server sizing and should not be presented as a production deployment.

Run `python3 -m unittest discover -s mvp/tests -v` for the bridge decision checks. The A2A wrappers expose Agent Cards at `/a2a/rubix/.well-known/agent-card.json` and `/a2a/nudgebee/.well-known/agent-card.json`, `POST /a2a/{agent}/message:send`, and `GET /a2a/{agent}/tasks/{task-id}`. They follow the relevant [A2A 1.0 HTTP+JSON operations](https://a2a-protocol.org/v1.0.1/specification/); no vendor-native A2A support is assumed. This is a working subset, not a full protocol conformance claim.

## API and policy

The admin bearer token protects incident creation/read, dispatch, decisions, execution, and verification. `RUBIX_SUBMIT_TOKEN` and `NUDGEBEE_CALLBACK_TOKEN` can only submit assessments for their respective branch. The callback body must carry the same incident ID, evidence version, SHA-256, exact evidence refs, actual model ID, and proposed action. NudgeBee also supplies timestamped capacity context.

The executor is restricted to context `kind-agent-mvp`, namespace `agent-mvp`, source Job `oom-demo`, image `oom-lab:0.1`, one new Job with 256Mi request/384Mi limit, and one attempt. It rechecks the original pod UID and `OOMKilled` state and checks node request headroom. It will not act on Docker-only evidence or a second incident for an already-recovered source Job. Verification requires Job Complete, exit code 0, and the `RESULT` log marker.

## Current local evidence

The 128 MiB Docker run was confirmed `OOMKilled=true`, exit 137. The identical image completed at 384 MiB. In KinD, `oom-demo` was confirmed `OOMKilled`, exit 137, and incident `736fd97b-71a4-4ba5-a582-15735910f8e4` was dispatched to both A2A wrappers. JarvisLabs Gemma 4 26B returned a structured OOM analysis from that real evidence. The Kepler war room and NudgeBee branch still need genuine assessments before this incident can qualify for automatic recovery.

