"""Generate an incident-bound assessment skeleton for either vendor branch."""
import argparse
import json

from mvp.bridge import core
from mvp.bridge.server import load_env
from mvp.cli import api


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=core.ALLOWED_AGENTS)
    parser.add_argument("incident_id")
    args = parser.parse_args()
    task = api("GET", f"/incidents/{args.incident_id}/task")
    result = {
        "incident_id": task["incident_id"], "evidence_version": task["evidence_version"],
        "evidence_sha256": task["evidence_sha256"], "agent_id": args.agent,
        "model_id": "REPLACE_WITH_ACTUAL_MODEL_ID", "cause_code": "container_oom_killed",
        "summary": "REPLACE_WITH_INDEPENDENT_FINDING",
        "evidence_refs": ["termination.reason", "limits.memory"],
        "missing_evidence": [], "action": task["allowed_action"],
    }
    if args.agent == "nudgebee":
        result["capacity_check"] = {"has_headroom": False,
                                    "observed_at": "REPLACE_WITH_LIVE_UTC_TIMESTAMP",
                                    "source": "REPLACE_WITH_NUDGEBEE_METRIC_OR_QUERY"}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

