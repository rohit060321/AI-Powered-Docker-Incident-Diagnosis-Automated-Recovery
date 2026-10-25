#!/usr/bin/env python3
"""Render the last run into a Markdown card you can paste into a Kepler war room.

    python3 card.py            # prints the card
    python3 card.py > out/card.md
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def load(name: str) -> dict:
    path = OUT / name
    return json.loads(path.read_text()) if path.is_file() else {}


def main() -> None:
    ev = load("evidence.json")
    props = load("proposals.json").get("proposals", {})
    verdict = load("verdict.json")
    check = load("verification.json")

    a = props.get("diagnostician", {})
    b = props.get("challenger", {})

    print("# Incident — OOMKilled container\n")
    print("## Evidence (given identically to both analysts)")
    print(f"- container: `{ev.get('container')}`  image: `{ev.get('image')}`")
    print(f"- exit code: `{ev.get('exit_code')}`   OOMKilled: `{ev.get('oom_killed')}`")
    print(f"- limit: `{ev.get('memory_limit_human')}`   job asked for: `{ev.get('required_memory_mb')} MiB`")
    print(f"- evidence sha256: `{load('proposals.json').get('evidence_sha256', 'n/a')}`")
    tail = ev.get("log_tail") or []
    if tail:
        print("\n```")
        for line in tail[:1] + tail[-4:]:
            print(line)
        print("```")

    print("\n## Two independent proposals\n")
    for label, p in (("A · Diagnostician", a), ("B · Challenger", b)):
        if not p or "error" in p:
            print(f"**{label}** — no usable answer: `{(p or {}).get('error', 'missing')}`\n")
            continue
        print(f"**{label}**")
        print(f"- cause: `{p.get('cause')}`")
        print(f"- action: `{p.get('action')}`")
        print(f"- memory limit: `{p.get('memory_limit')}`")
        print(f"- confidence: `{p.get('confidence')}`")
        print(f"- reasoning: {p.get('reasoning')}\n")

    print("## Bridge verdict")
    print(f"- **{verdict.get('verdict')}** — {verdict.get('reason')}")
    compared = verdict.get("compared") or {}
    for field, cmp in compared.items():
        print(f"  - `{field}`: A={cmp.get('A')!r} B={cmp.get('B')!r} equal={cmp.get('equal')}")

    approved = verdict.get("approved") or {}
    if approved:
        print(f"\n## Action taken (exactly once)")
        print(f"```\ndocker rm -f {ev.get('container')}")
        print(f"docker run -d --name {ev.get('container')} --memory={approved.get('memory_limit')} \\")
        print(f"  -v ./oom_job:/j:ro python:3.12-slim python /j/oom.py\n```")

    if check:
        print("\n## Verification")
        print(f"- recovered: `{check.get('recovered')}`  signal: `{check.get('signal')}`")
        print(f"- OOMKilled after restart: `{check.get('oom_killed')}`  exit: `{check.get('exit_code')}`")

    print("\n## Ask of the war room")
    if verdict.get("verdict") == "AGREE":
        print("The pipeline already executed this recovery once and verified it. "
              "Review the reasoning, confirm the evidence hash matches the incident, "
              "and pin the decision. No further change should be made.")
    else:
        print("The pipeline executed nothing. Review both explanations, state which "
              "proposal you would act on and why, and queue any change for approval.")


if __name__ == "__main__":
    main()
