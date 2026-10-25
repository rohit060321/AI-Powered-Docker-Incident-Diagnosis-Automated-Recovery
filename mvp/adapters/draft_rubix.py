"""Generate a JarvisLabs model draft for review in the Kepler war room; never submit it."""
import argparse
import json
from pathlib import Path

from mvp.bridge import core
from mvp.bridge.model_client import analyze
from mvp.bridge.server import load_env
from mvp.cli import api


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("incident_id")
    args = parser.parse_args()
    task = api("GET", f"/incidents/{args.incident_id}/task")
    result = analyze(task)
    draft = {"incident_id": task["incident_id"], "evidence_version": task["evidence_version"],
             "evidence_sha256": task["evidence_sha256"], "agent_id": "rubix",
             "model_id": result["model_id"], **result["analysis"]}
    core.validate_assessment(task, "rubix", draft)
    path = Path("mvp/evidence") / f"rubix-model-draft-{args.incident_id}.json"
    path.write_text(json.dumps(draft, indent=2))
    print(f"Validated model draft saved to {path}. Review in Kepler before submission.")
    print(f"JarvisLabs model: {result['model_id']}; prompt tokens: {result['usage'].get('prompt_tokens')}; output tokens: {result['usage'].get('completion_tokens')}")


if __name__ == "__main__":
    main()

