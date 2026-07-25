import unittest
from unittest.mock import patch

from crossvenue_scheduled_artifact import (
    artifact_belongs_to_run,
    choose_canonical_artifact,
    find_canonical,
    newest_named_artifact,
    run_is_canonical,
)


class ScheduledArtifactSelectionTest(unittest.TestCase):
    branch = "main"
    workflow = ".github/workflows/crossvenue-probe.yml"

    @staticmethod
    def artifact(ident, run_id, created_at="2026-07-25T06:05:00Z",
                 expired=False, name="crossvenue-series"):
        return {
            "id": ident,
            "name": name,
            "created_at": created_at,
            "expired": expired,
            "workflow_run": {"id": run_id},
            "archive_download_url": f"https://api.github.test/artifacts/{ident}/zip",
        }

    def run(self, ident=10, event="schedule", status="completed", conclusion="success",
            branch="main", path=".github/workflows/crossvenue-probe.yml",
            head_sha="a" * 40, created_at="2026-07-25T06:00:00Z",
            updated_at="2026-07-25T06:06:00Z"):
        return {
            "id": ident,
            "event": event,
            "status": status,
            "conclusion": conclusion,
            "head_branch": branch,
            "path": path,
            "head_sha": head_sha,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def test_manual_artifact_is_never_canonical(self):
        self.assertFalse(run_is_canonical(
            self.run(event="workflow_dispatch"), self.branch, self.workflow
        ))

    def test_rejects_failed_in_progress_wrong_branch_workflow_or_missing_sha(self):
        variants = [
            self.run(conclusion="failure"),
            self.run(status="in_progress", conclusion=None),
            self.run(branch="experiment"),
            self.run(path=".github/workflows/other.yml"),
            self.run(event="pull_request"),
            self.run(head_sha=""),
            self.run(head_sha="abc"),
        ]
        for run in variants:
            with self.subTest(run=run):
                self.assertFalse(run_is_canonical(run, self.branch, self.workflow))

    def test_artifact_requires_exact_run_and_possible_timestamp(self):
        run = self.run(10)
        self.assertTrue(artifact_belongs_to_run(self.artifact(1, 10), run))
        invalid = [
            self.artifact(1, 11),
            self.artifact(1, 10, "2026-07-25T05:59:59Z"),
            self.artifact(1, 10, "2026-07-25T06:17:00Z"),
            self.artifact(1, 10, "not-a-time"),
        ]
        for artifact in invalid:
            with self.subTest(artifact=artifact):
                self.assertFalse(artifact_belongs_to_run(artifact, run))

    def test_falls_back_past_newer_unbound_artifact(self):
        artifacts = [
            self.artifact(2, 20, "2026-07-25T06:10:00Z"),
            self.artifact(1, 10, "2026-07-25T06:05:00Z"),
        ]
        runs = {
            20: self.run(20, event="workflow_dispatch", updated_at="2026-07-25T06:11:00Z"),
            10: self.run(10),
        }
        chosen = choose_canonical_artifact(
            artifacts, runs, self.branch, self.workflow
        )
        self.assertEqual(1, chosen["id"])
        self.assertEqual(10, chosen["_canonical_run"]["id"])

    def test_newest_named_artifact_ignores_expired_wrong_name_and_wrong_run(self):
        run = self.run(10)
        payload = {"artifacts": [
            self.artifact(1, 10),
            self.artifact(2, 10, expired=True),
            self.artifact(3, 10, name="diagnostic"),
            self.artifact(4, 99),
        ]}
        chosen = newest_named_artifact(payload, "crossvenue-series", run)
        self.assertEqual(1, chosen["id"])
        self.assertEqual(run, chosen["_canonical_run"])

    @patch("crossvenue_scheduled_artifact.request_json")
    def test_queries_successful_scheduled_runs_before_artifacts(self, request):
        older = self.run(10)
        newer_without_artifact = self.run(
            20, created_at="2026-07-25T06:10:00Z", updated_at="2026-07-25T06:16:00Z"
        )
        request.side_effect = [
            {"workflow_runs": [newer_without_artifact, older]},
            {"artifacts": []},
            {"artifacts": [self.artifact(1, 10)]},
        ]
        chosen = find_canonical("owner/repo", "crossvenue-series", "token",
                                self.branch, self.workflow)
        self.assertEqual(1, chosen["id"])
        self.assertEqual("a" * 40, chosen["_canonical_run"]["head_sha"])
        first_url = request.call_args_list[0].args[0]
        self.assertIn("event=schedule", first_url)
        self.assertIn("status=success", first_url)
        self.assertIn("branch=main", first_url)
        self.assertNotIn("/actions/artifacts?", first_url)

    @patch("crossvenue_scheduled_artifact.request_json")
    def test_paginates_successful_runs_without_repository_artifact_cap(self, request):
        page_one = [self.run(
            i,
            created_at="2026-07-25T06:00:00Z",
            updated_at="2026-07-25T06:06:00Z",
        ) for i in range(100, 200)]
        old = self.run(9)
        request.side_effect = [
            {"workflow_runs": page_one},
            *({"artifacts": []} for _ in page_one),
            {"workflow_runs": [old]},
            {"artifacts": [self.artifact(9, 9, "2026-07-25T06:05:00Z")]},
        ]
        chosen = find_canonical("owner/repo", "crossvenue-series", "token",
                                self.branch, self.workflow, max_pages=2)
        self.assertEqual(9, chosen["id"])
        self.assertIn("page=2", request.call_args_list[101].args[0])


if __name__ == "__main__":
    unittest.main()
