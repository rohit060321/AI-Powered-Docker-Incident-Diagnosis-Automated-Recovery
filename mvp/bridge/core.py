"""Dependency-free incident contract, persistence, comparison, and controlled executor."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

NAMESPACE = "agent-mvp"
CLUSTER_CONTEXT = "kind-agent-mvp"
SOURCE_JOB = "oom-demo"
IMAGE = "oom-lab:0.1"
TARGET_MIB = 192
REQUEST_MIB = 256
LIMIT_MIB = 384
ALLOWED_AGENTS = ("rubix", "nudgebee")
LOCK = threading.RLock()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def db_path():
    path = Path(os.environ.get("BRIDGE_DB", "mvp/evidence/bridge.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect():
    con = sqlite3.connect(db_path(), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
    return con


def save(record):
    with LOCK, connect() as con:
        con.execute("INSERT OR REPLACE INTO incidents VALUES (?, ?)", (record["id"], canonical(record)))


def load(incident_id):
    with connect() as con:
        row = con.execute("SELECT record FROM incidents WHERE id=?", (incident_id,)).fetchone()
    if not row:
        raise ValueError("unknown incident")
    return json.loads(row["record"])


def list_incidents(limit=50):
    with connect() as con:
        query = "SELECT record FROM incidents ORDER BY rowid DESC" + (f" LIMIT {int(limit)}" if limit else "")
        rows = con.execute(query).fetchall()
    return [json.loads(row["record"]) for row in rows]


def event(record, kind, detail):
    record["events"].append({"at": utcnow(), "kind": kind, "detail": detail})


def run(*args, input_text=None, timeout=25):
    proc = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"{' '.join(args[:4])}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def kubectl_json(*args):
    return json.loads(run("kubectl", "--context", CLUSTER_CONTEXT, *args, "-o", "json"))


def collect_kubernetes():
    job = kubectl_json("get", "job", SOURCE_JOB, "-n", NAMESPACE)
    pods = kubectl_json("get", "pods", "-n", NAMESPACE, "-l", f"job-name={SOURCE_JOB}")["items"]
    if len(pods) != 1:
        raise ValueError(f"expected one failed pod, found {len(pods)}")
    pod = pods[0]
    container = pod["spec"]["containers"][0]
    state = pod.get("status", {}).get("containerStatuses", [{}])[0].get("state", {}).get("terminated", {})
    if state.get("reason") != "OOMKilled":
        raise ValueError(f"pod termination reason is {state.get('reason')!r}, not OOMKilled")
    if container.get("image") != IMAGE:
        raise ValueError("unexpected source image")
    logs = run("kubectl", "--context", CLUSTER_CONTEXT, "logs", pod["metadata"]["name"], "-n", NAMESPACE, timeout=15)
    numbered = [{"line": i, "text": line} for i, line in enumerate(logs.splitlines(), 1)]
    all_events = kubectl_json("get", "events", "-n", NAMESPACE)["items"]
    event_summary = [{"reason": item.get("reason"), "message": item.get("message"),
                      "at": item.get("eventTime") or item.get("lastTimestamp")}
                     for item in all_events if item.get("involvedObject", {}).get("uid") in
                     (pod["metadata"]["uid"], job["metadata"]["uid"])]
    resources = container.get("resources", {})
    evidence = {
        "source": "kubernetes", "namespace": NAMESPACE, "job_name": SOURCE_JOB,
        "job_uid": job["metadata"]["uid"], "pod_name": pod["metadata"]["name"],
        "pod_uid": pod["metadata"]["uid"], "node_name": pod["spec"].get("nodeName"),
        "image": IMAGE, "image_id": pod.get("status", {}).get("containerStatuses", [{}])[0].get("imageID"),
        "target_mib": TARGET_MIB, "requests": resources.get("requests", {}),
        "limits": resources.get("limits", {}), "termination": state,
        "logs": numbered, "log_sha256": hashlib.sha256(logs.encode()).hexdigest(),
        "events": event_summary,
        "collected_at": utcnow(),
    }
    return evidence


def collect_docker(container_name="oom-lab-fail"):
    inspected = json.loads(run("docker", "inspect", container_name))[0]
    state = inspected["State"]
    if not state.get("OOMKilled"):
        raise ValueError("Docker inspect does not confirm OOMKilled")
    logs = run("docker", "logs", container_name)
    return {
        "source": "docker", "namespace": NAMESPACE, "job_name": SOURCE_JOB,
        "job_uid": inspected["Id"], "pod_name": container_name, "pod_uid": inspected["Id"],
        "node_name": None, "image": IMAGE, "image_id": inspected.get("Image"),
        "target_mib": TARGET_MIB, "requests": {"memory": "64Mi"},
        "limits": {"memory": "128Mi"},
        "termination": {"reason": "OOMKilled", "exitCode": state["ExitCode"]},
        "logs": [{"line": i, "text": line} for i, line in enumerate(logs.splitlines(), 1)],
        "log_sha256": hashlib.sha256(logs.encode()).hexdigest(), "events": [], "collected_at": utcnow(),
    }


def create_incident(evidence):
    if evidence.get("termination", {}).get("reason") != "OOMKilled":
        raise ValueError("OOMKilled state is required")
    if evidence.get("image") != IMAGE or evidence.get("namespace") != NAMESPACE:
        raise ValueError("fixture image and namespace must match")
    incident_id = str(uuid.uuid4())
    evidence_hash = digest(evidence)
    refs = ["termination.reason", "termination.exitCode", "limits.memory", "log_sha256"]
    refs += [f"log:{item['line']}" for item in evidence.get("logs", [])]
    refs += [f"event:{index}" for index, _ in enumerate(evidence.get("events", []), 1)]
    task = {
        "incident_id": incident_id, "evidence_version": 1, "evidence_sha256": evidence_hash,
        "objective": "Diagnose the failure and propose one exact recovery action. Cite evidence and uncertainty.",
        "allowed_action": {"type": "create_recovery_job", "namespace": NAMESPACE,
                           "target_job": SOURCE_JOB, "memory_request_mib": REQUEST_MIB,
                           "memory_limit_mib": LIMIT_MIB, "max_attempts": 1},
        "evidence": evidence, "evidence_refs": refs, "created_at": utcnow(),
    }
    record = {"id": incident_id, "task": task, "assessments": {}, "status": "investigating",
              "comparison": None, "decision": None, "execution": None, "a2a_tasks": {}, "events": []}
    event(record, "created", {"evidence_sha256": evidence_hash})
    save(record)
    evidence_dir = db_path().parent
    (evidence_dir / f"{incident_id}.json").write_text(json.dumps(task, indent=2))
    return record


def validate_assessment(task, agent, body):
    if agent not in ALLOWED_AGENTS:
        raise ValueError("unknown agent")
    if not isinstance(body, dict):
        raise ValueError("assessment must be an object")
    for key, expected in (("incident_id", task["incident_id"]),
                          ("evidence_version", task["evidence_version"]),
                          ("evidence_sha256", task["evidence_sha256"]), ("agent_id", agent)):
        if body.get(key) != expected:
            raise ValueError(f"{key} mismatch")
    if not isinstance(body.get("cause_code"), str) or not body["cause_code"]:
        raise ValueError("cause_code is required")
    if not isinstance(body.get("summary"), str) or not body["summary"].strip():
        raise ValueError("summary is required")
    refs = body.get("evidence_refs")
    if not isinstance(refs, list) or "termination.reason" not in refs or not set(refs).issubset(task["evidence_refs"]):
        raise ValueError("evidence_refs must cite task evidence including termination.reason")
    action = body.get("action")
    required_action = ("type", "namespace", "target_job", "memory_request_mib", "memory_limit_mib", "max_attempts")
    if not isinstance(action, dict) or any(key not in action for key in required_action):
        raise ValueError("action must include all plan fields")
    if type(action["memory_request_mib"]) is not int or type(action["memory_limit_mib"]) is not int:
        raise ValueError("memory values must be integer MiB")
    if not isinstance(body.get("model_id"), str) or not body["model_id"].strip():
        raise ValueError("actual model_id is required")
    if agent == "nudgebee":
        capacity = body.get("capacity_check", {})
        if not isinstance(capacity, dict) or "has_headroom" not in capacity or "observed_at" not in capacity:
            raise ValueError("NudgeBee must report timestamped capacity_check")
    return body


def submit_assessment(incident_id, agent, body):
    with LOCK:
        record = load(incident_id)
        if record["status"] in ("executed", "verified", "execution_failed"):
            raise ValueError("incident already executed")
        validate_assessment(record["task"], agent, body)
        existing = record["assessments"].get(agent)
        if existing and existing != body:
            raise ValueError("assessment already submitted; revisions require a new incident")
        if existing == body:
            return record
        record["assessments"][agent] = body
        event(record, "assessment", {"agent": agent, "sha256": digest(body)})
        compare(record)
        save(record)
        return record


def compare(record):
    assessments = record["assessments"]
    if len(assessments) < 2:
        return
    rubix, nudge = assessments["rubix"], assessments["nudgebee"]
    reasons = []
    if (rubix["cause_code"], rubix["action"]) != (nudge["cause_code"], nudge["action"]):
        reasons.append("assessments disagree")
    if rubix["cause_code"] != "container_oom_killed":
        reasons.append("cause is outside OOM recovery policy")
    if rubix["action"] != record["task"]["allowed_action"]:
        reasons.append("proposed action is outside fixed executor policy")
    capacity = nudge.get("capacity_check", {})
    if capacity.get("has_headroom") is not True:
        reasons.append("NudgeBee did not confirm headroom")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(capacity["observed_at"])).total_seconds()
        if age < 0 or age > 600:
            reasons.append("capacity observation is stale")
    except (KeyError, TypeError, ValueError):
        reasons.append("capacity observation time is invalid")
    if rubix.get("missing_evidence") or nudge.get("missing_evidence"):
        reasons.append("assessment reports missing evidence")
    plan = record["task"]["allowed_action"]
    record["comparison"] = {"agreed": not reasons, "reasons": reasons,
                            "plan": plan, "plan_sha256": digest(plan)}
    record["status"] = "accepted" if not reasons else "review_required"
    event(record, "comparison", record["comparison"])


def memory_mib(quantity):
    value = str(quantity)
    for suffix, factor in (("Ki", 1/1024), ("Mi", 1), ("Gi", 1024), ("Ti", 1024*1024)):
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * factor
    return float(value) / 1024 / 1024


def check_live_preconditions(record):
    evidence = record["task"]["evidence"]
    if evidence["source"] != "kubernetes":
        raise ValueError("Docker-only evidence cannot authorize Kubernetes execution")
    job = kubectl_json("get", "job", SOURCE_JOB, "-n", NAMESPACE)
    pods = kubectl_json("get", "pods", "-n", NAMESPACE, "-l", f"job-name={SOURCE_JOB}")["items"]
    if job["metadata"]["uid"] != evidence["job_uid"] or len(pods) != 1:
        raise ValueError("source Job or pod changed")
    pod = pods[0]
    if pod["metadata"]["uid"] != evidence["pod_uid"]:
        raise ValueError("source pod UID changed")
    state = pod.get("status", {}).get("containerStatuses", [{}])[0].get("state", {}).get("terminated", {})
    if state.get("reason") != "OOMKilled":
        raise ValueError("source pod is no longer OOMKilled")
    nodes = kubectl_json("get", "nodes")["items"]
    all_pods = kubectl_json("get", "pods", "-A")["items"]
    eligible = []
    for node in nodes:
        name = node["metadata"]["name"]
        if node.get("spec", {}).get("unschedulable") or any(t.get("effect") == "NoSchedule" for t in node.get("spec", {}).get("taints", [])):
            continue
        alloc = memory_mib(node["status"]["allocatable"]["memory"])
        reserved = sum(memory_mib(c.get("resources", {}).get("requests", {}).get("memory", "0"))
                       for p in all_pods if p.get("spec", {}).get("nodeName") == name
                       and p.get("status", {}).get("phase") not in ("Succeeded", "Failed")
                       for c in p.get("spec", {}).get("containers", []))
        if alloc - reserved >= REQUEST_MIB:
            eligible.append({"node": name, "headroom_mib": round(alloc - reserved, 1)})
    if not eligible:
        raise ValueError("no schedulable node has room for the recovery request")
    return eligible


def recovery_manifest(record):
    incident_id = record["id"]
    short = incident_id.split("-")[0]
    name = f"oom-recovery-{short}"
    return {"apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": name, "namespace": NAMESPACE,
                         "labels": {"app": "oom-lab", "incident": short,
                                    "plan-hash": record["comparison"]["plan_sha256"][:16]}},
            "spec": {"backoffLimit": 0, "template": {"spec": {"restartPolicy": "Never",
                      "containers": [{"name": "worker", "image": IMAGE, "imagePullPolicy": "Never",
                                      "env": [{"name": "TARGET_MIB", "value": str(TARGET_MIB)}],
                                      "resources": {"requests": {"cpu": "50m", "memory": f"{REQUEST_MIB}Mi"},
                                                    "limits": {"cpu": "500m", "memory": f"{LIMIT_MIB}Mi"}}}]}}}}


def execute(incident_id):
    with LOCK:
        record = load(incident_id)
        if record["execution"]:
            return record
        if record["status"] != "accepted" or not record["comparison"]["agreed"]:
            raise ValueError("only matching accepted plans may execute")
        if os.environ.get("EXECUTION_MODE", "dry-run") != "live":
            raise ValueError("execution is dry-run; set EXECUTION_MODE=live after cluster validation")
        source_uid = record["task"]["evidence"]["job_uid"]
        if any(other["id"] != incident_id and other.get("execution") and
               other["task"]["evidence"]["job_uid"] == source_uid for other in list_incidents(None)):
            raise ValueError("this source Job already has a recovery execution")
        eligible = check_live_preconditions(record)
        manifest = recovery_manifest(record)
        name = manifest["metadata"]["name"]
        # Server-side create fails on an existing name; never replace a Job.
        result = run("kubectl", "--context", CLUSTER_CONTEXT, "create", "-f", "-", input_text=canonical(manifest))
        job = kubectl_json("get", "job", name, "-n", NAMESPACE)
        record["execution"] = {"job_name": name, "job_uid": job["metadata"]["uid"],
                               "created_at": utcnow(), "eligible_nodes": eligible, "kubectl": result.strip()}
        record["status"] = "executed"
        event(record, "executed", record["execution"])
        save(record)
    return record


def verify(incident_id):
    with LOCK:
        record = load(incident_id)
        if not record["execution"]:
            raise ValueError("no recovery Job")
        name = record["execution"]["job_name"]
        if record["status"] == "verified":
            return record
        try:
            run("kubectl", "--context", CLUSTER_CONTEXT, "wait", "-n", NAMESPACE, "--for=condition=complete", "--timeout=90s", f"job/{name}", timeout=100)
            job = kubectl_json("get", "job", name, "-n", NAMESPACE)
            pods = kubectl_json("get", "pods", "-n", NAMESPACE, "-l", f"job-name={name}")["items"]
            if len(pods) != 1 or job["metadata"]["uid"] != record["execution"]["job_uid"]:
                raise ValueError("recovery Job identity changed")
            state = pods[0]["status"]["containerStatuses"][0]["state"]["terminated"]
            logs = run("kubectl", "--context", CLUSTER_CONTEXT, "logs", pods[0]["metadata"]["name"], "-n", NAMESPACE)
            if state.get("exitCode") != 0 or "RESULT: completed memory workload" not in logs:
                raise ValueError("recovery Job lacked exit 0 or result marker")
            record["status"] = "verified"
            record["execution"]["verification"] = {"at": utcnow(), "exit_code": 0,
                                                       "result_marker": True, "pod_uid": pods[0]["metadata"]["uid"]}
        except Exception as exc:
            record["status"] = "execution_failed"
            record["execution"]["verification"] = {"at": utcnow(), "error": str(exc)}
        event(record, "verification", record["execution"]["verification"])
        save(record)
        return record
