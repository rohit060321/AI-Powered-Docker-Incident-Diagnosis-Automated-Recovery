"""Deploy the pinned official NudgeBee source chart to an adequately sized cluster."""
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

from mvp.bridge.server import load_env

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "vendor" / "nudgebee" / "deploy" / "kubernetes" / "nudgebee"


def call(*args, capture=False):
    return subprocess.run(args, check=True, text=True, capture_output=capture).stdout if capture else subprocess.run(args, check=True).returncode


def mib(quantity):
    match = re.fullmatch(r"([0-9.]+)(Ki|Mi|Gi|Ti)?", quantity)
    if not match:
        raise ValueError(f"unsupported memory quantity {quantity}")
    value, suffix = match.groups()
    return float(value) * {None: 1 / 1048576, "Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1048576}[suffix]


def main():
    load_env(str(ROOT / ".env.local"))
    context = os.environ.get("NUDGEBEE_KUBE_CONTEXT", "")
    email = os.environ.get("NUDGEBEE_ADMIN_EMAIL", "")
    if not context or not email or "@" not in email:
        raise SystemExit("set NUDGEBEE_KUBE_CONTEXT and NUDGEBEE_ADMIN_EMAIL in mvp/.env.local")
    if not CHART.exists():
        raise SystemExit("clone https://github.com/nudgebee/nudgebee into mvp/vendor/nudgebee first")
    nodes = json.loads(call("kubectl", "--context", context, "get", "nodes", "-o", "json", capture=True))["items"]
    schedulable = [n for n in nodes if not n.get("spec", {}).get("unschedulable")]
    alloc_mib = sum(mib(n["status"]["allocatable"]["memory"]) for n in schedulable)
    if len(schedulable) < 2 or alloc_mib < 12 * 1024:
        raise SystemExit(f"NudgeBee requires at least 2 nodes and 12 GiB RAM; context {context!r} has {len(schedulable)} nodes and {alloc_mib/1024:.1f} GiB allocatable. Aborting before install.")
    # The chart's persisted encryption key is generated once; the user must back it up.
    env_path = ROOT / ".env.local"
    key = os.environ.get("NUDGEBEE_ENCRYPTION_KEY", "")
    if not key:
        key = secrets.token_hex(32)
        with env_path.open("a") as handle:
            handle.write(f"\nNUDGEBEE_ENCRYPTION_KEY={key}\n")
        os.chmod(env_path, 0o600)
        print("Generated a permanent NudgeBee encryption key in ignored mvp/.env.local. Back it up securely.")
    values = {"nudgebee_secret": {"NUDGEBEE_ENCRYPTION_KEY": key},
              "admin": {"email": email}, "agent": {"enabled": True, "clusterName": "agent-mvp-observed"}}
    private_values = ROOT / "evidence" / "nudgebee-values.private.json"
    private_values.parent.mkdir(parents=True, exist_ok=True)
    private_values.write_text(json.dumps(values))
    os.chmod(private_values, 0o600)
    print(f"Deploying official source chart to {context}; verify cluster storage meets NudgeBee's 200 GB minimum.")
    call("helm", "dependency", "update", str(CHART))
    call("helm", "upgrade", "nudgebee", str(CHART), "--install", "--namespace", "nudgebee",
         "--create-namespace", "--kube-context", context, "-f", str(private_values),
         "--wait", "--timeout", "20m")
    print("Helm install completed. Verify pods and port-forward svc/app:80 to localhost:3000.")


if __name__ == "__main__":
    main()

