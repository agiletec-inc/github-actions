from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DETECT = ROOT / ".github/scripts/detect_native_gates.sh"


def parse_outputs(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)


class NativeGateDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.name", "Test"],
            check=True,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, contents: str) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def commit(self, message: str) -> str:
        subprocess.run(["git", "-C", str(self.repository), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repository), "commit", "-qm", message], check=True
        )
        return subprocess.run(
            ["git", "-C", str(self.repository), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def detect(self, base: str, head: str) -> list[dict[str, str]]:
        result = subprocess.run(
            ["bash", str(DETECT), str(self.repository), base, head],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(parse_outputs(result.stdout)["required_contexts"])

    def test_base_gate_remains_detected_when_head_changes_it(self) -> None:
        workflow = ".github/workflows/quality.yml"
        self.write(workflow, "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n")
        base = self.commit("base native aggregate")
        self.write(workflow, "jobs:\n  repo-quality-gate:\n    runs-on: org-shared-ci-light\n")
        head = self.commit("change native aggregate")

        self.assertEqual(
            self.detect(base, head),
            [{"context": "repo-quality-gate", "workflow_path": workflow}],
        )

    def test_adding_gate_in_head_activates_requirement(self) -> None:
        self.write("README.md", "initial\n")
        base = self.commit("base")
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        head = self.commit("add native aggregate")

        self.assertEqual(
            self.detect(base, head),
            [
                {
                    "context": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                }
            ],
        )

    def test_supabase_with_db_tests_job_requires_db_tests_context(self) -> None:
        self.write("README.md", "initial\n")
        base = self.commit("base")
        self.write("supabase/config.toml", "project_id = 'fixture'\n")
        self.write(
            ".github/workflows/database.yml",
            "jobs:\n  db-tests:\n    runs-on: ubuntu-latest\n",
        )
        head = self.commit("add supabase database gate")

        self.assertEqual(
            self.detect(base, head),
            [
                {
                    "context": "db-tests",
                    "workflow_path": ".github/workflows/database.yml",
                }
            ],
        )

    def test_unrelated_repository_has_no_native_gate(self) -> None:
        self.write("README.md", "documentation only\n")
        base = self.commit("base")
        self.write("src/main.ts", "export const value = 1;\n")
        head = self.commit("ordinary source")

        self.assertEqual(self.detect(base, head), [])


if __name__ == "__main__":
    unittest.main()
