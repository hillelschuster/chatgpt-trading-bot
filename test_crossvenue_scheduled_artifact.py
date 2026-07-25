import unittest
from unittest.mock import patch

from crossvenue_scheduled_artifact import (
    choose_canonical_artifact,
    find_canonical,
    newest_named_artifact,
    run_is_canonical,
)


class ScheduledArtifactSelectionTest(unittest.TestCase):
    branch = "main"
    workflow = ".github/workflows/crossvenue-probe.yml"

    @staticmethod
    def artifact(ident, run_id, created_at, expired=False, name="crossvenue-series"):
        return {
            "id": ident,
            "name": name,
            "created_at": created_at,
            "expired": expired,
            "workflow_run": {"id": run_id},
            "archive_download_url": f"https://api.github.test/artifacts/{ident}/zip",
        }

    def run(self, ident=10, event="schedule", status="completed", conclusion="success",
            branch="main", path=".github/workflows/crossvenue-probe.yml"):
        return {
            "id": ident,
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
            20: self.run(20, event="workflow_dispatch"),
            10: self.run(10, event="schedule"),
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

    def test_newest_named_artifact_ignores_expired_and_wrong_name(self):
        payload = {"artifacts": [
            self.artifact(1, 10, "2026-07-25T06:05:00Z"),
            self.artifact(2, 10, "2026-07-25T06:10:00Z", expired=True),
            self.artifact(3, 10, "2026-07-25T06:15:00Z", name="diagnostic"),
        ]}
        self.assertEqual(1, newest_named_artifact(payload, "crossvenue-series")["id"])

    @patch("crossvenue_scheduled_artifact.request_json")
    def test_queries_successful_scheduled_runs_before_artifacts(self, request):
        older = self.run(10)
        newer_without_artifact = self.run(20)
        request.side_effect = [
            {"workflow_runs": [newer_without_artifact, older]},
            {"artifacts": []},
            {"artifacts": [self.artifact(1, 10, "2026-07-25T06:05:00Z")]},
        ]
        chosen = find_canonical("owner/repo", "crossvenue-series", "token",
                                self.branch, self.workflow)
        self.assertEqual(1, chosen["id"])
        first_url = request.call_args_list[0].args[0]
        self.assertIn("event=schedule", first_url)
        self.assertIn("status=success", first_url)
        self.assertIn("branch=main", first_url)
        self.assertNotIn("/actions/artifacts?", first_url)

    @patch("crossvenue_scheduled_artifact.request_json")
    def test_paginates_successful_runs_without_repository_artifact_cap(self, request):
        page_one = [self.run(i) for i in range(100, 200)]
        old = self.run(9)
        request.side_effect = [
            {"workflow_runs": page_one},
            *({"artifacts": []} for _ in page_one),
            {"workflow_runs": [old]},
            {"artifacts": [self.artifact(9, 9, "2026-07-20T00:00:00Z")]},
        ]
        chosen = find_canonical("owner/repo", "crossvenue-series", "token",
                                self.branch, self.workflow, max_pages=2)
        self.assertEqual(9, chosen["id"])
        self.assertIn("page=2", request.call_args_list[101].args[0])


if __name__ == "__main__":
    unittest.main()
