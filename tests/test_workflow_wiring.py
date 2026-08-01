from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
QUALITY_GATE = ROOT / ".github/workflows/quality-gate.yml"
ORG_CALLER = ROOT / ".github/workflows/org-quality-gate.yml"
CI = ROOT / ".github/workflows/ci.yml"
FEATURE_FLAG_ACTION = ROOT / ".github/actions/feature-flag/action.yml"
FEATURE_FLAG_WORKFLOW = ROOT / ".github/workflows/feature-flag-check.yml"
NODE_WORKFLOW = ROOT / ".github/workflows/node-pnpm-ci.yml"
PYTHON_WORKFLOW = ROOT / ".github/workflows/python-ci.yml"


class WorkflowWiringContractTests(unittest.TestCase):
    def test_org_ruleset_entrypoint_pins_the_nested_workflow(self) -> None:
        source = ORG_CALLER.read_text()
        self.assertIn(
            "uses: agiletec-inc/github-actions/.github/workflows/quality-gate.yml@"
            "c04f47176b865fcde75dd66955623cf8e1fb0e3d",
            source,
        )
        self.assertNotIn("@main", source)
        self.assertNotIn("source-ref", source)

    def test_quality_gate_uses_private_actions_at_pr_a_merge_sha(self) -> None:
        source = QUALITY_GATE.read_text()
        revision = "bc8d3af3f29651286df2ccff0063658ceacff5fb"
        action_refs = re.findall(
            r"uses: agiletec-inc/github-actions/\.github/actions/(detect|evaluate)@([0-9a-f]{40})",
            source,
        )
        self.assertEqual(action_refs, [("detect", revision), ("evaluate", revision)])
        self.assertNotIn("repository: agiletec-inc/github-actions", source)
        self.assertNotIn("source-ref", source)
        self.assertNotIn("source_sha", source)
        self.assertNotIn(".quality-gate-source", source)

    def test_comparison_revisions_are_fetched_before_detection(self) -> None:
        source = QUALITY_GATE.read_text()
        fetch_index = source.index("name: Fetch gate comparison revisions")
        detect_index = source.index("name: Detect quality gate capabilities")

        self.assertLess(fetch_index, detect_index)
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

    def test_private_repository_ci_uses_containerized_organization_runner(self) -> None:
        source = CI.read_text()
        self.assertIn("runs-on: ${{ 'org-shared-ci-light' }}", source)
        self.assertIn("container:\n      image: node:26-bookworm", source)
        self.assertNotRegex(source, r"(?m)^\s*runs-on:\s*ubuntu-latest\s*$")

    def test_ci_pins_setup_go_before_actionlint(self) -> None:
        source = CI.read_text()
        setup_go = (
            "uses: actions/setup-go@"
            "924ae3a1cded613372ab5595356fb5720e22ba16 # v6"
        )
        self.assertEqual(source.count(setup_go), 1)
        self.assertIn("go-version: 1.25.x", source)
        self.assertLess(source.index(setup_go), source.index("go run github.com/rhysd/actionlint"))

    def test_npm_without_a_lockfile_uses_install_instead_of_ci(self) -> None:
        source = NODE_WORKFLOW.read_text()
        self.assertIn('[ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]', source)
        self.assertIn("npm ci", source)
        self.assertIn("npm install", source)

    def test_node_gates_follow_declared_package_scripts(self) -> None:
        source = NODE_WORKFLOW.read_text()
        self.assertIn("name: Detect declared quality scripts", source)
        for name in ("lint", "typecheck", "test", "build"):
            self.assertIn(f"steps.scripts.outputs.{name} == 'true'", source)

    def test_python_formatter_follows_repository_configuration(self) -> None:
        source = PYTHON_WORKFLOW.read_text()
        self.assertIn("grep -Eq '^\\[tool\\.black\\]' pyproject.toml", source)
        self.assertIn("black --check .", source)
        self.assertIn("ruff format --check .", source)

    def test_feature_flag_checker_is_packaged_as_a_private_composite_action(self) -> None:
        source = FEATURE_FLAG_ACTION.read_text()
        self.assertIn("using: composite", source)
        self.assertIn('python "$GITHUB_ACTION_PATH/../../scripts/feature_flag_check.py"', source)
        self.assertIn('--root "$REPOSITORY_PATH"', source)

    def test_feature_flag_workflow_uses_pinned_private_action_without_checkout(self) -> None:
        source = FEATURE_FLAG_WORKFLOW.read_text()
        self.assertIn(
            "uses: agiletec-inc/github-actions/.github/actions/feature-flag@"
            "faf4cdde6e57c970df29bb912fb57406ca33d0ad",
            source,
        )
        self.assertNotIn("repository: agiletec-inc/github-actions", source)
        self.assertNotIn(".org-quality-gate", source)

    def test_native_gate_does_not_poll_repository_checks(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertNotIn("repository-gates:", source)
        self.assertNotIn("Wait for repository-native required checks", source)
        self.assertNotIn("sleep 15", source)

    def test_native_gate_repositories_do_not_run_duplicate_language_or_secret_gates(self) -> None:
        source = QUALITY_GATE.read_text()
        self.assertIn("native_required: ${{ steps.detect.outputs.native_required }}", source)
        self.assertGreaterEqual(source.count("needs.detect.outputs.native_required != 'true'"), 10)

        detected = source.split("detected: >-", 1)[1]
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
