"""Kepler terminal handoff: validate and submit the war-room lead's final JSON."""
import argparse
import json
from pathlib import Path

from mvp.bridge import core
from mvp.bridge.server import load_env
from mvp.cli import api


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("incident_id")
    parser.add_argument("assessment_json", type=Path)
    args = parser.parse_args()
    task = api("GET", f"/incidents/{args.incident_id}/task")
    body = json.loads(args.assessment_json.read_text())
    core.validate_assessment(task, "rubix", body)
    result = api("POST", f"/incidents/{args.incident_id}/assessments/rubix", body,
                 "RUBIX_SUBMIT_TOKEN")
    print(json.dumps({"incident_id": result["id"], "status": result["status"],
                      "assessment_sha256": core.digest(body)}, indent=2))


if __name__ == "__main__":
    main()

