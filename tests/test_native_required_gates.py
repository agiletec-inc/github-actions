from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DETECT = ROOT / ".github/scripts/detect_native_gates.sh"
EVALUATE = ROOT / ".github/scripts/evaluate_required_checks.mjs"


def parse_outputs(stdout: str) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in stdout.splitlines() if "=" in line
    )


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

    def detect_result(
        self, base: str, head: str, pr_labels: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if pr_labels is not None:
            environment["PR_LABELS"] = pr_labels
        else:
            environment.pop("PR_LABELS", None)
        return subprocess.run(
            ["bash", str(DETECT), str(self.repository), base, head],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def detect(self, base: str, head: str) -> list[dict[str, str]]:
        result = self.detect_result(base, head)
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = parse_outputs(result.stdout)
        self.assertIn("required_contexts", outputs)
        return json.loads(outputs["required_contexts"])

    def test_removing_base_gate_workflow_is_rejected(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        (self.repository / ".github/workflows/quality.yml").unlink()
        head = self.commit("attempt to remove native aggregate")

        result = self.detect_result(base, head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".github/workflows/quality.yml", result.stderr)

    def test_modifying_base_gate_workflow_is_rejected(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: self-hosted\n",
        )
        head = self.commit("attempt to modify protected workflow")

        result = self.detect_result(base, head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".github/workflows/quality.yml", result.stderr)

    def test_modifying_base_gate_workflow_without_label_still_rejected(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: self-hosted\n",
        )
        head = self.commit("attempt to modify protected workflow")

        result = self.detect_result(base, head, pr_labels="some-other-label")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Base-required workflow was modified or removed", result.stderr)
        self.assertIn(".github/workflows/quality.yml", result.stderr)

    def test_modifying_base_gate_workflow_with_allow_label_succeeds(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: self-hosted\n",
        )
        head = self.commit("intentionally strengthen protected workflow")

        result = self.detect_result(
            base, head, pr_labels="allow-protected-workflow-change"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Protected workflow changed under allow-protected-workflow-change: "
            ".github/workflows/quality.yml",
            result.stdout,
        )

    def test_unrelated_workflow_change_unaffected_by_label(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        self.write(
            ".github/workflows/other.yml",
            "jobs:\n  other-job:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base with protected and unrelated workflows")
        self.write(
            ".github/workflows/other.yml",
            "jobs:\n  other-job:\n    runs-on: self-hosted\n",
        )
        head = self.commit("modify unrelated workflow only")

        for pr_labels in (None, "allow-protected-workflow-change"):
            with self.subTest(pr_labels=pr_labels):
                result = self.detect_result(base, head, pr_labels=pr_labels)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("other.yml", result.stderr)

    def test_allow_label_has_no_effect_without_protected_workflow_change(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        self.write("README.md", "unrelated change\n")
        head = self.commit("touch unrelated file")

        result = self.detect_result(
            base, head, pr_labels="allow-protected-workflow-change"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Protected workflow changed", result.stdout)

    def test_merge_group_style_empty_labels_keeps_strict_behavior(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: self-hosted\n",
        )
        head = self.commit("attempt to modify protected workflow in merge_group")

        # merge_group events carry no labels, so PR_LABELS is unset/empty and
        # the strict rejection must apply exactly as without the label.
        for pr_labels in (None, ""):
            with self.subTest(pr_labels=pr_labels):
                result = self.detect_result(base, head, pr_labels=pr_labels)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(".github/workflows/quality.yml", result.stderr)

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

    def test_detection_does_not_depend_on_repository_directory_name(self) -> None:
        self.write(
            ".github/workflows/quality.yml",
            "jobs:\n  repo-quality-gate:\n    runs-on: ubuntu-latest\n",
        )
        base = self.commit("base native aggregate")
        self.write("README.md", "change\n")
        head = self.commit("head")
        original = self.detect(base, head)

        original_path = self.repository
        renamed = self.repository.parent / "not-agiletec"
        self.repository.rename(renamed)
        self.repository = renamed
        try:
            self.assertEqual(self.detect(base, head), original)
        finally:
            self.repository.rename(original_path)
            self.repository = original_path


class RequiredCheckEvaluationTests(unittest.TestCase):
    QUALITY_DESCRIPTOR = {
        "context": "repo-quality-gate",
        "workflow_path": ".github/workflows/quality.yml",
    }
    DB_DESCRIPTOR = {
        "context": "db-tests",
        "workflow_path": ".github/workflows/database.yml",
    }

    def evaluate(
        self,
        required_contexts: list[dict[str, str]],
        check_runs: list[dict[str, str | None]],
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["REQUIRED_CONTEXTS"] = json.dumps(required_contexts)
        environment["CHECK_RUNS"] = json.dumps(check_runs)
        return subprocess.run(
            ["node", str(EVALUATE)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_context_names_must_match_exactly(self) -> None:
        result = self.evaluate(
            [self.QUALITY_DESCRIPTOR],
            [
                {
                    "name": "repo-quality-gate / quality",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        )
        self.assertEqual(result.returncode, 75, result.stderr)

    def test_same_name_success_from_wrong_workflow_path_is_ignored(self) -> None:
        result = self.evaluate(
            [self.QUALITY_DESCRIPTOR],
            [
                {
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/spoof.yml",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        )
        self.assertEqual(result.returncode, 75, result.stderr)

    def test_latest_candidate_from_correct_path_is_authoritative(self) -> None:
        result = self.evaluate(
            [self.QUALITY_DESCRIPTOR],
            [
                {
                    "id": 100,
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "id": 101,
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_latest_failure_from_correct_path_is_rejected(self) -> None:
        result = self.evaluate(
            [self.QUALITY_DESCRIPTOR],
            [
                {
                    "id": 100,
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 101,
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "completed",
                    "conclusion": "failure",
                },
            ],
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_pending_or_missing_check_requests_retry(self) -> None:
        cases = {
            "missing": [],
            "queued": [
                {
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "queued",
                    "conclusion": None,
                }
            ],
            "in_progress": [
                {
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "in_progress",
                    "conclusion": None,
                }
            ],
        }
        for name, check_runs in cases.items():
            with self.subTest(state=name):
                result = self.evaluate([self.QUALITY_DESCRIPTOR], check_runs)
                self.assertEqual(result.returncode, 75, result.stderr)

    def test_genuine_pending_retries_even_when_spoof_success_exists(self) -> None:
        result = self.evaluate(
            [self.QUALITY_DESCRIPTOR],
            [
                {
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/spoof.yml",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "in_progress",
                    "conclusion": None,
                },
            ],
        )
        self.assertEqual(result.returncode, 75, result.stderr)

    def test_terminal_failure_is_a_hard_failure(self) -> None:
        for conclusion in (
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
        ):
            with self.subTest(conclusion=conclusion):
                result = self.evaluate(
                    [self.DB_DESCRIPTOR],
                    [
                        {
                            "name": "db-tests",
                            "workflow_path": ".github/workflows/database.yml",
                            "status": "completed",
                            "conclusion": conclusion,
                        }
                    ],
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(result.returncode, 75)
                self.assertIn("db-tests", result.stderr)

    def test_all_required_checks_succeed(self) -> None:
        result = self.evaluate(
            [self.QUALITY_DESCRIPTOR, self.DB_DESCRIPTOR],
            [
                {
                    "name": "repo-quality-gate",
                    "workflow_path": ".github/workflows/quality.yml",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "db-tests",
                    "workflow_path": ".github/workflows/database.yml",
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
