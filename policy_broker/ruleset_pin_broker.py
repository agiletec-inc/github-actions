from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

ORGANIZATION = "agiletec-inc"
RULESET_ID = 19456040
WORKFLOW_PATH = ".github/workflows/org-quality-gate.yml"
WORKFLOW_REF = "refs/heads/main"
SOURCE_REPOSITORY = "agiletec-inc/github-actions"
EFFECTIVE_REPOSITORY = "agiletec-inc/agiletec"
API_VERSION = "2026-03-10"
SHA_KEYS = {"proposed_sha"}


class RejectedProposal(ValueError):
    pass


class Conflict(RuntimeError):
    pass


class GithubFailure(RuntimeError):
    pass


class Signer(Protocol):
    def sign(self, message: bytes) -> bytes: ...


class AuditStore(Protocol):
    def append(self, record: dict[str, Any]) -> None: ...


def _expect_keys(value: Any, required: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise RejectedProposal(f"{where} must contain exactly {sorted(required)}")
    return value


def _is_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(c in "0123456789abcdef" for c in value)
    )


def canonical_digest(proposal: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in proposal.items() if key != "digest"}
    payload = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def validate_proposal(proposal: Any, source_repository_id: int) -> dict[str, Any]:
    root = _expect_keys(
        proposal,
        {"schema_version", "operation", "target", "change", "canary", "digest"},
        "proposal",
    )
    if root["schema_version"] != 1 or root["operation"] != "ruleset-workflow-pin":
        raise RejectedProposal("unsupported proposal operation or schema version")

    target = _expect_keys(
        root["target"], {"organization", "ruleset_id", "workflow"}, "target"
    )
    workflow = _expect_keys(
        target["workflow"], {"repository_id", "path", "ref"}, "workflow"
    )
    if (
        target["organization"] != ORGANIZATION
        or target["ruleset_id"] != RULESET_ID
        or workflow["repository_id"] != source_repository_id
        or workflow["path"] != WORKFLOW_PATH
        or workflow["ref"] != WORKFLOW_REF
    ):
        raise RejectedProposal("proposal target does not match the fixed broker target")

    change = _expect_keys(root["change"], SHA_KEYS, "change")
    if not _is_sha(change["proposed_sha"]):
        raise RejectedProposal("proposed_sha must be a lowercase 40-character SHA")

    canary = _expect_keys(
        root["canary"],
        {
            "repository",
            "pull_request",
            "head_sha",
            "check_name",
            "check_run_id",
            "workflow_run_id",
            "workflow_path",
            "conclusion",
        },
        "canary",
    )
    if (
        canary["repository"] != SOURCE_REPOSITORY
        or canary["workflow_path"] != ".github/workflows/ci.yml"
        or canary["check_name"] != "test"
        or canary["conclusion"] != "success"
        or not _is_sha(canary["head_sha"])
        or canary["head_sha"] != change["proposed_sha"]
        or not all(
            isinstance(canary[key], int) and canary[key] > 0
            for key in ("pull_request", "check_run_id", "workflow_run_id")
        )
    ):
        raise RejectedProposal("canary does not prove the proposed workflow SHA")
    if root["digest"] != canonical_digest(root):
        raise RejectedProposal("proposal digest mismatch")
    return root


