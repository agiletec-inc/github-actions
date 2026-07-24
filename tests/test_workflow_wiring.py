from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
QUALITY_GATE = ROOT / ".github/workflows/quality-gate.yml"
ORG_CALLER = ROOT / ".github/workflows/org-quality-gate.yml"
CI = ROOT / ".github/workflows/ci.yml"


class WorkflowWiringContractTests(unittest.TestCase):
    def test_org_caller_uses_immutable_quality_gate_revision(self) -> None:
        source = ORG_CALLER.read_text()
        uses_match = re.search(
            r"uses:\s*agiletec-inc/github-actions/\.github/workflows/quality-gate\.yml@([0-9a-f]{40})",
            source,
        )
        source_ref_match = re.search(r"(?m)^\s*source-ref:\s*([0-9a-f]{40})\s*$", source)

        self.assertIsNotNone(uses_match)
        self.assertIsNotNone(source_ref_match)
        self.assertEqual(uses_match.group(1), source_ref_match.group(1))

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

    def test_private_repositories_use_org_shared_light_runner(self) -> None:
        source = ORG_CALLER.read_text()
        self.assertIn("org-shared-ci-light", source)
        self.assertNotIn("agiletec-ci-runner", source)

    def test_ci_discovers_all_contract_test_modules(self) -> None:
        source = CI.read_text()
        self.assertRegex(source, r"python3\s+-m\s+unittest\s+discover(?:\s|$)")
        self.assertNotRegex(source, r"python3\s+-m\s+unittest\s+tests\.test_")

    def test_native_gate_pending_status_is_captured_under_errexit(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertIn(
            'if CHECK_RUNS="$CHECK_RUNS" node '
            '.quality-gate-source/.github/scripts/evaluate_required_checks.mjs; then',
            source,
        )


if __name__ == "__main__":
    unittest.main()
