import unittest

from crossvenue_artifact import choose_artifact, run_is_approved


class ArtifactSelectionTest(unittest.TestCase):
    def artifact(self, ident, run, created, expired=False):
        return {"id": ident, "created_at": created, "expired": expired,
                "workflow_run": {"id": run}}

    def run(self, conclusion="success", event="schedule", status="completed",
            branch="main", path=".github/workflows/crossvenue-probe.yml"):
        return {"status": status, "conclusion": conclusion, "event": event,
                "head_branch": branch, "path": path}

    def test_skips_newer_failed_run(self):
        artifacts = [self.artifact(2, 20, "2026-07-23T20:00:00Z"),
                     self.artifact(1, 10, "2026-07-23T19:00:00Z")]
        runs = {20: self.run(conclusion="failure"), 10: self.run()}
        self.assertEqual(1, choose_artifact(artifacts, runs, "main",
                                           ".github/workflows/crossvenue-probe.yml")["id"])

    def test_skips_in_progress_and_pull_request(self):
        artifacts = [self.artifact(3, 30, "2026-07-23T21:00:00Z"),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z"),
                     self.artifact(1, 10, "2026-07-23T19:00:00Z")]
        runs = {30: self.run(status="in_progress", conclusion=None),
                20: self.run(event="pull_request"),
                10: self.run(event="workflow_dispatch")}
        self.assertEqual(1, choose_artifact(artifacts, runs, "main",
                                           ".github/workflows/crossvenue-probe.yml")["id"])

    def test_skips_wrong_branch_and_workflow(self):
        artifacts = [self.artifact(3, 30, "2026-07-23T21:00:00Z"),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z"),
                     self.artifact(1, 10, "2026-07-23T19:00:00Z")]
        runs = {30: self.run(branch="experiment"),
                20: self.run(path=".github/workflows/other.yml"),
                10: self.run()}
        self.assertEqual(1, choose_artifact(artifacts, runs, "main",
                                           ".github/workflows/crossvenue-probe.yml")["id"])

    def test_skips_expired_and_missing_run(self):
        artifacts = [self.artifact(3, 30, "2026-07-23T21:00:00Z", expired=True),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z")]
        self.assertIsNone(choose_artifact(artifacts, {}, "main",
                                          ".github/workflows/crossvenue-probe.yml"))

    def test_newest_approved_success_wins(self):
        artifacts = [self.artifact(1, 10, "2026-07-23T19:00:00Z"),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z")]
        runs = {10: self.run(), 20: self.run()}
        self.assertEqual(2, choose_artifact(artifacts, runs, "main",
                                           ".github/workflows/crossvenue-probe.yml")["id"])

    def test_approval_requires_exact_provenance(self):
        self.assertTrue(run_is_approved(self.run(), "main",
                                        ".github/workflows/crossvenue-probe.yml"))
        self.assertFalse(run_is_approved(self.run(branch="dev"), "main",
                                         ".github/workflows/crossvenue-probe.yml"))
        self.assertFalse(run_is_approved(self.run(path="other.yml"), "main",
                                         ".github/workflows/crossvenue-probe.yml"))


if __name__ == "__main__":
    unittest.main()
