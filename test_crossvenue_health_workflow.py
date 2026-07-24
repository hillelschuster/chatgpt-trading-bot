import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/crossvenue-health.yml")


class HealthWorkflowTests(unittest.TestCase):
    def test_final_actions_gate_always_runs_after_base_summary(self):
        text = WORKFLOW.read_text()
        step = text.split("- name: Summarize and bind authoritative evidence health", 1)[1]
        step = step.split("- uses: actions/upload-artifact@v4", 1)[0]

        summary = "python crossvenue_health.py --out reports/crossvenue_health.json || true"
        gate = "python crossvenue_actions_gate.py"
        self.assertIn(summary, step)
        self.assertIn(gate, step)
        self.assertLess(step.index(summary), step.index(gate))

    def test_final_gate_receives_every_bound_input(self):
        text = WORKFLOW.read_text()
        step = text.split("- name: Summarize and bind authoritative evidence health", 1)[1]
        step = step.split("- uses: actions/upload-artifact@v4", 1)[0]
        for argument in (
            "--health-report reports/crossvenue_health.json",
            "--binding reports/crossvenue_actions_binding.json",
            "--runs reports/crossvenue_workflow_runs.json",
            "--restoration reports/crossvenue_restoration.json",
            "--actions-report reports/crossvenue_actions_health.json",
        ):
            self.assertIn(argument, step)

    def test_ungated_health_report_is_not_uploaded_on_success_path(self):
        text = WORKFLOW.read_text()
        summary_index = text.index("python crossvenue_health.py --out reports/crossvenue_health.json || true")
        gate_index = text.index("python crossvenue_actions_gate.py", summary_index)
        upload_index = text.index("- uses: actions/upload-artifact@v4", gate_index)
        self.assertLess(summary_index, gate_index)
        self.assertLess(gate_index, upload_index)


if __name__ == "__main__":
    unittest.main()
