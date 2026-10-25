import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from mvp.bridge import core


class BridgeDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BRIDGE_DB"] = str(Path(self.tmp.name) / "test.db")
        os.environ["EXECUTION_MODE"] = "dry-run"
        evidence = {
            "source": "kubernetes", "namespace": "agent-mvp", "job_name": "oom-demo",
            "job_uid": "job-1", "pod_name": "pod-1", "pod_uid": "pod-uid-1",
            "node_name": "worker", "image": "oom-lab:0.1", "image_id": "digest",
            "target_mib": 192, "requests": {"memory": "64Mi"}, "limits": {"memory": "128Mi"},
            "termination": {"reason": "OOMKilled", "exitCode": 137},
            "logs": [{"line": 1, "text": "allocated_mib=120"}], "log_sha256": "a" * 64,
            "collected_at": core.utcnow(),
        }
        self.record = core.create_incident(evidence)

    def tearDown(self):
        self.tmp.cleanup()

    def assessment(self, agent, **changes):
        task = self.record["task"]
        result = {"incident_id": self.record["id"], "evidence_version": 1,
                  "evidence_sha256": task["evidence_sha256"], "agent_id": agent,
                  "model_id": "test-model", "cause_code": "container_oom_killed",
                  "summary": "Pod state confirms OOMKilled at 128Mi.",
                  "evidence_refs": ["termination.reason", "limits.memory", "log:1"],
                  "missing_evidence": [], "action": task["allowed_action"].copy()}
        if agent == "nudgebee":
            result["capacity_check"] = {"has_headroom": True, "observed_at": core.utcnow(),
                                        "source": "test fixture"}
        result.update(changes)
        return result

    def test_agreement_accepts_but_dry_run_cannot_execute(self):
        core.submit_assessment(self.record["id"], "rubix", self.assessment("rubix"))
        result = core.submit_assessment(self.record["id"], "nudgebee", self.assessment("nudgebee"))
        self.assertEqual(result["status"], "accepted")
        with self.assertRaisesRegex(ValueError, "dry-run"):
            core.execute(self.record["id"])

    def test_action_disagreement_holds(self):
        core.submit_assessment(self.record["id"], "rubix", self.assessment("rubix"))
        other = self.assessment("nudgebee")
        other["action"]["memory_limit_mib"] = 512
        result = core.submit_assessment(self.record["id"], "nudgebee", other)
        self.assertEqual(result["status"], "review_required")
        with self.assertRaisesRegex(ValueError, "accepted"):
            core.execute(self.record["id"])

    def test_stale_capacity_holds(self):
        core.submit_assessment(self.record["id"], "rubix", self.assessment("rubix"))
        result = core.submit_assessment(self.record["id"], "nudgebee",
            self.assessment("nudgebee", capacity_check={"has_headroom": True,
                "observed_at": "2020-01-01T00:00:00+00:00"}))
        self.assertIn("capacity observation is stale", result["comparison"]["reasons"])

    def test_duplicate_callback_does_not_change_audit(self):
        assessment = self.assessment("rubix")
        first = core.submit_assessment(self.record["id"], "rubix", assessment)
        second = core.submit_assessment(self.record["id"], "rubix", assessment)
        self.assertEqual(first["events"], second["events"])


if __name__ == "__main__":
    unittest.main()
