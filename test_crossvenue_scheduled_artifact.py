import unittest

from crossvenue_scheduled_artifact import (
    choose_canonical_artifact,
    run_is_canonical,
)


class ScheduledArtifactSelectionTest(unittest.TestCase):
    branch = "main"
    workflow = ".github/workflows/crossvenue-probe.yml"

    @staticmethod
    def artifact(ident, run_id, created_at, expired=False):
        return {
            "id": ident,
            "created_at": created_at,
            "expired": expired,
            "workflow_run": {"id": run_id},
        }

    def run(self, event="schedule", status="completed", conclusion="success",
            branch="main", path=".github/workflows/crossvenue-probe.yml"):
        return {
            "event": event,
            "status": status,
            "conclusion": conclusion,
            "head_branch": branch,
            "path": path,
        }

    def test_manual_artifact_is_never_canonical(self):
        self.assertFalse(run_is_canonical(
            self.run(event="workflow_dispatch"), self.branch, self.workflow
        ))

    def test_falls_back_past_newer_manual_artifact(self):
        artifacts = [
            self.artifact(2, 20, "2026-07-25T06:10:00Z"),
            self.artifact(1, 10, "2026-07-25T06:05:00Z"),
        ]
        runs = {
            20: self.run(event="workflow_dispatch"),
            10: self.run(event="schedule"),
        }
        chosen = choose_canonical_artifact(
            artifacts, runs, self.branch, self.workflow
        )
        self.assertEqual(1, chosen["id"])

    def test_rejects_failed_in_progress_wrong_branch_and_wrong_workflow(self):
        variants = [
            self.run(conclusion="failure"),
            self.run(status="in_progress", conclusion=None),
            self.run(branch="experiment"),
            self.run(path=".github/workflows/other.yml"),
            self.run(event="pull_request"),
        ]
        for run in variants:
            with self.subTest(run=run):
                self.assertFalse(run_is_canonical(run, self.branch, self.workflow))

    def test_newest_valid_scheduled_artifact_wins(self):
        artifacts = [
            self.artifact(1, 10, "2026-07-25T06:05:00Z"),
            self.artifact(2, 20, "2026-07-25T06:10:00Z"),
        ]
        runs = {10: self.run(), 20: self.run()}
        chosen = choose_canonical_artifact(
            artifacts, runs, self.branch, self.workflow
        )
        self.assertEqual(2, chosen["id"])

    def test_expired_or_missing_run_is_rejected(self):
        artifacts = [
            self.artifact(2, 20, "2026-07-25T06:10:00Z", expired=True),
            self.artifact(1, 10, "2026-07-25T06:05:00Z"),
        ]
        self.assertIsNone(choose_canonical_artifact(
            artifacts, {}, self.branch, self.workflow
        ))


if __name__ == "__main__":
    unittest.main()
