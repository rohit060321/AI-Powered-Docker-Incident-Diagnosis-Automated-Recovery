"""OpenAI-compatible JarvisLabs analysis helper. Model output is advisory only."""
import json
import os
import subprocess
from urllib.request import Request, urlopen


def analyze(task):
    base = os.environ.get("JARVIS_BASE_URL", "").rstrip("/")
    model = os.environ.get("JARVIS_MODEL", "")
    if not model:
        raise ValueError("JARVIS_MODEL is required")
    prompt = {
        "incident_id": task["incident_id"], "evidence_sha256": task["evidence_sha256"],
        "evidence": task["evidence"], "allowed_action": task["allowed_action"],
        "instruction": "Return a JSON object with exactly these fields: cause_code (use 'container_oom_killed' "
                       "only if termination.reason is OOMKilled), summary, evidence_refs (an array of exact "
                       "identifiers from the supplied evidence_refs array), missing_evidence (array), and action "
                       "(an object with type, namespace, target_job, memory_request_mib, memory_limit_mib, "
                       "max_attempts). Do not put values or explanations into evidence_refs identifiers. "
                       "Copy the allowed_action only if you independently endorse it; otherwise state your own "
                       "specific action. Use only provided evidence. You recommend, never execute.",
        "evidence_refs": task["evidence_refs"],
    }
    body = {"model": model, "temperature": 0, "messages": [
        {"role": "system", "content": "You are a Kubernetes incident analyst. Return a JSON object only."},
        {"role": "user", "content": json.dumps(prompt)}]}
    key = os.environ.get("JARVIS_API_KEY", "")
    if key:
        if not base:
            raise ValueError("JARVIS_BASE_URL is required with JARVIS_API_KEY")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        request = Request(base + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
        with urlopen(request, timeout=45) as response:
            result = json.load(response)
    else:
        # The configured JarvisLabs CLI carries its own credentials. Pipe evidence
        # on stdin so it does not appear in shell history or the process argv.
        process = subprocess.run(["jl", "models", "chat", model,
            "Analyze the incident JSON from stdin. Return only the requested JSON object.",
            "--system", "You are a Kubernetes incident analyst. Return a JSON object only.",
            "--max-tokens", "1000", "--no-thinking", "--json"],
            input=json.dumps(prompt), text=True, capture_output=True, timeout=90)
        if process.returncode:
            raise RuntimeError("JarvisLabs CLI request failed: " + process.stderr[-500:])
        result = json.loads(process.stdout)
    content = result["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return {"model_id": result.get("model", model), "analysis": json.loads(content),
            "usage": result.get("usage", {})}

