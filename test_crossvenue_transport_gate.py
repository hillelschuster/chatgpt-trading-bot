import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from crossvenue_artifact_binding import verify
from crossvenue_bundle import extract_bundle
from crossvenue_transport_gate import apply_transport_gate, recompute_transport

REQUIRED = {
    "data/crossvenue_experiment_freeze.json",
    "data/crossvenue_snapshots.jsonl",
    "reports/crossvenue_chain.json",
    "reports/crossvenue_validation.json",
    "reports/crossvenue_promotion.json",
}


def make_fixture(root: Path):
    archive = root / "series.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(REQUIRED):
            bundle.writestr(name, (name + "\n").encode())
    raw = archive.read_bytes()
    restoration = {
        "status": "downloaded", "schema_version": 5,
        "archive_sha256": hashlib.sha256(raw).hexdigest(), "archive_bytes": len(raw),
        "redirect_policy": "https_cross_origin_credentials_stripped",
        "zip_safety_policy": "bounded_unencrypted_members_before_crc_v1",
        "zip_member_count": len(REQUIRED),
        "zip_uncompressed_bytes": sum(len(name + "\n") for name in REQUIRED),
        "zip_crc_verified": True, "artifact_id": 1, "workflow_run_id": 2,
        "created_at": "2026-07-25T00:00:00Z", "branch": "main",
        "workflow_path": ".github/workflows/crossvenue-probe.yml",
    }
    binding = verify(archive, restoration)
    bundle = extract_bundle(archive, root, REQUIRED)
    health = {"status": "ACCUMULATING_SNAPSHOTS", "integrity": {"blockers": []}}
    return archive, restoration, binding, bundle, health


class TransportGateTest(unittest.TestCase):
    def test_exact_recomputation_preserves_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, restoration, binding, bundle, health = make_fixture(root)
            rb, rbu, errors = recompute_transport(archive, restoration, root, REQUIRED)
            result = apply_transport_gate(
                health, binding, bundle,
                recomputed_binding=rb,
                recomputed_bundle=rbu,
                recomputation_blockers=errors,
            )
            self.assertEqual("ACCUMULATING_SNAPSHOTS", result["status"])
            self.assertTrue(result["integrity"]["transport"]["artifact_binding_exact_recomputation_match"])
            self.assertTrue(result["integrity"]["transport"]["bundle_exact_recomputation_match"])

    def test_forged_binding_with_valid_status_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, restoration, binding, bundle, health = make_fixture(root)
            rb, rbu, errors = recompute_transport(archive, restoration, root, REQUIRED)
            binding["artifact_id"] = 999
            result = apply_transport_gate(
                health, binding, bundle,
                recomputed_binding=rb,
                recomputed_bundle=rbu,
                recomputation_blockers=errors,
            )
            self.assertEqual("INVALID", result["status"])
            self.assertIn("artifact_binding_recomputation_mismatch", result["integrity"]["blockers"])

    def test_forged_bundle_member_digest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, restoration, binding, bundle, health = make_fixture(root)
            rb, rbu, errors = recompute_transport(archive, restoration, root, REQUIRED)
            name = sorted(REQUIRED)[0]
            bundle["members"][name]["sha256"] = "0" * 64
            result = apply_transport_gate(
                health, binding, bundle,
                recomputed_binding=rb,
                recomputed_bundle=rbu,
                recomputation_blockers=errors,
            )
            self.assertEqual("INVALID", result["status"])
            self.assertIn("bundle_recomputation_mismatch", result["integrity"]["blockers"])

    def test_restored_file_changed_after_report_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, restoration, binding, bundle, health = make_fixture(root)
            (root / sorted(REQUIRED)[0]).write_text("tampered\n")
            rb, rbu, errors = recompute_transport(archive, restoration, root, REQUIRED)
            result = apply_transport_gate(
                health, binding, bundle,
                recomputed_binding=rb,
                recomputed_bundle=rbu,
                recomputation_blockers=errors,
            )
            self.assertEqual("INVALID", result["status"])
            self.assertIn("bundle_recomputation_mismatch", result["integrity"]["blockers"])

    def test_missing_restored_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, restoration, binding, bundle, health = make_fixture(root)
            (root / sorted(REQUIRED)[0]).unlink()
            rb, rbu, errors = recompute_transport(archive, restoration, root, REQUIRED)
            result = apply_transport_gate(
                health, binding, bundle,
                recomputed_binding=rb,
                recomputed_bundle=rbu,
                recomputation_blockers=errors,
            )
            self.assertEqual("INVALID", result["status"])
            self.assertTrue(any(
                blocker.startswith("restored_member_unreadable:")
                for blocker in result["integrity"]["blockers"]
            ))


if __name__ == "__main__":
    unittest.main()
