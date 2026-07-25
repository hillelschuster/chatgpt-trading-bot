import unittest
from crossvenue_transport_gate import apply_transport_gate


def valid_inputs():
    health = {"status": "ACCUMULATING_SNAPSHOTS", "integrity": {"blockers": []}}
    binding = {"status": "VALID", "archive_sha256": "a" * 64}
    bundle = {
        "status": "VALID", "zip_sha256": "a" * 64,
        "extraction": "crash_recoverable_transactional_bundle_replace",
        "destination_path_policy": "no_symlink_or_special_file_components",
        "recovery_policy": "old_and_new_sha256_verified_before_mutation",
        "recovered_interrupted_transactions": 0,
    }
    return health, binding, bundle


class TransportGateTest(unittest.TestCase):
    def test_valid_exact_transport_preserves_health(self):
        health, binding, bundle = valid_inputs()
        result = apply_transport_gate(health, binding, bundle)
        self.assertEqual("ACCUMULATING_SNAPSHOTS", result["status"])
        self.assertTrue(result["integrity"]["transport"]["digest_matches"])
        self.assertEqual([], result["integrity"]["blockers"])

    def test_digest_mismatch_fails_closed(self):
        health, binding, bundle = valid_inputs()
        bundle["zip_sha256"] = "b" * 64
        result = apply_transport_gate(health, binding, bundle)
        self.assertEqual("INVALID", result["status"])
        self.assertIn("artifact_bundle_digest_mismatch", result["integrity"]["blockers"])

    def test_invalid_binding_and_bundle_preserve_existing_blockers(self):
        health, binding, bundle = valid_inputs()
        health["integrity"]["blockers"] = ["collection_stale"]
        binding["status"] = "INVALID"
        bundle["status"] = "INVALID"
        result = apply_transport_gate(health, binding, bundle)
        self.assertEqual("INVALID", result["status"])
        self.assertEqual("collection_stale", result["integrity"]["blockers"][0])
        self.assertIn("artifact_binding_invalid", result["integrity"]["blockers"])
        self.assertIn("bundle_restore_invalid", result["integrity"]["blockers"])

    def test_policy_tampering_fails_closed(self):
        health, binding, bundle = valid_inputs()
        bundle["extraction"] = "unsafe"
        bundle["destination_path_policy"] = "unsafe"
        bundle["recovery_policy"] = "unsafe"
        result = apply_transport_gate(health, binding, bundle)
        self.assertEqual("INVALID", result["status"])
        self.assertFalse(result["integrity"]["transport"]["extraction_policy_valid"])
        self.assertEqual(3, len(result["integrity"]["transport"]["blockers"]))


if __name__ == "__main__":
    unittest.main()
