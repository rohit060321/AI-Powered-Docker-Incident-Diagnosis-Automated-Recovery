"""Local bridge HTTP API and two project-owned A2A wrapper endpoints."""
from __future__ import annotations

import hmac
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import core
from .model_client import analyze


def load_env(path="mvp/.env.local"):
    if Path(path).exists():
        for raw in Path(path).read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def agent_card(agent, base):
    names = {"rubix": "Kepler War Room adapter", "nudgebee": "NudgeBee investigation adapter"}
    return {"name": names[agent], "description": "Project-owned wrapper for independent OOM incident assessment.",
            "supportedInterfaces": [{"url": f"{base}/a2a/{agent}", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}],
            "version": "0.1.0", "capabilities": {"streaming": False, "pushNotifications": False},
            "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
            "security": [{"bearer": []}], "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [{"id": "oom-assessment", "name": "OOM incident assessment",
                        "description": "Investigate supplied immutable evidence and return a proposed recovery action.",
                        "tags": ["kubernetes", "incident", "oom"]}]}


def a2a_task(record, agent):
    task_id = record["a2a_tasks"][agent]
    assessment = record["assessments"].get(agent)
    status = "TASK_STATE_COMPLETED" if assessment else "TASK_STATE_WORKING"
    task = {"id": task_id, "contextId": record["id"], "status": {"state": status}}
    if assessment:
        task["artifacts"] = [{"artifactId": f"assessment-{agent}", "name": "assessment",
                              "parts": [{"data": assessment, "metadata": {"mimeType": "application/json"}}]}]
    return {"task": task}


