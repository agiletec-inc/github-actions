from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github/workflows"


class PublicSecurityBoundaryTests(unittest.TestCase):
    def test_remote_action_and_workflow_refs_are_immutable(self) -> None:
        violations: list[str] = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for line_number, line in enumerate(workflow.read_text().splitlines(), start=1):
                match = re.search(r"^\s*uses:\s*([^\s#]+)", line)
                if not match:
                    continue
                reference = match.group(1)
                if reference.startswith("./"):
                    continue
                revision = reference.rsplit("@", 1)[-1]
                if not re.fullmatch(r"[0-9a-f]{40}", revision):
                    violations.append(f"{workflow.name}:{line_number}: {reference}")

        self.assertEqual(violations, [])

    def test_privileged_untrusted_code_triggers_are_absent(self) -> None:
        combined = "\n".join(path.read_text() for path in WORKFLOWS.glob("*.yml"))
        self.assertNotRegex(combined, r"(?m)^\s*pull_request_target\s*:")
        self.assertNotRegex(combined, r"(?m)^\s*workflow_run\s*:")

    def test_every_workflow_declares_token_permissions(self) -> None:
        violations = [
            path.name
            for path in sorted(WORKFLOWS.glob("*.yml"))
            if not re.search(r"(?m)^\s*permissions:\s*(?:\{\})?\s*$", path.read_text())
        ]
        self.assertEqual(violations, [])

    def test_workflows_never_request_write_all(self) -> None:
        combined = "\n".join(path.read_text() for path in WORKFLOWS.glob("*.yml"))
        self.assertNotRegex(combined, r"(?m)^\s*permissions:\s*write-all\s*$")

    def test_repository_does_not_contain_common_secret_shapes(self) -> None:
        patterns = {
            "GitHub token": r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})",
            "AWS access key": r"(?:AKIA|ASIA)[A-Z0-9]{16}",
            "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            "AWS ARN": r"arn:aws(?:-[a-z]+)?:[a-z0-9-]+:[^\s]+",
        }
        files = [path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]
        violations: list[str] = []
        for path in files:
            try:
                source = path.read_text()
            except UnicodeDecodeError:
                continue
            for label, pattern in patterns.items():
                if re.search(pattern, source):
                    violations.append(f"{path.relative_to(ROOT)}: {label}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
