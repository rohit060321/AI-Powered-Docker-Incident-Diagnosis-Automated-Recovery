# Kepler war room run card

This is the **operator-started RubixKube branch**. The project-owned A2A adapter already has the immutable incident task. Kepler is not assumed to expose a headless API. Open this workspace in Kepler, run the CLI below in its terminal, and show the same incident in Observe mode. The Kepler war room lead produces one final JSON assessment; only the bridge can execute a recovery Job.

1. Start a war room in Observe mode for the incident ID. Attach the `mvp/evidence/<incident-id>.json` task file. Do not paste secrets or `.env.local` into prompts.
2. Assign three distinct investigations:
   - **Log and termination state:** cite `termination.reason`, `termination.exitCode`, and numbered log lines. Distinguish OOM evidence from exit code alone.
   - **Workload configuration:** inspect image, target memory, 64Mi request, 128Mi limit, and whether the pod is still the original failed pod.
   - **Recovery critique:** assess the fixed 256Mi request/384Mi limit, one attempt, possible node headroom issues, and what requires human review.
3. Let the lead compare the findings. Ask the local JarvisLabs helper for a *separate* structured opinion:

   ```sh
   python3 -m mvp.cli analyze INCIDENT_ID
   ```

   Record the actual returned `model_id`. A model suggestion is evidence for discussion, not authorization to act.
   For an incident-bound JSON draft instead, run `python3 -m mvp.adapters.draft_rubix INCIDENT_ID`. It validates the model response and saves it in the ignored evidence directory; it does not submit it.
4. Generate an incident-bound template and replace the placeholder fields with the war room's genuine conclusion:

   ```sh
   python3 -m mvp.adapters.make_template rubix INCIDENT_ID > mvp/evidence/rubix-assessment.json
   ```

   Keep `evidence_refs` restricted to references present in the task. If the war room disagrees with the fixed action, change the proposed `action`; the bridge will hold it for review.
5. Submit once from Kepler's terminal:

   ```sh
   python3 -m mvp.adapters.kepler_submit INCIDENT_ID mvp/evidence/rubix-assessment.json
   ```

When the RubixKube Enterprise custom REST integration is available, expose the bridge task/analyze/assessment operations there as a supported tool integration. That is an optional upgrade; the Kepler terminal handoff is the tested MVP path.