def send_webhook(task):
    url = os.environ.get("NUDGEBEE_WEBHOOK_URL", "")
    if not url:
        return {"sent": False, "reason": "NUDGEBEE_WEBHOOK_URL not configured"}
    callback = os.environ.get("PUBLIC_BRIDGE_URL", "").rstrip("/")
    if not callback:
        return {"sent": False, "reason": "PUBLIC_BRIDGE_URL not configured"}
    payload = {"incident_task": task, "callback_url": f"{callback}/incidents/{task['incident_id']}/assessments/nudgebee"}
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("NUDGEBEE_WEBHOOK_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urlopen(req, timeout=15) as res:
        return {"sent": True, "http_status": res.status}


class Handler(BaseHTTPRequestHandler):
    server_version = "AcceptanceBridge/0.1"

    def log_message(self, fmt, *args):
        # Avoid logging bearer credentials, request bodies, and incident evidence.
        print(fmt % args)

    def reply(self, code, value, content_type="application/json"):
        payload = value.encode() if content_type.startswith("text/") else json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self, scope="BRIDGE_TOKEN"):
        token = os.environ.get(scope, "")
        actual = self.headers.get("Authorization", "")
        return bool(token and len(token) >= 24 and hmac.compare_digest(actual, f"Bearer {token}"))

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 2_000_000:
            raise ValueError("invalid request length")
        return json.loads(self.rfile.read(length) or b"{}")

    def handle_route(self, method):
        path = urlparse(self.path).path
        if method == "GET" and path == "/health":
            return self.reply(200, {"ok": True, "execution_mode": os.environ.get("EXECUTION_MODE", "dry-run")})
        if method == "GET" and path == "/":
            return self.reply(200, (Path(__file__).parent / "review.html").read_text(), "text/html; charset=utf-8")
        if method == "GET" and path.startswith("/a2a/") and path.endswith("/.well-known/agent-card.json"):
            agent = path.split("/")[2]
            if agent not in core.ALLOWED_AGENTS:
                raise ValueError("unknown agent")
            base = (os.environ.get("PUBLIC_BRIDGE_URL") or f"http://{self.headers.get('Host', '127.0.0.1:8765')}").rstrip("/")
            return self.reply(200, agent_card(agent, base))
        parts = path.strip("/").split("/")
        assessment_scope = None
        if method == "POST" and len(parts) == 4 and parts[0] == "incidents" and parts[2] == "assessments":
            assessment_scope = {"rubix": "RUBIX_SUBMIT_TOKEN", "nudgebee": "NUDGEBEE_CALLBACK_TOKEN"}.get(parts[3])
        if not (self.authorized() or (assessment_scope and self.authorized(assessment_scope))):
            return self.reply(401, {"error": "valid bridge bearer token required"})
        if method == "GET" and path == "/incidents":
            return self.reply(200, [{"id": r["id"], "status": r["status"], "task": {"created_at": r["task"]["created_at"]}} for r in core.list_incidents()])
        if method == "POST" and path == "/incidents":
            return self.reply(201, core.create_incident(self.body()["evidence"]))
        if len(parts) >= 2 and parts[0] == "incidents":
            incident_id = parts[1]
            if len(parts) == 2 and method == "GET":
                return self.reply(200, core.load(incident_id))
            if len(parts) == 3 and parts[2] == "task" and method == "GET":
                return self.reply(200, core.load(incident_id)["task"])
            if len(parts) == 3 and parts[2] == "analyze" and method == "POST":
                return self.reply(200, analyze(core.load(incident_id)["task"]))
            if len(parts) == 4 and parts[2] == "assessments" and method == "POST":
                record = core.submit_assessment(incident_id, parts[3], self.body())
                if record["status"] == "accepted" and not record["execution"] and os.environ.get("EXECUTION_MODE") == "live":
                    threading.Thread(target=auto_recover, args=(incident_id,), daemon=True).start()
                return self.reply(200, record)
            if len(parts) == 3 and parts[2] == "dispatch" and method == "POST":
                return self.reply(200, self.dispatch(incident_id))
            if len(parts) == 3 and parts[2] == "execute" and method == "POST":
                return self.reply(200, core.execute(incident_id))
            if len(parts) == 3 and parts[2] == "verify" and method == "POST":
                return self.reply(200, core.verify(incident_id))
            if len(parts) == 3 and parts[2] == "decision" and method == "POST":
                return self.reply(200, self.decide(incident_id, self.body()))
        if len(parts) >= 3 and parts[0] == "a2a" and parts[1] in core.ALLOWED_AGENTS:
            agent = parts[1]
            if len(parts) == 3 and parts[2] == "message:send" and method == "POST":
                return self.reply(200, self.a2a_send(agent, self.body()), "application/a2a+json")
            if len(parts) == 4 and parts[2] == "tasks" and method == "GET":
                for record in core.list_incidents():
                    if record["a2a_tasks"].get(agent) == parts[3]:
                        return self.reply(200, a2a_task(record, agent), "application/a2a+json")
                raise ValueError("unknown A2A task")
        return self.reply(404, {"error": "route not found"})

    def a2a_send(self, agent, data):
        message = data.get("message", {})
        if message.get("role") != "ROLE_USER" or not message.get("messageId"):
            raise ValueError("A2A message must have ROLE_USER and messageId")
        raw = next((part["text"] for part in message.get("parts", []) if "text" in part), None)
        if raw is None:
            raise ValueError("A2A message needs a JSON text part")
        task = json.loads(raw)
        record = core.load(task["incident_id"])
        if record["task"] != task:
            raise ValueError("A2A task does not match frozen incident task")
        with core.LOCK:
            record = core.load(task["incident_id"])
            record["a2a_tasks"].setdefault(agent, str(uuid.uuid4()))
            core.event(record, "a2a_send", {"agent": agent, "task_id": record["a2a_tasks"][agent]})
            core.save(record)
        return a2a_task(record, agent)

    def dispatch(self, incident_id):
        record = core.load(incident_id)
        task = record["task"]
        base = f"http://127.0.0.1:{os.environ.get('BRIDGE_PORT', '8765')}"
        token = os.environ["BRIDGE_TOKEN"]
        results = {}
        for agent in core.ALLOWED_AGENTS:
            card_url = f"{base}/a2a/{agent}/.well-known/agent-card.json"
            with urlopen(card_url, timeout=5) as response:
                card = json.load(response)
            message = {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                                   "parts": [{"text": json.dumps(task)}]}}
            req = Request(card["supportedInterfaces"][0]["url"] + "/message:send",
                          data=json.dumps(message).encode(), headers={"Content-Type": "application/a2a+json",
                                                               "Authorization": f"Bearer {token}"})
            with urlopen(req, timeout=5) as response:
                results[agent] = json.load(response)["task"]["id"]
        # The webhook is an acknowledgement only. Assessment arrives later via callback.
        try:
            webhook = send_webhook(task)
        except Exception as exc:
            webhook = {"sent": False, "reason": str(exc)}
        return {"incident_id": incident_id, "a2a_task_ids": results, "nudgebee_webhook": webhook}

    def decide(self, incident_id, body):
        with core.LOCK:
            record = core.load(incident_id)
            if record["status"] != "review_required":
                raise ValueError("human decision is only available for held incidents")
            if record["decision"]:
                return record
            if body.get("plan_sha256") != record["comparison"]["plan_sha256"]:
                raise ValueError("plan hash mismatch")
            if body.get("decision") not in ("approve", "reject"):
                raise ValueError("decision must be approve or reject")
            record["decision"] = {"value": body["decision"], "plan_sha256": body["plan_sha256"],
                                  "at": core.utcnow(), "note": body.get("note", "")}
            # A held plan never executes automatically. Approval is an audit record for an
            # operator to resolve with a new evidence version and two fresh assessments.
            record["status"] = "human_approved_for_reassessment" if body["decision"] == "approve" else "rejected"
            core.event(record, "human_decision", record["decision"])
            core.save(record)
            return record

    def do_GET(self):
        try:
            self.handle_route("GET")
        except ValueError as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(500, {"error": str(exc)})

    def do_POST(self):
        try:
            self.handle_route("POST")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(500, {"error": str(exc)})


def main():
    load_env()
    token = os.environ.get("BRIDGE_TOKEN", "")
    if len(token) < 24 or token.startswith("replace-"):
        raise SystemExit("set a random BRIDGE_TOKEN (at least 24 characters) in mvp/.env.local")
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Bridge listening on http://{host}:{port} ({os.environ.get('EXECUTION_MODE', 'dry-run')})", flush=True)
    server.serve_forever()


def auto_recover(incident_id):
    try:
        core.execute(incident_id)
        core.verify(incident_id)
    except Exception as exc:
        with core.LOCK:
            record = core.load(incident_id)
            if not record["execution"]:
                record["status"] = "review_required"
                core.event(record, "automatic_execution_held", {"reason": str(exc)})
                core.save(record)


if __name__ == "__main__":
    main()
