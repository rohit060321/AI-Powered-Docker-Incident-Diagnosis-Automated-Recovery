# NudgeBee workflow run card

Use the **same frozen `incident_task`** received in the bridge's webhook POST. Configure the NudgeBee agent on the KinD cluster per the [official local setup](https://docs.nudgebee.com/docs/installation/agent/local-setup/). KinD has inventory, events, and metrics, but not the eBPF node agent; this demo does not depend on an hour of rightsizing history.

Create a workflow named `oom_incident_assessment`:

1. Webhook trigger accepts JSON with `incident_task` and `callback_url`. Authenticate the trigger and put its URL/token in `mvp/.env.local` as `NUDGEBEE_WEBHOOK_URL` and `NUDGEBEE_WEBHOOK_TOKEN`.
2. AI investigation reads the frozen evidence and independently checks the `agent-mvp/oom-demo` Job, pod termination, pod events, declared limits, and node metrics. Pass the JarvisLabs OpenAI-compatible endpoint through NudgeBee's supported LLM gateway **if the tenant permits it**; otherwise record the actual configured model in `model_id`.
3. Capacity step reports `has_headroom` as a boolean, `observed_at` as a UTC ISO-8601 time, and a concrete `source` (metric/query). A missing or stale observation must be `false` or included in `missing_evidence`.
4. HTTP task POSTs a JSON assessment to `callback_url` with `Authorization: Bearer <NUDGEBEE_CALLBACK_TOKEN>` and `Content-Type: application/json`. Configure that token in NudgeBee's secret store; do not put the bridge admin token there. The exact response body is shaped like the output of:

   ```sh
   python3 -m mvp.adapters.make_template nudgebee INCIDENT_ID
   ```

   Populate every placeholder from actual workflow results. The `incident_id`, `evidence_version`, and `evidence_sha256` must be copied unchanged from `incident_task`. Cite `termination.reason`; include any other cited `evidence_refs` from the task. The action may disagree, but only an exact allowed action plus fresh confirmed headroom can execute.
5. The webhook's synchronous response is only trigger acknowledgement. The bridge waits for the separate assessment callback. Duplicate identical callbacks are idempotent; a changed result needs a new incident/evidence version.

The callback URL needs a reachable HTTPS base (`PUBLIC_BRIDGE_URL`). Keep the bridge private until you have a controlled tunnel or hosted endpoint, and expose only the required route to the NudgeBee workflow. [Webhook triggers](https://docs.nudgebee.com/docs/features/workflow-builder/triggers/) and [workflow tasks](https://docs.nudgebee.com/docs/features/workflow-builder/workflow-tasks-reference/) describe the vendor configuration.