def mutation_body(ruleset: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")
    if not all(key in ruleset for key in keys):
        raise RejectedProposal("GitHub Ruleset response is missing mutation fields")
    return {key: copy.deepcopy(ruleset[key]) for key in keys}


def replace_workflow_sha(
    ruleset: dict[str, Any], source_repository_id: int, proposed_sha: str
) -> tuple[dict[str, Any], str]:
    body = mutation_body(ruleset)
    matches: list[dict[str, Any]] = []
    for rule in body["rules"]:
        if rule.get("type") != "workflows":
            continue
        for workflow in rule.get("parameters", {}).get("workflows", []):
            if (
                workflow.get("repository_id") == source_repository_id
                and workflow.get("path") == WORKFLOW_PATH
                and workflow.get("ref") == WORKFLOW_REF
            ):
                matches.append(workflow)
    if len(matches) != 1:
        raise RejectedProposal("fixed required workflow target must occur exactly once")
    current_sha = matches[0].get("sha")
    if not _is_sha(current_sha):
        raise RejectedProposal("current required workflow is not SHA pinned")
    matches[0]["sha"] = proposed_sha
    return body, current_sha


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def github_app_jwt(app_id: str, signer: Signer, now: int | None = None) -> str:
    timestamp = int(time.time()) if now is None else now
    header = _b64url(b'{"alg":"RS256","typ":"JWT"}')
    payload = _b64url(
        json.dumps(
            {"iat": timestamp - 60, "exp": timestamp + 540, "iss": app_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_b64url(signer.sign(signing_input.encode()))}"


@dataclass(frozen=True)
class GithubResponse:
    body: Any
    request_id: str | None


class GithubClient:
    def __init__(self, token: str, opener: Any = urllib.request.urlopen):
        self._token = token
        self._opener = opener

    def request(
        self, method: str, path: str, body: Any | None = None
    ) -> GithubResponse:
        data = (
            None if body is None else json.dumps(body, separators=(",", ":")).encode()
        )
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "agiletec-ruleset-policy-broker",
            },
        )
        for attempt in range(3):
            try:
                with self._opener(request, timeout=10) as response:
                    raw = response.read()
                    return GithubResponse(
                        json.loads(raw) if raw else None,
                        response.headers.get("x-github-request-id"),
                    )
            except urllib.error.HTTPError as error:
                try:
                    detail = error.read().decode(errors="replace")[:500]
                finally:
                    error.close()
                if 500 <= error.code < 600 and attempt < 2:
                    continue
                raise GithubFailure(
                    f"GitHub API {method} {path} failed with {error.code}: {detail}"
                ) from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < 2:
                    continue
                raise GithubFailure(
                    f"GitHub API {method} {path} transport failure"
                ) from error
        raise AssertionError("unreachable")


def installation_token(app_id: str, installation_id: str, signer: Signer) -> str:
    response = GithubClient(github_app_jwt(app_id, signer)).request(
        "POST", f"/app/installations/{installation_id}/access_tokens"
    )
    token = response.body.get("token") if isinstance(response.body, dict) else None
    if not isinstance(token, str) or not token:
        raise GithubFailure("GitHub did not return an installation token")
    return token


def verify_canary(github: GithubClient, proposal: dict[str, Any]) -> None:
    canary = proposal["canary"]
    check = github.request(
        "GET", f"/repos/{SOURCE_REPOSITORY}/check-runs/{canary['check_run_id']}"
    ).body
    run = github.request(
        "GET", f"/repos/{SOURCE_REPOSITORY}/actions/runs/{canary['workflow_run_id']}"
    ).body
    check_suite_id = (
        check.get("check_suite", {}).get("id") if isinstance(check, dict) else None
    )
    pull_requests = run.get("pull_requests", []) if isinstance(run, dict) else []
    if (
        not isinstance(check, dict)
        or not isinstance(run, dict)
        or check.get("name") != canary["check_name"]
        or check.get("head_sha") != canary["head_sha"]
        or check.get("conclusion") != "success"
        or run.get("id") != canary["workflow_run_id"]
        or run.get("head_sha") != canary["head_sha"]
        or run.get("conclusion") != "success"
        or run.get("event") != "pull_request"
        or run.get("path") != canary["workflow_path"]
        or run.get("repository", {}).get("full_name") != SOURCE_REPOSITORY
        or run.get("check_suite_id") != check_suite_id
        or not any(
            item.get("number") == canary["pull_request"] for item in pull_requests
        )
    ):
        raise RejectedProposal("GitHub read-back did not verify the proposal canary")


class RulesetBroker:
    def __init__(
        self,
        github: GithubClient,
        audit: AuditStore,
        source_repository_id: int,
        apply_enabled: bool,
    ):
        self.github = github
        self.audit = audit
        self.source_repository_id = source_repository_id
        self.apply_enabled = apply_enabled

    def apply(self, proposal: Any, actor: str, workload: str) -> dict[str, Any]:
        audit_id = str(uuid.uuid4())
        timestamp = int(time.time())
        digest = proposal.get("digest") if isinstance(proposal, dict) else None
        record: dict[str, Any] = {
            "audit_id": audit_id,
            "proposal_digest": digest,
            "actor": actor,
            "workload": workload,
            "timestamp": timestamp,
        }
        try:
            validated = validate_proposal(proposal, self.source_repository_id)
            verify_canary(self.github, validated)
            proposed_sha = validated["change"]["proposed_sha"]
            path = f"/orgs/{ORGANIZATION}/rulesets/{RULESET_ID}"
            initial = self.github.request("GET", path)
            desired, before_sha = replace_workflow_sha(
                initial.body, self.source_repository_id, proposed_sha
            )
            record.update({"before_sha": before_sha, "after_sha": proposed_sha})
            if before_sha == proposed_sha:
                record["result"] = "applied"
                self.audit.append(record)
                return {"status": "applied", "audit_id": audit_id, "idempotent": True}
            if not self.apply_enabled:
                record["result"] = "approved"
                self.audit.append(record)
                return {"status": "approved", "audit_id": audit_id, "dry_run": True}

            current = self.github.request("GET", path)
            if mutation_body(current.body) != mutation_body(initial.body):
                raise Conflict("Ruleset changed after admission read")
            updated = self.github.request("PUT", path, desired)
            applied, applied_sha = replace_workflow_sha(
                updated.body, self.source_repository_id, proposed_sha
            )
            if applied_sha != proposed_sha or applied != desired:
                raise GithubFailure(
                    "organization Ruleset read-back did not match the candidate"
                )
            effective = self.github.request(
                "GET",
                f"/repos/{EFFECTIVE_REPOSITORY}/rulesets/{RULESET_ID}?includes_parents=true",
            )
            _, effective_sha = replace_workflow_sha(
                effective.body, self.source_repository_id, proposed_sha
            )
            if effective_sha != proposed_sha:
                raise GithubFailure(
                    "effective repository Ruleset did not expose the candidate"
                )
            record.update(
                {"result": "applied", "github_request_id": updated.request_id}
            )
            self.audit.append(record)
            return {"status": "applied", "audit_id": audit_id, "idempotent": False}
        except RejectedProposal as error:
            record.update({"result": "rejected", "reason": str(error)})
            self.audit.append(record)
            return {"status": "rejected", "audit_id": audit_id, "reason": str(error)}
        except (Conflict, GithubFailure) as error:
            record.update({"result": "failed", "reason": str(error)})
            self.audit.append(record)
            return {"status": "failed", "audit_id": audit_id, "reason": str(error)}


class KmsSigner:
    def __init__(self, kms: Any, key_id: str):
        self.kms = kms
        self.key_id = key_id

    def sign(self, message: bytes) -> bytes:
        response = self.kms.sign(
            KeyId=self.key_id,
            Message=message,
            MessageType="RAW",
            SigningAlgorithm="RSASSA_PKCS1_V1_5_SHA_256",
        )
        return response["Signature"]


class DynamoAuditStore:
    def __init__(self, table: Any):
        self.table = table

    def append(self, record: dict[str, Any]) -> None:
        self.table.put_item(
            Item=record, ConditionExpression="attribute_not_exists(audit_id)"
        )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    import boto3

    required_env = (
        "GITHUB_APP_ID",
        "GITHUB_INSTALLATION_ID",
        "KMS_KEY_ARN",
        "AUDIT_TABLE",
        "SOURCE_REPOSITORY_ID",
    )
    missing = [name for name in required_env if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing broker configuration: {', '.join(missing)}")
    source_repository_id = int(os.environ["SOURCE_REPOSITORY_ID"])
    signer = KmsSigner(boto3.client("kms"), os.environ["KMS_KEY_ARN"])
    token = installation_token(
        os.environ["GITHUB_APP_ID"], os.environ["GITHUB_INSTALLATION_ID"], signer
    )
    github = GithubClient(token)
    audit = DynamoAuditStore(
        boto3.resource("dynamodb").Table(os.environ["AUDIT_TABLE"])
    )
    broker = RulesetBroker(
        github,
        audit,
        source_repository_id,
        os.environ.get("APPLY_ENABLED") == "true",
    )
    return broker.apply(
        event.get("proposal"),
        str(event.get("actor", "unknown"))[:200],
        str(event.get("workload", "unknown"))[:200],
    )
