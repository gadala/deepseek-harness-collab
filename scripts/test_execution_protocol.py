"""Deterministic regression tests; never launch Harness or call a model."""
import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import execution_protocol as ep


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = self.root / "batch.json"
        self.snapshot = {"baseline": "head+dirty-digest", "interfaces": {"api": "v1-digest"}}
        ep.initialize(self.registry, self.snapshot)
        self.gate = patch.object(ep, "time_gate", return_value={"status": "allow"})
        self.gate.start()
        self.addCleanup(self.gate.stop)
        self.card = {
            "schemaVersion": 1, "taskId": "A", "attemptId": "A-1", "department": "implementation",
            "cwd": str(self.root), "goal": "implement bounded change", "nonGoals": ["deployment"],
            "readSet": ["src.py"], "writeSet": ["src.py", "result.log"],
            "snapshot": self.snapshot, "dependencies": [], "risks": [], "unknowns": [],
            "checks": ["worker", "scope", "negative", "contract", "independent", "integration"],
            "permissions": {"gitIndex": False, "deploy": False, "recursiveDelegation": False},
        }

    def artifact(self, name="proof.log", text="real evidence"):
        p = self.root / name
        p.write_text(text, encoding="utf-8")
        return {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}

    def stop(self, task="A", attempt="A-1", phase="delivered", process="stopped"):
        ep.update(self.registry, {"taskId": task, "attemptId": attempt, "phase": phase,
                                 "process": process, "exitCode": 0,
                                 "descendants": "stopped", "evidence": self.artifact("lifecycle.log"),
                                 "risks": [], "unknowns": []})

    def result(self):
        proof = self.artifact()
        return {"schemaVersion": 1, "taskId": "A", "attemptId": "A-1",
                "snapshot": copy.deepcopy(self.snapshot), "reviewer": "codex",
                "artifacts": [proof], "risks": [], "unknowns": [],
                "checks": [{"name": name, "command": "independent check " + name,
                            "exitCode": 0, "evidence": proof,
                            "performedBy": "worker" if name == "worker" else "codex"}
                           for name in self.card["checks"]]}

    def deliver(self):
        ep.reserve(self.registry, self.card)
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "running",
                                 "process": "running", "exitCode": None, "descendants": "unknown",
                                 "runtime": {"handle": "test-exec-handle", "sessionId": None, "children": []},
                                 "evidence": self.artifact("start.log"), "risks": [], "unknowns": []})
        self.stop()

    def test_success_and_short_handoff(self):
        self.deliver()
        ep.accept(self.registry, self.result())
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["acceptance"], "accepted")
        h = ep.handoff(self.registry)
        self.assertEqual(h["snapshot"], self.snapshot)
        self.assertEqual(h["tasks"][0]["taskId"], "A")
        self.assertIn("receipt", h["tasks"][0])

    def test_duplicate_dispatch_rejected(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, self.card)

    def test_overlap_rejected(self):
        ep.reserve(self.registry, self.card)
        c = dict(self.card, taskId="B", attemptId="B-1")
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, c)

    def test_disjoint_writes_allowed(self):
        ep.reserve(self.registry, self.card)
        ep.reserve(self.registry, dict(self.card, taskId="B", attemptId="B-1", writeSet=["other.py"], readSet=["other.py"]))

    def test_unknown_keeps_reservation(self):
        ep.reserve(self.registry, self.card)
        self.stop(phase="unknown", process="unknown")
        with self.assertRaises(ep.ProtocolError):
            ep.release(self.registry, "A", "A-1", self.artifact())
        with self.assertRaises(ep.ProtocolError):
            ep.reserve(self.registry, dict(self.card, taskId="B", attemptId="B-1"))
        self.assertEqual(ep.handoff(self.registry)["tasks"][0]["phase"], "unknown")

    def test_no_automatic_retry_after_release(self):
        ep.reserve(self.registry, self.card)
        self.stop(phase="failed", process="not_started")
        ep.release(self.registry, "A", "A-1", self.artifact())
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, self.card)
        ep.reserve(self.registry, dict(self.card, attemptId="A-2", retryReason="confirmed not started"))

    def test_running_cannot_be_released(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError): ep.release(self.registry, "A", "A-1", self.artifact())

    def test_message_delivery_not_acceptance(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, self.result())

    def test_missing_check_rejected(self):
        self.deliver()
        r = self.result(); r["checks"].pop()
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, r)

    def test_failed_test_even_zero_process_exit(self):
        self.deliver()
        r = self.result(); r["checks"][0]["exitCode"] = 1
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, r)

    def test_worker_cannot_self_accept(self):
        self.deliver()
        r = self.result(); r["reviewer"] = "worker"
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, r)

    def test_independent_checks_cannot_be_worker(self):
        self.deliver()
        r = self.result(); r["checks"][-1]["performedBy"] = "worker"
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, r)

    def test_unknown_cannot_be_accepted(self):
        self.deliver()
        r = self.result(); r["unknowns"] = ["consumer not tested"]
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, r)

    def test_changed_evidence_is_stale(self):
        self.deliver(); ep.accept(self.registry, self.result())
        (self.root / "proof.log").write_text("changed", encoding="utf-8")
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["acceptance"], "stale")

    def test_interface_refresh_invalidates_pass(self):
        self.deliver(); ep.accept(self.registry, self.result())
        ep.refresh(self.registry, dict(self.snapshot, interfaces={"api": "v2"}))
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["acceptance"], "stale")
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, self.result())

    def test_dependency_must_be_current_accepted_and_released(self):
        ep.reserve(self.registry, self.card)
        c = dict(self.card, taskId="B", attemptId="B-1", writeSet=["other.py"], dependencies=["A"])
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, c)

    def test_gate_checked_before_every_reserve(self):
        with patch.object(ep, "time_gate", return_value={"status": "rest"}):
            with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, self.card)
        self.assertEqual(ep.inspect(self.registry)["tasks"], [])

    def test_old_snapshot_rejected(self):
        c = copy.deepcopy(self.card); c["snapshot"]["baseline"] = "old"
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, c)

    def test_missing_permission_or_quality_gate_rejected(self):
        for key in ("permissions", "checks", "nonGoals"):
            c = dict(self.card); c.pop(key)
            with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, c)
        c = dict(self.card, checks=["worker"])
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, c)

    def test_unsafe_write_paths_rejected(self):
        for path in ("../escape", "*.py", str(self.root.parent / "escape"), "."):
            with self.subTest(path=path), self.assertRaises(ep.ProtocolError):
                ep.reserve(self.registry, dict(self.card, writeSet=[path]))

    def test_directory_write_rejected(self):
        (self.root / "dir").mkdir()
        with self.assertRaises(ep.ProtocolError):
            ep.reserve(self.registry, dict(self.card, writeSet=["dir"]))

    def test_duplicate_write_alias_rejected(self):
        with self.assertRaises(ep.ProtocolError):
            ep.reserve(self.registry, dict(self.card, writeSet=["src.py", "./src.py"]))

    def test_forged_hash_rejected(self):
        self.deliver()
        r = self.result(); r["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, r)

    def test_illegal_transition_rejected(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError): self.stop()

    def test_attempt_mismatch_rejected(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError): self.stop(attempt="wrong", phase="unknown", process="unknown")

    def test_stale_lock_does_not_auto_release(self):
        self.registry.with_suffix(".json.lock").write_text("old", encoding="utf-8")
        with self.assertRaises(ep.ProtocolError): ep.reserve(self.registry, self.card)

    def test_handoff_preserves_risks_unknowns_and_permissions(self):
        c = dict(self.card, risks=["existing failure"], unknowns=["unconfirmed start"])
        ep.reserve(self.registry, c)
        h = ep.handoff(self.registry)["tasks"][0]
        self.assertEqual(h["risks"], c["risks"])
        self.assertEqual(h["unknowns"], c["unknowns"])
        self.assertEqual(h["permissions"], c["permissions"])
        self.assertIn("checks", h)

    def test_atomic_competing_reservations_only_one_succeeds(self):
        def run(i):
            try:
                ep.reserve(self.registry, dict(self.card, taskId=str(i), attemptId=str(i)))
                return True
            except ep.ProtocolError: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(run, [1, 2])), 1)
        self.assertEqual(len(ep.inspect(self.registry)["tasks"]), 1)


    def test_reserved_is_not_safe_without_start_reconciliation(self):
        ep.reserve(self.registry, self.card)
        state = ep.inspect(self.registry)["tasks"][0]
        self.assertEqual(state["process"], "unknown")

    def test_workspace_change_invalidates_pass(self):
        self.deliver(); ep.accept(self.registry, self.result())
        (self.root / "src.py").write_text("changed", encoding="utf-8")
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["acceptance"], "stale")

    def test_fast_worker_changes_do_not_block_observed_start(self):
        ep.reserve(self.registry, self.card)
        ep.preflight(self.registry, "A", "A-1")
        (self.root / "src.py").write_text("fast worker output", encoding="utf-8")
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "running",
            "process": "running", "descendants": "unknown", "exitCode": None,
            "runtime": {"handle": "h", "sessionId": None, "children": []},
            "evidence": self.artifact(), "risks": [], "unknowns": []})
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["phase"], "running")

    def test_descendants_unknown_cannot_settle(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError):
            ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "failed",
                "process": "stopped", "descendants": "unknown", "exitCode": 1,
                "evidence": self.artifact(), "risks": [], "unknowns": []})

    def test_incomplete_handoff_rejected(self):
        ep.reserve(self.registry, self.card)
        h = ep.handoff(self.registry); del h["tasks"][0]["unknowns"]
        with self.assertRaises(ep.ProtocolError): ep.validate_handoff(self.registry, h)

    def test_dependency_changes_invalidate_consumer(self):
        self.deliver(); ep.accept(self.registry, self.result())
        ep.release(self.registry, "A", "A-1", self.artifact("release.log"))
        b = dict(self.card, taskId="B", attemptId="B-1", writeSet=["other.py"], dependencies=["A"])
        ep.reserve(self.registry, b)
        ep.update(self.registry, {"taskId": "B", "attemptId": "B-1", "phase": "running",
            "process": "running", "descendants": "none", "exitCode": None,
            "runtime": {"handle": "b", "sessionId": None, "children": []},
            "evidence": self.artifact("b-start.log"), "risks": [], "unknowns": []})
        self.stop("B", "B-1")
        r = self.result(); r.update(taskId="B", attemptId="B-1")
        ep.accept(self.registry, r)
        (self.root / "proof.log").write_text("upstream proof replaced", encoding="utf-8")
        self.assertEqual(ep.inspect(self.registry)["tasks"][1]["acceptance"], "stale")

    def test_receipts_and_registry_cannot_be_worker_writes(self):
        with self.assertRaises(ep.ProtocolError):
            ep.reserve(self.registry, dict(self.card, writeSet=[str(self.registry)]))

    def test_conflicting_shared_resources(self):
        ep.reserve(self.registry, dict(self.card, resources=["tcp:3000"]))
        with self.assertRaises(ep.ProtocolError):
            ep.reserve(self.registry, dict(self.card, taskId="B", attemptId="B-1", writeSet=["other.py"],
                readSet=["other.py"], resources=["tcp:3000"]))

    def test_same_attempt_on_different_task_is_rejected(self):
        ep.reserve(self.registry, self.card)
        with self.assertRaises(ep.ProtocolError):
            ep.reserve(self.registry, dict(self.card, taskId="B", writeSet=["other.py"], readSet=["other.py"]))

    def test_acceptance_must_cover_unchanged_shared_risks(self):
        self.deliver()
        with ep.transaction(self.registry) as d: d["tasks"][0]["risks"] = ["known residual"]
        with self.assertRaises(ep.ProtocolError): ep.accept(self.registry, self.result())

    def test_preflight_checks_time_and_drift(self):
        ep.reserve(self.registry, self.card)
        self.assertEqual(ep.preflight(self.registry, "A", "A-1")["status"], "allow")
        with patch.object(ep, "time_gate", return_value={"status": "rest"}):
            with self.assertRaises(ep.ProtocolError): ep.preflight(self.registry, "A", "A-1")
        (self.root / "src.py").write_text("drift", encoding="utf-8")
        with self.assertRaises(ep.ProtocolError): ep.preflight(self.registry, "A", "A-1")

    def test_no_silent_risk_or_unknown_removal(self):
        ep.reserve(self.registry, dict(self.card, unknowns=["unconfirmed workspace"]))
        with self.assertRaises(ep.ProtocolError): self.stop(phase="failed", process="not_started")

    def test_observed_running_can_be_recorded_during_rest(self):
        ep.reserve(self.registry, self.card)
        with patch.object(ep, "time_gate", return_value={"status": "rest"}):
            ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "running",
                "process": "running", "descendants": "unknown", "exitCode": None,
                "runtime": {"handle": "observed-before-rest", "sessionId": None, "children": []},
                "evidence": self.artifact(), "risks": [], "unknowns": []})

    def test_runtime_identity_cannot_change_or_forget_children(self):
        self.deliver()
        # Separate live task to exercise observed continuation identity.
        c = dict(self.card, taskId="B", attemptId="B-1", readSet=["b.py"], writeSet=["b.py"])
        ep.reserve(self.registry, c)
        r = {"taskId": "B", "attemptId": "B-1", "phase": "running", "process": "running",
            "descendants": "running", "exitCode": None, "risks": [], "unknowns": [],
            "evidence": self.artifact("b.log"),
            "runtime": {"handle": "handle-b", "sessionId": "real-parent", "children": ["child-1"]}}
        ep.update(self.registry, r)
        for runtime in ({"handle": "other", "sessionId": "real-parent", "children": ["child-1"]},
                        {"handle": "handle-b", "sessionId": "other", "children": ["child-1"]},
                        {"handle": "handle-b", "sessionId": "real-parent", "children": []}):
            with self.assertRaises(ep.ProtocolError): ep.update(self.registry, dict(r, runtime=runtime))

    def test_handoff_uses_latest_attempt_with_history_index(self):
        ep.reserve(self.registry, self.card)
        self.stop(phase="failed", process="not_started")
        ep.release(self.registry, "A", "A-1", self.artifact())
        ep.reserve(self.registry, dict(self.card, attemptId="A-2", retryReason="confirmed never started"))
        h = ep.handoff(self.registry)
        self.assertEqual(len(h["tasks"]), 1)
        self.assertEqual(h["tasks"][0]["attemptId"], "A-2")
        self.assertEqual(h["registry"], str(self.registry.resolve()))

    def test_cli_roundtrip_and_duplicate_exit(self):
        import subprocess, sys
        tool = str(Path(ep.__file__))
        card_path = self.root / "card.json"
        card_path.write_text(json.dumps(self.card), encoding="utf-8")
        def command(*args):
            return subprocess.run([sys.executable, "-B", "-X", "utf8", tool, *args],
                                  capture_output=True, text=True, encoding="utf-8")
        r = command("validate", "--record", str(card_path))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Failed mutations must be machine-readable, not an unhandled traceback.
        ep.reserve(self.registry, self.card)
        r = command("release", "--registry", str(self.registry), "--record", str(card_path))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout)["status"], "blocked")
        r = command("inspect", "--registry", str(self.registry))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("events", json.loads(r.stdout))

    def test_handoff_keeps_latest_runtime_risk_state(self):
        ep.reserve(self.registry, self.card)
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "unknown",
            "process": "unknown", "descendants": "unknown", "exitCode": None,
            "evidence": self.artifact(), "risks": ["new risk"], "unknowns": ["start unclear"]})
        h = ep.handoff(self.registry)["tasks"][0]
        self.assertEqual(h["risks"], ["new risk"])
        self.assertEqual(h["unknowns"], ["start unclear"])

    def test_summary_does_not_load_full_cards_into_output(self):
        ep.reserve(self.registry, self.card)
        s = ep.summary(self.registry)
        self.assertEqual(s["tasks"][0]["taskId"], "A")
        self.assertNotIn("card", s["tasks"][0])
        self.assertNotIn("events", s)

    def test_preflight_reserves_one_launch_check_not_repeat_permit(self):
        ep.reserve(self.registry, self.card)
        ep.preflight(self.registry, "A", "A-1")
        with self.assertRaises(ep.ProtocolError): ep.preflight(self.registry, "A", "A-1")

    def test_risk_resolution_is_retained_in_handoff(self):
        ep.reserve(self.registry, dict(self.card, unknowns=["workspace unknown"]))
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "unknown",
            "process": "unknown", "descendants": "unknown", "exitCode": None,
            "evidence": self.artifact(), "risks": [], "unknowns": [], "resolution": "verified workspace"})
        self.assertEqual(ep.handoff(self.registry)["tasks"][0]["resolution"], "verified workspace")

    def test_one_shot_completion_without_fake_running_state(self):
        ep.reserve(self.registry, self.card)
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "delivered",
            "process": "stopped", "descendants": "none", "exitCode": 0,
            "runtime": {"handle": "completed-real-exec", "sessionId": None, "children": []},
            "evidence": self.artifact("one-shot.log"), "risks": [], "unknowns": []})
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["phase"], "delivered")

    def test_parent_session_can_be_learned_once_from_null(self):
        ep.reserve(self.registry, self.card)
        r = {"taskId": "A", "attemptId": "A-1", "phase": "running", "process": "running",
            "descendants": "unknown", "exitCode": None, "evidence": self.artifact(),
            "risks": [], "unknowns": [], "runtime": {"handle": "h", "sessionId": None, "children": []}}
        ep.update(self.registry, r)
        r["runtime"]["sessionId"] = "discovered-real-parent"
        ep.update(self.registry, r)
        self.assertEqual(ep.inspect(self.registry)["tasks"][0]["runtime"]["sessionId"], "discovered-real-parent")

    def test_two_os_processes_share_one_atomic_reservation(self):
        import subprocess, sys
        program = (
            "import sys,json; sys.path.insert(0,sys.argv[1]); import execution_protocol as ep; "
            "ep.time_gate=lambda: {'status':'allow'}; "
            "ep.reserve(sys.argv[2],json.load(open(sys.argv[3],encoding='utf-8')))"
        )
        files = []
        for i in range(2):
            p = self.root / ("process-card-" + str(i) + ".json")
            p.write_text(json.dumps(dict(self.card, taskId=str(i), attemptId=str(i))), encoding="utf-8")
            files.append(p)
        children = [subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-c", program,
                    str(Path(ep.__file__).parent), str(self.registry), str(p)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE) for p in files]
        for child in children: child.communicate(timeout=30)
        self.assertEqual(sum(child.returncode == 0 for child in children), 1)
        self.assertEqual(len(ep.inspect(self.registry)["tasks"]), 1)

    def test_resolution_can_clear_unknown_but_not_auto_release(self):
        ep.reserve(self.registry, dict(self.card, unknowns=["start unclear"]))
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "failed",
            "process": "not_started", "descendants": "none", "exitCode": None,
            "evidence": self.artifact(), "risks": [], "unknowns": [],
            "resolution": "confirmed no parent or descendants launched"})
        self.assertFalse(ep.inspect(self.registry)["tasks"][0]["released"])
        ep.release(self.registry, "A", "A-1", self.artifact("release-proof.log"))
        self.assertTrue(ep.inspect(self.registry)["tasks"][0]["released"])

    def test_known_started_execution_cannot_be_relabeled_not_started(self):
        ep.reserve(self.registry, self.card)
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "running",
            "process": "running", "descendants": "none", "exitCode": None,
            "runtime": {"handle": "h", "sessionId": None, "children": []},
            "evidence": self.artifact(), "risks": [], "unknowns": []})
        with self.assertRaises(ep.ProtocolError): self.stop(phase="failed", process="not_started")

    def test_known_child_cannot_be_declared_no_descendants(self):
        ep.reserve(self.registry, self.card)
        ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "running",
            "process": "running", "descendants": "running", "exitCode": None,
            "runtime": {"handle": "h", "sessionId": None, "children": ["child-1"]},
            "evidence": self.artifact(), "risks": [], "unknowns": []})
        with self.assertRaises(ep.ProtocolError):
            ep.update(self.registry, {"taskId": "A", "attemptId": "A-1", "phase": "delivered",
                "process": "stopped", "descendants": "none", "exitCode": 0,
                "evidence": self.artifact(), "risks": [], "unknowns": []})


if __name__ == "__main__": unittest.main()
