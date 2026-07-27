from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DETECT_ACTION = ROOT / ".github/actions/detect/action.yml"
EVALUATE_ACTION = ROOT / ".github/actions/evaluate/action.yml"


def section(source: str, heading: str, next_heading: str) -> str:
    return source.split(f"{heading}:\n", 1)[1].split(f"\n{next_heading}:\n", 1)[0]


class ActionMetadataContractTests(unittest.TestCase):
    def test_actions_are_composite_metadata(self) -> None:
        for action in (DETECT_ACTION, EVALUATE_ACTION):
            with self.subTest(action=action):
                source = action.read_text()
                self.assertRegex(source, r"(?m)^name: .+$")
                self.assertRegex(source, r"(?m)^description: .+$")
                self.assertIn("runs:\n  using: composite\n", source)
                self.assertNotRegex(source, r"(?i)\b(?:pat|token|secret)s?\b")

    def test_detect_exposes_current_workflow_outputs(self) -> None:
        source = DETECT_ACTION.read_text()
        outputs = section(source, "outputs", "runs")
        expected = {
            "node",
            "node_version",
            "node_run_command",
            "bun",
            "python",
            "python_directory",
            "rust",
            "swift",
            "swift_directory",
            "supported",
            "deno",
            "supabase",
            "docker",
            "dependency_audit",
            "docs_only",
            "heavy",
            "secret_scan",
            "required_contexts",
            "native_required",
        }
        declared = set(re.findall(r"(?m)^  ([a-z][a-z0-9_]*):$", outputs))
        self.assertEqual(declared, expected)

    def test_detect_runs_only_repository_owned_scripts_from_action_path(self) -> None:
        source = DETECT_ACTION.read_text()
        run_commands = re.findall(r"(?m)^      run: (.+)$", source)
        self.assertEqual(len(run_commands), 3)
        self.assertEqual(
            {
                "detect_capabilities.sh",
                "docs_only.sh",
                "detect_native_gates.sh",
            },
            {
                match.group(1)
                for command in run_commands
                if (match := re.search(r"scripts/([a-z_]+\.sh)", command))
            },
        )
        for command in run_commands:
            self.assertIn('$GITHUB_ACTION_PATH/../../scripts/', command)
            self.assertNotIn("${{ inputs.", command)

    def test_evaluate_passes_json_inputs_through_environment(self) -> None:
        source = EVALUATE_ACTION.read_text()
        self.assertIn("NEEDS: ${{ inputs.needs }}", source)
        self.assertIn("DETECTED: ${{ inputs.detected }}", source)
        self.assertIn(
            'run: node "$GITHUB_ACTION_PATH/../../scripts/evaluate_quality_gate.mjs"',
            source,
        )
        run_command = re.search(r"(?m)^      run: (.+)$", source)
        self.assertIsNotNone(run_command)
        self.assertNotIn("${{ inputs.", run_command.group(1))


if __name__ == "__main__":
    unittest.main()
