from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "generate_required_workflow_pin_proposal.py"
SPEC = importlib.util.spec_from_file_location("ruleset_pin_proposal", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PROPOSED_SHA = "2" * 40
REPOSITORY_ID = 12345


class FakeReader:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.paths: list[str] = []

    def get_object(self, path: str) -> dict[str, object]:
        self.paths.append(path)
        return self.responses[path]


def responses() -> dict[str, dict[str, object]]:
    repository_path = "/repos/agiletec-inc/github-actions"
    return {
        repository_path: {"id": REPOSITORY_ID, "default_branch": "main"},
        f"{repository_path}/commits/{PROPOSED_SHA}": {"sha": PROPOSED_SHA},
        f"{repository_path}/compare/{PROPOSED_SHA}...main": {"status": "ahead"},
        f"{repository_path}/pulls/25": {
            "state": "closed",
            "merged_at": "2026-07-27T00:00:00Z",
            "base": {"ref": "main"},
            "head": {"sha": PROPOSED_SHA},
        },
        f"{repository_path}/commits/{PROPOSED_SHA}/check-runs?filter=latest&per_page=100": {
            "check_runs": [
                {
                    "id": 88,
                    "name": "test",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://github.com/agiletec-inc/github-actions/actions/runs/77/job/99",
                    "app": {"slug": "github-actions"},
                }
            ]
        },
        f"{repository_path}/actions/runs/77": {
            "head_sha": PROPOSED_SHA,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        },
        "/repos/agiletec-inc/agiletec/rulesets/19456040": {
            "id": 19456040,
            "source_type": "Organization",
            "source": "agiletec-inc",
            "enforcement": "active",
            "rules": [
                {
                    "type": "workflows",
                    "parameters": {
                        "workflows": [
                            {
                                "repository_id": REPOSITORY_ID,
                                "path": ".github/workflows/org-quality-gate.yml",
                                "ref": "refs/heads/main",
                            }
                        ]
                    },
                }
            ],
        },
    }


class ProposalTest(unittest.TestCase):
    def test_build_proposal_is_deterministic_and_digest_covers_unsigned_body(
        self,
    ) -> None:
        canary = {
            "repository": "agiletec-inc/github-actions",
            "pull_request": 25,
            "head_sha": PROPOSED_SHA,
            "check_name": "test",
            "check_run_id": 88,
            "workflow_run_id": 77,
            "workflow_path": ".github/workflows/ci.yml",
            "conclusion": "success",
        }
        first = MODULE.build_proposal(REPOSITORY_ID, PROPOSED_SHA, canary)
        second = MODULE.build_proposal(REPOSITORY_ID, PROPOSED_SHA, canary)
        self.assertEqual(first, second)
        unsigned = {key: value for key, value in first.items() if key != "digest"}
        expected = hashlib.sha256(MODULE.canonical_json(unsigned).encode()).hexdigest()
        self.assertEqual(first["digest"], f"sha256:{expected}")

    def test_validates_candidate_canary_and_effective_ruleset(self) -> None:
        reader = FakeReader(responses())
        repository_id = MODULE.validate_candidate(reader, PROPOSED_SHA)
        canary = MODULE.validate_canary(reader, 25, PROPOSED_SHA)
        ruleset = reader.get_object("/repos/agiletec-inc/agiletec/rulesets/19456040")
        MODULE.validate_effective_workflow(ruleset, repository_id)
        self.assertEqual(canary["workflow_run_id"], 77)

    def test_rejects_candidate_not_reachable_from_main(self) -> None:
        payloads = responses()
        payloads[f"/repos/agiletec-inc/github-actions/compare/{PROPOSED_SHA}...main"][
            "status"
        ] = "diverged"
        with self.assertRaisesRegex(MODULE.ProposalError, "not reachable"):
            MODULE.validate_candidate(FakeReader(payloads), PROPOSED_SHA)

    def test_rejects_canary_head_mismatch(self) -> None:
        payloads = responses()
        payloads["/repos/agiletec-inc/github-actions/pulls/25"]["head"] = {
            "sha": "3" * 40
        }
        with self.assertRaisesRegex(MODULE.ProposalError, "head does not match"):
            MODULE.validate_canary(FakeReader(payloads), 25, PROPOSED_SHA)

    def test_rejects_spoofed_or_unsuccessful_check(self) -> None:
        payloads = responses()
        checks = payloads[
            f"/repos/agiletec-inc/github-actions/commits/{PROPOSED_SHA}/check-runs?filter=latest&per_page=100"
        ]["check_runs"]
        assert isinstance(checks, list)
        checks[0]["app"] = {"slug": "third-party"}
        with self.assertRaisesRegex(MODULE.ProposalError, "Expected one canary check"):
            MODULE.validate_canary(FakeReader(payloads), 25, PROPOSED_SHA)

    def test_rejects_wrong_workflow_run(self) -> None:
        payloads = responses()
        payloads["/repos/agiletec-inc/github-actions/actions/runs/77"]["path"] = (
            ".github/workflows/other.yml"
        )
        with self.assertRaisesRegex(MODULE.ProposalError, "does not match"):
            MODULE.validate_canary(FakeReader(payloads), 25, PROPOSED_SHA)

    def test_rejects_inactive_or_ambiguous_effective_ruleset(self) -> None:
        ruleset = responses()["/repos/agiletec-inc/agiletec/rulesets/19456040"]
        ruleset["enforcement"] = "disabled"
        with self.assertRaisesRegex(MODULE.ProposalError, "not active"):
            MODULE.validate_effective_workflow(ruleset, REPOSITORY_ID)

    def test_schema_and_script_keep_fixed_authority_boundary(self) -> None:
        schema = json.loads(
            (
                ROOT / "schemas" / "ruleset-workflow-pin-proposal-v1.schema.json"
            ).read_text()
        )
        self.assertEqual(
            schema["properties"]["operation"]["const"], "ruleset-workflow-pin"
        )
        target = schema["properties"]["target"]["properties"]
        self.assertEqual(target["organization"]["const"], "agiletec-inc")
        self.assertEqual(target["ruleset_id"]["const"], 19456040)
        source = SCRIPT.read_text()
        self.assertNotRegex(source, r'method="(?:POST|PUT|PATCH|DELETE)"')
        self.assertNotIn("--token", source)
        self.assertNotIn("admin:org", source)
        self.assertNotIn("dotenv", source)


if __name__ == "__main__":
    unittest.main()
