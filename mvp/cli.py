"""Local operator CLI. Run with: python3 -m mvp.cli <command> ..."""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from .bridge import core
from .bridge.model_client import analyze
from .bridge.server import load_env


def api(method, path, body=None, token_name="BRIDGE_TOKEN"):
    base = f"http://127.0.0.1:{os.environ.get('BRIDGE_PORT', '8765')}"
    headers = {"Authorization": "Bearer " + os.environ[token_name], "Content-Type": "application/json"}
    req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                  headers=headers, method=method)
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def main():
    load_env()
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("collect-k8s")
    subs.add_parser("collect-docker")
    for name in ("task", "analyze", "dispatch", "status", "verify", "execute"):
        sub = subs.add_parser(name)
        sub.add_argument("incident_id")
    sub = subs.add_parser("submit")
    sub.add_argument("agent", choices=core.ALLOWED_AGENTS)
    sub.add_argument("incident_id")
    sub.add_argument("assessment_json", type=Path)
    args = parser.parse_args()
    if args.command == "collect-k8s":
        result = api("POST", "/incidents", {"evidence": core.collect_kubernetes()})
    elif args.command == "collect-docker":
        result = api("POST", "/incidents", {"evidence": core.collect_docker()})
    elif args.command == "task":
        result = api("GET", f"/incidents/{args.incident_id}/task")
    elif args.command == "analyze":
        result = api("POST", f"/incidents/{args.incident_id}/analyze", {})
    elif args.command == "status":
        result = api("GET", f"/incidents/{args.incident_id}")
    elif args.command == "submit":
        token_name = "RUBIX_SUBMIT_TOKEN" if args.agent == "rubix" else "NUDGEBEE_CALLBACK_TOKEN"
        result = api("POST", f"/incidents/{args.incident_id}/assessments/{args.agent}",
                     json.loads(args.assessment_json.read_text()), token_name)
    else:
        result = api("POST", f"/incidents/{args.incident_id}/{args.command}", {})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

