from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/crossvenue-probe.yml")


class CollectionProvenanceWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_scheduled_runs_publish_canonical_series_name(self):
        expected = (
            "name: ${{ github.event_name == 'schedule' && 'crossvenue-series' "
            "|| format('crossvenue-probe-{0}', github.run_id) }}"
        )
        self.assertIn(expected, self.text)
        self.assertNotIn(
            "github.event_name == 'pull_request' && format('crossvenue-probe-{0}', github.run_id) || 'crossvenue-series'",
            self.text,
        )

    def test_manual_dispatch_remains_available_but_cannot_advance_canonical_chain(self):
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("github.event_name == 'schedule'", self.text)
        self.assertIn("format('crossvenue-probe-{0}', github.run_id)", self.text)


if __name__ == "__main__":
    unittest.main()
