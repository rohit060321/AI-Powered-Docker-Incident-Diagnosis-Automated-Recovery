#!/usr/bin/env python3
"""OOM incident -> two independent proposals -> deterministic bridge -> one recovery.

    python3 pipeline.py                  full run (needs the NudgeBee gateway)
    python3 pipeline.py --conflict       force proposal B to disagree (no re-analysis)
    python3 pipeline.py --proposals F    replay saved proposals, skip the agents
    python3 pipeline.py --no-execute     stop after the verdict

Exit codes: 0 recovered, 1 not recovered, 2 setup/parse problem, 3 flagged for review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
JOB_DIR = ROOT / "oom_job"

CAUSES = ("OOM_MEMORY_LIMIT", "OOM_HOST_MEMORY", "APP_LEAK")
ACTIONS = ("RESTART_WITH_HIGHER_MEMORY_LIMIT", "RESTART_WITH_SAME_LIMIT", "NO_ACTION")
MAX_FIX = 4 * 1024 * 1024 * 1024  # 4 GiB ceiling on any approved limit


# ---------------------------------------------------------------- config

def load_env() -> dict:
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


ENV = load_env()


def cfg(key: str, default: str = "") -> str:
    return ENV.get(key, default)


# ---------------------------------------------------------------- 1. evidence

def docker(*args: str) -> str:
    res = subprocess.run(["docker", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


def collect_evidence(name: str) -> dict:
    raw = docker("inspect", name)
    state = json.loads(raw)[0]
    logs = subprocess.run(
        ["docker", "logs", "--tail", "40", name], capture_output=True, text=True
    ).stdout

    evidence = {
        "incident_id": time.strftime("inc-%Y%m%d-%H%M%S"),
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "container": name,
        "image": state["Config"]["Image"],
        "command": state["Config"].get("Cmd"),
        "memory_limit": state["HostConfig"]["Memory"],
        "memory_limit_human": human(state["HostConfig"]["Memory"]),
        "exit_code": state["State"]["ExitCode"],
        "oom_killed": state["State"]["OOMKilled"],
        "status": state["State"]["Status"],
        "log_tail": logs.strip().splitlines(),
    }
    # What the workload said it needed, not what it was allowed. The fix has to clear
    # this with headroom; the 128m limit alone would make 256m look generous.
    match = re.search(r"alloc=(\d+)MiB", logs)
    evidence["required_memory_mb"] = int(match.group(1)) if match else None
    return evidence


def human(nbytes: int) -> str:
    if nbytes % (1024 ** 3) == 0:
        return f"{nbytes // 1024 ** 3}g"
    return f"{nbytes // 1024 ** 2}m"


def evidence_hash(evidence: dict) -> str:
    blob = json.dumps(evidence, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


# ---------------------------------------------------------------- 2. agents

SCHEMA = """Answer with ONLY this JSON object, no analysis, no markdown:
{"cause":"OOM_MEMORY_LIMIT|OOM_HOST_MEMORY|APP_LEAK",
 "action":"RESTART_WITH_HIGHER_MEMORY_LIMIT|RESTART_WITH_SAME_LIMIT|NO_ACTION",
 "params":{"memory_limit":"<value like 1g>"},
 "confidence":0.0,
 "reasoning":"<one sentence citing the log lines you used>"}
