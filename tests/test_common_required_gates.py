from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DETECT = ROOT / ".github/scripts/detect_capabilities.sh"
DOCS_ONLY = ROOT / ".github/scripts/docs_only.sh"
EVALUATE = ROOT / ".github/scripts/evaluate_quality_gate.mjs"


def parse_outputs(stdout: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            outputs[key] = value
    return outputs


class CapabilityDetectionTests(unittest.TestCase):
    def run_detection(self, repository: Path) -> dict[str, str]:
        result = subprocess.run(
            ["bash", str(DETECT), str(repository)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return parse_outputs(result.stdout)

    def test_detection_is_independent_of_repository_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            outputs = []
            for name in ("agiletec", "unrelated-public-project"):
                repository = parent / name
                repository.mkdir()
                (repository / "deno.json").write_text("{}\n")
                outputs.append(self.run_detection(repository))

        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0].get("deno"), "true")

    def test_detects_deno_from_config_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "deno.jsonc").write_text("{}\n")
            self.assertEqual(self.run_detection(repository).get("deno"), "true")

    def test_detects_supabase_from_config_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "supabase").mkdir()
            (repository / "supabase/config.toml").write_text("project_id = 'fixture'\n")
            self.assertEqual(self.run_detection(repository).get("supabase"), "true")

    def test_detects_nested_dockerfile_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "apps/api").mkdir(parents=True)
            (repository / "apps/api/Dockerfile").write_text("FROM scratch\n")
            self.assertEqual(self.run_detection(repository).get("docker"), "true")

    def test_detects_dependency_audit_from_lockfile_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
            self.assertEqual(
                self.run_detection(repository).get("dependency_audit"), "true"
            )


class DocsOnlyDetectionTests(unittest.TestCase):
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
        (self.repository / "README.md").write_text("initial\n")
        self.commit("initial")
        self.base = self.rev_parse("HEAD")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def commit(self, message: str) -> None:
        subprocess.run(["git", "-C", str(self.repository), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repository), "commit", "-qm", message], check=True
        )

    def rev_parse(self, revision: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repository), "rev-parse", revision],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def run_detection(self, base: str, head: str) -> dict[str, str]:
        result = subprocess.run(
            ["bash", str(DOCS_ONLY), str(self.repository), base, head],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return parse_outputs(result.stdout)

    def assert_heavy_and_secret_scan(self, outputs: dict[str, str]) -> None:
        self.assertEqual(outputs.get("docs_only"), "false")
        self.assertEqual(outputs.get("heavy"), "true")
        self.assertEqual(outputs.get("secret_scan"), "true")

    def test_known_markdown_only_diff_skips_only_heavy_jobs(self) -> None:
        (self.repository / "README.md").write_text("documentation update\n")
        self.commit("docs")
        outputs = self.run_detection(self.base, self.rev_parse("HEAD"))
        self.assertEqual(outputs.get("docs_only"), "true")
        self.assertEqual(outputs.get("heavy"), "false")
        self.assertEqual(outputs.get("secret_scan"), "true")

    def test_unknown_zero_or_unresolvable_base_fails_closed(self) -> None:
        head = self.rev_parse("HEAD")
        for base in ("unknown", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                self.assert_heavy_and_secret_scan(self.run_detection(base, head))

    def test_operational_files_are_never_docs_only(self) -> None:
        fixtures = {
            ".github/workflows/ci.yml": "name: ci\n",
            "package.json": "{}\n",
            "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
            "supabase/config.toml": "project_id = 'fixture'\n",
            "apps/api/Dockerfile": "FROM scratch\n",
            "src/policy.md": "operational input disguised as markdown\n",
        }
        for relative_path, contents in fixtures.items():
            with self.subTest(path=relative_path):
                subprocess.run(
                    ["git", "-C", str(self.repository), "reset", "--hard", "-q", self.base],
                    check=True,
                )
                path = self.repository / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
                self.commit(relative_path)
                self.assert_heavy_and_secret_scan(
                    self.run_detection(self.base, self.rev_parse("HEAD"))
                )


class AggregateGateTests(unittest.TestCase):
    def evaluate(
        self, detected: dict[str, bool], needs: dict[str, dict[str, str]]
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["DETECTED"] = json.dumps(detected)
        environment["NEEDS"] = json.dumps(needs)
        return subprocess.run(
            ["node", str(EVALUATE)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_applicable_job_must_not_be_skipped_failed_or_cancelled(self) -> None:
        for result_name in ("skipped", "failure", "cancelled"):
            with self.subTest(result=result_name):
                result = self.evaluate(
                    {"deno-ci": True},
                    {
                        "deno-ci": {"result": result_name},
                        "secret-scan": {"result": "success"},
                    },
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("deno-ci", result.stderr)

    def test_non_applicable_job_may_be_skipped(self) -> None:
        result = self.evaluate(
            {"deno-ci": False},
            {
                "deno-ci": {"result": "skipped"},
                "secret-scan": {"result": "success"},
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_secret_scan_is_required_even_when_all_capabilities_are_absent(self) -> None:
        result = self.evaluate(
            {"deno-ci": False},
            {
                "deno-ci": {"result": "skipped"},
                "secret-scan": {"result": "skipped"},
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("secret-scan", result.stderr)


if __name__ == "__main__":
    unittest.main()
