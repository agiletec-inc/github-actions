from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
QUALITY_GATE = ROOT / ".github/workflows/quality-gate.yml"
ORG_CALLER = ROOT / ".github/workflows/org-quality-gate.yml"
CI = ROOT / ".github/workflows/ci.yml"


class WorkflowWiringContractTests(unittest.TestCase):
    def test_org_ruleset_entrypoint_follows_protected_main_end_to_end(self) -> None:
        source = ORG_CALLER.read_text()
        self.assertIn(
            "uses: agiletec-inc/github-actions/.github/workflows/quality-gate.yml@main",
            source,
        )
        self.assertIn("source-ref: main", source)

    def test_quality_gate_resolves_source_once_and_never_checks_out_main(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertNotRegex(source, r"(?m)^\s*ref:\s*main\s*$")
        self.assertEqual(len(re.findall(r"id:\s*resolve-source", source)), 1)
        self.assertIn("source_sha", source)
        self.assertRegex(source, r"ref:\s*\$\{\{[^}]*source_sha[^}]*\}\}")

    def test_comparison_revisions_are_fetched_before_source_checkout(self) -> None:
        source = QUALITY_GATE.read_text()
        fetch_index = source.index("name: Fetch gate comparison revisions")
        source_checkout_index = source.index("name: Check out quality gate implementation")

        self.assertLess(fetch_index, source_checkout_index)
        self.assertIn(
            'git config --global --add safe.directory "$GITHUB_WORKSPACE"',
            source,
        )
        self.assertIn('git fetch --no-tags --depth=1 origin "$BASE_SHA" "$HEAD_SHA"', source)

    def test_org_caller_grants_read_only_checks_and_actions_access(self) -> None:
        source = ORG_CALLER.read_text()
        self.assertRegex(source, r"(?m)^\s*actions:\s*read\s*$")
        self.assertRegex(source, r"(?m)^\s*checks:\s*read\s*$")

    def test_private_repositories_use_the_lightweight_organization_runner(self) -> None:
        source = ORG_CALLER.read_text()
        self.assertIn("'org-shared-ci-light'", source)
        self.assertNotIn("'org-required-ci'", source)
        self.assertIn("'ubuntu-latest'", source)
        self.assertNotIn("github.repository", source)
        self.assertNotIn("agiletec-ci-runner", source)

    def test_ci_discovers_all_contract_test_modules(self) -> None:
        source = CI.read_text()
        self.assertRegex(source, r"python3\s+-m\s+unittest\s+discover(?:\s|$)")
        self.assertNotRegex(source, r"python3\s+-m\s+unittest\s+tests\.test_")

    def test_private_repository_ci_uses_organization_runner(self) -> None:
        source = CI.read_text()
        self.assertIn("runs-on: ${{ 'org-shared-ci-light' }}", source)
        self.assertNotRegex(source, r"(?m)^\s*runs-on:\s*ubuntu-latest\s*$")

    def test_native_gate_does_not_poll_repository_checks(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertNotIn("repository-gates:", source)
        self.assertNotIn("Wait for repository-native required checks", source)
        self.assertNotIn("sleep 15", source)

    def test_native_gate_repositories_do_not_run_duplicate_language_or_secret_gates(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertIn("native_required: ${{ steps.native.outputs.required_contexts != '[]' }}", source)
        self.assertGreaterEqual(source.count("needs.detect.outputs.native_required != 'true'"), 10)

        detected = source.split("DETECTED: >-", 1)[1].split("run: node", 1)[0]
        for job in ("node-ci", "bun-ci", "python-ci", "rust-ci", "swift-ci"):
            line = next(line for line in detected.splitlines() if f'"{job}"' in line)
            self.assertIn("needs.detect.outputs.native_required != 'true'", line)

    def test_native_gate_repositories_do_not_run_duplicate_feature_flag_gate(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertIn(
            "needs.detect.outputs.heavy == 'true' && needs.detect.outputs.native_required != 'true'",
            source,
        )

    def test_secret_scan_is_required_only_when_selected(self) -> None:
        evaluator = (ROOT / ".github/scripts/evaluate_quality_gate.mjs").read_text()
        self.assertIn("const required = new Set();", evaluator)
        self.assertNotIn("new Set(['secret-scan'])", evaluator)


if __name__ == "__main__":
    unittest.main()