memory_limit MUST be at least 25% above required_memory_mb.
Do not repeat this schema."""

ROLES = {
    "diagnostician": (
        "You are the primary on-call diagnostician. Diagnose the failed container "
        "from the evidence and recommend exactly one recovery action."
    ),
    "challenger": (
        "You are an independent reviewer. Form your own diagnosis from the evidence "
        "alone; do not assume any other analysis is correct. Recommend the action you "
        "would take if you were on call."
    ),
}


def prompt_for(role: str, evidence: dict) -> str:
    # Compact on purpose: a long prompt makes a reasoning model narrate, and the
    # answer gets truncated before the JSON.
    brief = {
        "container": evidence["container"],
        "image": evidence["image"],
        "exit_code": evidence["exit_code"],
        "oom_killed": evidence["oom_killed"],
        "memory_limit": evidence["memory_limit_human"],
        "required_memory_mb": evidence.get("required_memory_mb"),
        # First line matters: it states what the job needed to allocate. Without it the
        # model infers the requirement from the cgroup limit and under-proposes.
        "log_tail": evidence["log_tail"][:1] + evidence["log_tail"][-5:],
    }
    return (
        f"{ROLES[role]}\n\nEVIDENCE: {json.dumps(brief)}\n"
        f"{cfg('HEADROOM_RULE', '')}{SCHEMA}"
    )


def call_gateway(prompt: str) -> str:
    body = json.dumps(
        {
            "model": f"{cfg('NB_PROVIDER')}/{cfg('NB_MODEL')}",
            "temperature": 0,
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
            # Without this the model streams its whole thinking trace into `content`
            # and hits max_tokens before ever emitting the answer.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        cfg("NB_GATEWAY_URL", "http://localhost:8010") + "/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg('NB_TOKEN', 'nb-demo-token')}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise RuntimeError(f"gateway HTTP {exc.code}: {detail}") from exc

    message = (payload.get("choices") or [{}])[0].get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        # A reasoning model sometimes returns only its thinking trace.
        text = "".join(
            part.get("text", "") for part in (message.get("reasoning_details") or [])
        ).strip()
    if not text:
        raise RuntimeError(f"empty completion; message keys={sorted(message)}")
    return text


def parse_proposal(role: str, text: str) -> dict:
    """Strict-ish: pick the model's own answer object.

    Small models echo the schema before answering, so scan every decodable object and
    take the LAST one carrying the fields we asked for. No field repair: a malformed
    answer stays a no-decision.
    """
    decoder = json.JSONDecoder()
    candidates = []
    idx = 0
    while True:
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict) and "cause" in obj and "action" in obj:
            candidates.append(obj)
        idx = start + max(end, 1)
    if not candidates:
        (OUT / f"unparsed_{role}.txt").write_text(text)
        raise ValueError(f"{role}: no answer object in response (raw saved to out/)")
    data = candidates[-1]

    cause = data.get("cause")
    action = data.get("action")
    limit = (data.get("params") or {}).get("memory_limit")
    if cause not in CAUSES:
        raise ValueError(f"{role}: bad cause {cause!r}")
    if action not in ACTIONS:
        raise ValueError(f"{role}: bad action {action!r}")
    if not limit or mem_bytes(limit) is None:
        raise ValueError(f"{role}: bad memory_limit {limit!r}")
    return {
        "agent": role,
        "cause": cause,
        "action": action,
        "memory_limit": limit,
        "memory_limit_bytes": mem_bytes(limit),
        "confidence": float(data.get("confidence", 0)),
        "reasoning": str(data.get("reasoning", ""))[:800],
    }


def mem_bytes(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]i?b?)?\s*", str(value).lower())
    if not match:
        return None
    num = float(match.group(1))
    unit = match.group(2) or ""
    mult = {
        "": 1, "b": 1,
        "k": 1024, "kb": 1024, "ki": 1024, "kib": 1024,
        "m": 1024 ** 2, "mb": 1024 ** 2, "mi": 1024 ** 2, "mib": 1024 ** 2,
        "g": 1024 ** 3, "gb": 1024 ** 3, "gi": 1024 ** 3, "gib": 1024 ** 3,
        "t": 1024 ** 4, "tb": 1024 ** 4, "ti": 1024 ** 4, "tib": 1024 ** 4,
    }[unit]
    return int(num * mult)


def ask_both(evidence: dict) -> dict:
    digest = evidence_hash(evidence)
    print(f"   evidence {digest} sent to both agents")

    def one(role: str) -> dict:
        text = call_gateway(prompt_for(role, evidence))
        return parse_proposal(role, text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {r: pool.submit(one, r) for r in ("diagnostician", "challenger")}
        out = {}
        for role, fut in futures.items():
            try:
                out[role] = fut.result()
            except Exception as exc:  # noqa: BLE001 - a failed agent is a no-decision
                out[role] = {"agent": role, "error": str(exc)}
    return {"evidence_sha256": digest, "proposals": out}


# ---------------------------------------------------------------- 3. bridge

def bridge(proposals: dict, evidence: dict) -> dict:
    a = proposals.get("diagnostician", {})
    b = proposals.get("challenger", {})
    compared = {}
    for key in ("cause", "action", "memory_limit_bytes"):
        compared[key] = {"A": a.get(key), "B": b.get(key), "equal": a.get(key) == b.get(key)}

    if "error" in a or "error" in b:
        return {
            "verdict": "NO_DECISION",
            "reason": f"an agent failed: {a.get('error') or b.get('error')}",
            "compared": compared,
        }
    if not all(f["equal"] for f in compared.values()):
        differing = [k for k, f in compared.items() if not f["equal"]]
        return {
            "verdict": "DISAGREE",
            "reason": "proposals differ on: " + ", ".join(differing),
            "compared": compared,
        }

    limit = a["memory_limit_bytes"]
    current = evidence["memory_limit"]
    if a["action"] != ACTIONS[0]:
        return {"verdict": "DENIED", "reason": f"{a['action']} is not a permitted action", "compared": compared}
    if limit <= current:
        return {"verdict": "DENIED", "reason": f"{human(limit)} does not raise the limit above {human(current)}", "compared": compared}
    required = evidence.get("required_memory_mb")
    if required:
        floor = int(required * 1024 * 1024 * 1.25)
        if limit < floor:
            return {
                "verdict": "DENIED",
                "reason": (f"{human(limit)} leaves no headroom over the {required} MiB the job "
                           f"asked to allocate (need at least {human(floor)})"),
                "compared": compared,
            }
    if limit > MAX_FIX:
        return {"verdict": "DENIED", "reason": f"{human(limit)} exceeds the 4 GiB ceiling", "compared": compared}
    return {
        "verdict": "AGREE",
        "reason": f"both propose {a['action']} at {human(limit)}; permitted",
        "compared": compared,
        "approved": {"action": a["action"], "memory_limit": human(limit)},
    }


# ---------------------------------------------------------------- 4. execute

def execute_once(approved: dict) -> str:
    OUT.mkdir(exist_ok=True)
    lock = OUT / "executed.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return "skipped (already executed once)"
    with os.fdopen(fd, "w") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    name = cfg("JOB_NAME", "oom-job")
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", name,
            f"--memory={approved['memory_limit']}",
            "-e", f"ALLOC_MB={cfg('ALLOC_MB', '512')}",
            "-v", f"{JOB_DIR}:/j:ro",
            cfg("JOB_IMAGE", "python:3.12-slim"),
            "python", "/j/oom.py",
        ],
        capture_output=True, text=True, check=True,
    )
    return f"executed once with --memory={approved['memory_limit']}"


# ---------------------------------------------------------------- 5. verify

def verify(name: str, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = json.loads(docker("inspect", name))[0]["State"]
        logs = subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True
        ).stdout
        if "WORK_COMPLETE" in logs:
            return {"recovered": True, "oom_killed": state["OOMKilled"],
                    "exit_code": state["ExitCode"], "signal": "WORK_COMPLETE"}
        if state["Status"] == "exited":
            return {"recovered": False, "oom_killed": state["OOMKilled"],
                    "exit_code": state["ExitCode"], "signal": "exited without completion"}
        time.sleep(1)
    return {"recovered": False, "signal": "timeout"}


# ---------------------------------------------------------------- 6. trail

def ledger(stage: str, payload: dict) -> None:
    OUT.mkdir(exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stage": stage, **payload}
    with open(OUT / "ledger.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conflict", action="store_true", help="force B to disagree")
    ap.add_argument("--proposals", help="replay saved proposals JSON")
    ap.add_argument("--no-execute", action="store_true")
    args = ap.parse_args(argv)

    name = cfg("JOB_NAME", "oom-job")
    OUT.mkdir(exist_ok=True)

    print("1. evidence")
    evidence = collect_evidence(name)
    (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2))
    print(f"   {name}: exit={evidence['exit_code']} oom_killed={evidence['oom_killed']} "
          f"limit={evidence['memory_limit_human']}")
    ledger("incident", {"incident_id": evidence["incident_id"],
                        "evidence_sha256": evidence_hash(evidence),
                        "exit_code": evidence["exit_code"],
                        "oom_killed": evidence["oom_killed"]})

    print("2. agents")
    if args.proposals:
        proposals = json.loads(Path(args.proposals).read_text())
        print(f"   replayed from {args.proposals}")
    else:
        proposals = ask_both(evidence)
        (OUT / "proposals.json").write_text(json.dumps(proposals, indent=2))

    for role, prop in proposals["proposals"].items():
        if "error" in prop:
            print(f"   {role}: FAILED {prop['error']}")
        else:
            print(f"   {role}: {prop['cause']} / {prop['action']} / "
                  f"{prop['memory_limit']} (conf {prop['confidence']:.0%})")
        ledger("proposal", {"agent": role, "proposal": prop})

    if args.conflict:
        b = proposals["proposals"].get("challenger", {})
        if "error" not in b:
            b["memory_limit"] = "2g"
            b["memory_limit_bytes"] = mem_bytes("2g")
            print("   [--conflict] challenger proposal B mutated to 2g")

    print("3. bridge")
    verdict = bridge(proposals["proposals"], evidence)
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2))
    print(f"   {verdict['verdict']}: {verdict['reason']}")
    ledger("verdict", verdict)

    if verdict["verdict"] != "AGREE":
        print("\n   -> flagged for human review; nothing executed.")
        print("   -> Kepler war room: paste out/verdict.json + both proposals.")
        return 3

    if args.no_execute:
        return 0

    print("4. execute")
    result = execute_once(verdict["approved"])
    print(f"   {result}")
    ledger("execution", {"result": result, "approved": verdict["approved"]})

    print("5. verify")
    check = verify(name)
    (OUT / "verification.json").write_text(json.dumps(check, indent=2))
    print(f"   {check}")
    ledger("verification", check)

    return 0 if check["recovered"] else 1


if __name__ == "__main__":
    sys.exit(main())
