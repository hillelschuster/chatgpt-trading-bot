import unittest

from crossvenue_artifact import choose_artifact


class ArtifactSelectionTest(unittest.TestCase):
    def artifact(self, ident, run, created, expired=False):
        return {"id": ident, "created_at": created, "expired": expired,
                "workflow_run": {"id": run}}

    def test_skips_newer_failed_run(self):
        artifacts = [self.artifact(2, 20, "2026-07-23T20:00:00Z"),
                     self.artifact(1, 10, "2026-07-23T19:00:00Z")]
        runs = {20: {"status": "completed", "conclusion": "failure", "event": "schedule"},
                10: {"status": "completed", "conclusion": "success", "event": "schedule"}}
        self.assertEqual(1, choose_artifact(artifacts, runs)["id"])

    def test_skips_in_progress_and_pull_request(self):
        artifacts = [self.artifact(3, 30, "2026-07-23T21:00:00Z"),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z"),
                     self.artifact(1, 10, "2026-07-23T19:00:00Z")]
        runs = {30: {"status": "in_progress", "conclusion": None, "event": "schedule"},
                20: {"status": "completed", "conclusion": "success", "event": "pull_request"},
                10: {"status": "completed", "conclusion": "success", "event": "workflow_dispatch"}}
        self.assertEqual(1, choose_artifact(artifacts, runs)["id"])

    def test_skips_expired_and_missing_run(self):
        artifacts = [self.artifact(3, 30, "2026-07-23T21:00:00Z", expired=True),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z")]
        self.assertIsNone(choose_artifact(artifacts, {}))

    def test_newest_success_wins(self):
        artifacts = [self.artifact(1, 10, "2026-07-23T19:00:00Z"),
                     self.artifact(2, 20, "2026-07-23T20:00:00Z")]
        runs = {10: {"status": "completed", "conclusion": "success", "event": "schedule"},
                20: {"status": "completed", "conclusion": "success", "event": "schedule"}}
        self.assertEqual(2, choose_artifact(artifacts, runs)["id"])


if __name__ == "__main__":
    unittest.main()
