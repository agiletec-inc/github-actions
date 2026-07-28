#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any


ORGANIZATION = "agiletec-inc"
SOURCE_REPOSITORY = "github-actions"
CANARY_REPOSITORY = "github-actions"
EFFECTIVE_REPOSITORY = "agiletec"
RULESET_ID = 19456040
TARGET_WORKFLOW = ".github/workflows/org-quality-gate.yml"
CANARY_WORKFLOW = ".github/workflows/ci.yml"
CANARY_CHECK = "test"


class ProposalError(RuntimeError):
    pass


class GitHubReader:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get_object(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            raise ProposalError(f"GitHub API GET {path} failed: {error}") from error
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProposalError(
                f"GitHub API GET {path} returned invalid JSON"
            ) from error
        if not isinstance(decoded, dict):
            raise ProposalError(f"GitHub API GET {path} did not return an object")
        return decoded


def require_string(record: dict[str, Any], key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ProposalError(f"{context} has invalid {key}")
    return value


def require_integer(record: dict[str, Any], key: str, context: str) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProposalError(f"{context} has invalid {key}")
    return value


def validate_candidate(reader: GitHubReader, proposed_sha: str) -> int:
    repository = reader.get_object(f"/repos/{ORGANIZATION}/{SOURCE_REPOSITORY}")
    repository_id = require_integer(repository, "id", "source repository")
    if require_string(repository, "default_branch", "source repository") != "main":
        raise ProposalError("Source repository default branch is not main")
    commit = reader.get_object(
        f"/repos/{ORGANIZATION}/{SOURCE_REPOSITORY}/commits/{proposed_sha}"
    )
    if require_string(commit, "sha", "candidate commit") != proposed_sha:
        raise ProposalError("Candidate commit SHA mismatch")
    comparison = reader.get_object(
        f"/repos/{ORGANIZATION}/{SOURCE_REPOSITORY}/compare/{proposed_sha}...main"
    )
    if comparison.get("status") not in {"ahead", "identical"}:
        raise ProposalError("Candidate SHA is not reachable from github-actions main")
    return repository_id


def validate_canary(
    reader: GitHubReader, canary_pr: int, proposed_sha: str
) -> dict[str, object]:
    repository_path = f"/repos/{ORGANIZATION}/{CANARY_REPOSITORY}"
    pull = reader.get_object(f"{repository_path}/pulls/{canary_pr}")
    state = pull.get("state")
    merged_at = pull.get("merged_at")
    if state != "open" and not (state == "closed" and isinstance(merged_at, str)):
        raise ProposalError("Canary pull request is neither open nor merged")
    base = pull.get("base")
    head = pull.get("head")
    if (
        not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
    ):
        raise ProposalError("Canary pull request has an invalid base or head")
    head_sha = require_string(head, "sha", "canary pull request head")
    if head_sha != proposed_sha:
        raise ProposalError("Canary pull request head does not match the proposed SHA")
    checks = reader.get_object(
        f"{repository_path}/commits/{head_sha}/check-runs?filter=latest&per_page=100"
    )
    check_runs = checks.get("check_runs")
    if not isinstance(check_runs, list):
        raise ProposalError("Canary check-runs response is invalid")
    matching = [
        check
        for check in check_runs
        if isinstance(check, dict)
        and check.get("name") == CANARY_CHECK
        and isinstance(check.get("app"), dict)
        and check["app"].get("slug") == "github-actions"
    ]
    if len(matching) != 1:
        raise ProposalError(f"Expected one canary check, found {len(matching)}")
    check = matching[0]
    if check.get("status") != "completed" or check.get("conclusion") != "success":
        raise ProposalError("Canary check is not successful")
    check_id = require_integer(check, "id", "canary check")
    details_url = require_string(check, "details_url", "canary check")
    run_match = re.search(r"/actions/runs/(\d+)(?:/|$)", details_url)
    if run_match is None:
        raise ProposalError("Canary check has no workflow run URL")
    run_id = int(run_match.group(1))
    run = reader.get_object(f"{repository_path}/actions/runs/{run_id}")
    if run.get("head_sha") != head_sha or run.get("path") != CANARY_WORKFLOW:
        raise ProposalError(
            "Canary workflow run does not match the candidate head or path"
        )
    if run.get("conclusion") != "success" or run.get("status") != "completed":
        raise ProposalError("Canary workflow run is not successful")
    return {
        "repository": f"{ORGANIZATION}/{CANARY_REPOSITORY}",
        "pull_request": canary_pr,
        "head_sha": head_sha,
        "check_name": CANARY_CHECK,
        "check_run_id": check_id,
        "workflow_run_id": run_id,
        "workflow_path": CANARY_WORKFLOW,
        "conclusion": "success",
    }


def validate_effective_workflow(ruleset: dict[str, Any], repository_id: int) -> None:
    if ruleset.get("id") != RULESET_ID:
        raise ProposalError("Effective Ruleset ID mismatch")
    if (
        ruleset.get("source_type") != "Organization"
        or ruleset.get("source") != ORGANIZATION
    ):
        raise ProposalError("Effective Ruleset authority mismatch")
    if ruleset.get("enforcement") != "active":
        raise ProposalError("Effective Ruleset is not active")
    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        raise ProposalError("Effective Ruleset has invalid rules")
    matching: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "workflows":
            continue
        parameters = rule.get("parameters")
        workflows = (
            parameters.get("workflows") if isinstance(parameters, dict) else None
        )
        if not isinstance(workflows, list):
            raise ProposalError("Effective workflow rule has invalid workflows")
        for workflow in workflows:
            if not isinstance(workflow, dict):
                raise ProposalError("Effective Ruleset has an invalid workflow entry")
            if (
                workflow.get("repository_id") == repository_id
                and workflow.get("path") == TARGET_WORKFLOW
                and workflow.get("ref") == "refs/heads/main"
            ):
                matching.append(workflow)
    if len(matching) != 1:
        raise ProposalError(f"Expected one effective workflow, found {len(matching)}")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_proposal(
    repository_id: int,
    proposed_sha: str,
    canary: dict[str, object],
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "operation": "ruleset-workflow-pin",
        "target": {
            "organization": ORGANIZATION,
            "ruleset_id": RULESET_ID,
            "workflow": {
                "repository_id": repository_id,
                "path": TARGET_WORKFLOW,
                "ref": "refs/heads/main",
            },
        },
        "change": {"proposed_sha": proposed_sha},
        "canary": canary,
    }
    digest = hashlib.sha256(canonical_json(unsigned).encode()).hexdigest()
    return {**unsigned, "digest": f"sha256:{digest}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposed-sha", required=True)
    parser.add_argument("--canary-pr", type=int, required=True)
    parser.add_argument("--api-base-url", default="https://api.github.com")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.proposed_sha):
        raise ProposalError(
            "--proposed-sha must be a 40-character lowercase commit SHA"
        )
    if args.canary_pr < 1:
        raise ProposalError("--canary-pr must be positive")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ProposalError("GH_TOKEN is required")

    reader = GitHubReader(args.api_base_url, token)
    repository_id = validate_candidate(reader, args.proposed_sha)
    canary = validate_canary(reader, args.canary_pr, args.proposed_sha)
    ruleset = reader.get_object(
        f"/repos/{ORGANIZATION}/{EFFECTIVE_REPOSITORY}/rulesets/{RULESET_ID}"
    )
    validate_effective_workflow(ruleset, repository_id)
    proposal = build_proposal(repository_id, args.proposed_sha, canary)
    print(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProposalError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
