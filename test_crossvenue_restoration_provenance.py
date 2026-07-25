import unittest

from crossvenue_restoration_provenance import verify


class RestorationProvenanceTest(unittest.TestCase):
    repository = "hillelschuster/chatgpt-trading-bot"
    branch = "main"
    workflow = ".github/workflows/crossvenue-probe.yml"

    def valid_report(self):
        return {
            "status": "downloaded",
            "schema_version": 7,
            "artifact_id": 123,
            "artifact_created_at": "2026-07-25T12:05:00Z",
            "workflow_run_id": 456,
            "workflow_run_event": "schedule",
            "workflow_run_head_sha": "a" * 40,
            "workflow_run_created_at": "2026-07-25T12:00:00Z",
            "workflow_run_updated_at": "2026-07-25T12:06:00Z",
            "branch": "main",
            "workflow_path": self.workflow,
            "allowed_events": ["schedule"],
            "selection": "successful_scheduled_workflow_runs_then_bound_named_artifact",
            "artifact_run_binding": "exact_run_id_and_bounded_timestamps_v1",
            "archive_sha256": "b" * 64,
            "archive_bytes": 1024,
            "zip_member_count": 5,
            "zip_uncompressed_bytes": 4096,
            "zip_crc_verified": True,
            "redirect_policy": "https_cross_origin_credentials_stripped",
            "zip_safety_policy": "bounded_unencrypted_members_before_crc_v1",
        }

    def evaluate(self, report):
        return verify(report, self.repository, self.branch, self.workflow)

    def test_exact_emitted_report_is_valid(self):
        result = self.evaluate(self.valid_report())
        self.assertEqual("VALID", result["status"])
        self.assertEqual([], result["blockers"])
        self.assertTrue(all(result["checks"].values()))

    def test_rejects_non_scheduled_or_wrong_code_provenance(self):
        mutations = {
            "manual": ("workflow_run_event", "workflow_dispatch"),
            "wrong_branch": ("branch", "experiment"),
            "wrong_workflow": ("workflow_path", ".github/workflows/other.yml"),
            "uppercase_sha": ("workflow_run_head_sha", "A" * 40),
            "short_sha": ("workflow_run_head_sha", "a" * 39),
            "expanded_allowlist": ("allowed_events", ["schedule", "workflow_dispatch"]),
        }
        for name, (field, value) in mutations.items():
            with self.subTest(name=name):
                report = self.valid_report()
                report[field] = value
                self.assertEqual("INVALID", self.evaluate(report)["status"])

    def test_rejects_impossible_or_missing_timestamp_binding(self):
        variants = [
            ("workflow_run_created_at", "2026-07-25T12:07:00Z"),
            ("artifact_created_at", "2026-07-25T11:59:59Z"),
            ("artifact_created_at", "2026-07-25T12:17:00Z"),
            ("workflow_run_updated_at", "not-a-time"),
        ]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                report = self.valid_report()
                report[field] = value
                self.assertEqual("INVALID", self.evaluate(report)["status"])

    def test_rejects_forged_or_incomplete_download_identity(self):
        variants = [
            ("archive_sha256", "B" * 64),
            ("archive_sha256", "b" * 63),
            ("archive_bytes", 0),
            ("zip_member_count", 0),
            ("zip_uncompressed_bytes", 0),
            ("zip_crc_verified", False),
            ("redirect_policy", "credentials_forwarded"),
            ("zip_safety_policy", "unbounded"),
        ]
        for field, value in variants:
            with self.subTest(field=field):
                report = self.valid_report()
                report[field] = value
                result = self.evaluate(report)
                self.assertEqual("INVALID", result["status"])
                self.assertTrue(result["blockers"])

    def test_rejects_boolean_or_nonpositive_identifiers(self):
        for field, value in (
            ("artifact_id", True),
            ("artifact_id", 0),
            ("workflow_run_id", -1),
            ("workflow_run_id", "not-an-int"),
        ):
            with self.subTest(field=field, value=value):
                report = self.valid_report()
                report[field] = value
                self.assertEqual("INVALID", self.evaluate(report)["status"])


if __name__ == "__main__":
    unittest.main()
