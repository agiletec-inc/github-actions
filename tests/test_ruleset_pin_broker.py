import copy
import io
import json
import unittest
import urllib.error

from policy_broker.ruleset_pin_broker import (
    EFFECTIVE_REPOSITORY,
    ORGANIZATION,
    RULESET_ID,
    SOURCE_REPOSITORY,
    WORKFLOW_PATH,
    WORKFLOW_REF,
    GithubResponse,
    GithubClient,
    GithubFailure,
    RejectedProposal,
    RulesetBroker,
    canonical_digest,
    github_app_jwt,
    replace_workflow_sha,
    validate_proposal,
)

SOURCE_ID = 1234
OLD_SHA = "1" * 40
NEW_SHA = "2" * 40


def proposal():
    value = {
        "schema_version": 1,
        "operation": "ruleset-workflow-pin",
        "target": {
            "organization": ORGANIZATION,
            "ruleset_id": RULESET_ID,
            "workflow": {
                "repository_id": SOURCE_ID,
                "path": WORKFLOW_PATH,
                "ref": WORKFLOW_REF,
            },
        },
        "change": {"proposed_sha": NEW_SHA},
        "canary": {
            "repository": SOURCE_REPOSITORY,
            "pull_request": 26,
            "head_sha": NEW_SHA,
            "check_name": "test",
            "check_run_id": 10,
            "workflow_run_id": 11,
            "workflow_path": ".github/workflows/ci.yml",
            "conclusion": "success",
        },
        "digest": "",
    }
    value["digest"] = canonical_digest(value)
    return value


def ruleset(sha=OLD_SHA):
    return {
        "id": RULESET_ID,
        "name": "Main Branch Protection",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {
                "type": "pull_request",
                "parameters": {"required_approving_review_count": 0},
            },
            {
                "type": "workflows",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "workflows": [
                        {
                            "repository_id": SOURCE_ID,
                            "path": WORKFLOW_PATH,
                            "ref": WORKFLOW_REF,
                            "sha": sha,
                        }
                    ],
                },
            },
        ],
    }


def canary_responses():
    return [
        {
            "name": "test",
            "head_sha": NEW_SHA,
            "conclusion": "success",
            "check_suite": {"id": 99},
        },
        {
            "id": 11,
            "head_sha": NEW_SHA,
            "conclusion": "success",
            "event": "pull_request",
            "path": ".github/workflows/ci.yml",
            "repository": {"full_name": SOURCE_REPOSITORY},
            "check_suite_id": 99,
            "pull_requests": [{"number": 26}],
        },
    ]


class FakeAudit:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


class FakeGithub:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return GithubResponse(copy.deepcopy(response), "request-id")


class ProposalTests(unittest.TestCase):
    def test_accepts_exact_schema_and_digest(self):
        self.assertEqual(
            validate_proposal(proposal(), SOURCE_ID)["change"]["proposed_sha"], NEW_SHA
        )

    def test_rejects_unknown_field_digest_and_target(self):
        for mutate in (
            lambda value: value.update({"extra": True}),
            lambda value: value.update({"digest": "sha256:" + "0" * 64}),
            lambda value: value["target"].update({"ruleset_id": 1}),
        ):
            value = proposal()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(RejectedProposal):
                validate_proposal(value, SOURCE_ID)

    def test_canary_must_prove_candidate(self):
        value = proposal()
        value["canary"]["head_sha"] = OLD_SHA
        value["digest"] = canonical_digest(value)
        with self.assertRaises(RejectedProposal):
            validate_proposal(value, SOURCE_ID)


class RulesetTests(unittest.TestCase):
    def test_only_sha_changes(self):
        current = ruleset()
        desired, before = replace_workflow_sha(current, SOURCE_ID, NEW_SHA)
        self.assertEqual(before, OLD_SHA)
        self.assertEqual(
            current["rules"][1]["parameters"]["workflows"][0]["sha"], OLD_SHA
        )
        self.assertEqual(
            desired["rules"][1]["parameters"]["workflows"][0]["sha"], NEW_SHA
        )

    def test_rejects_unpinned_or_duplicate_target(self):
        unpinned = ruleset()
        del unpinned["rules"][1]["parameters"]["workflows"][0]["sha"]
        duplicate = ruleset()
        duplicate["rules"][1]["parameters"]["workflows"].append(
            copy.deepcopy(duplicate["rules"][1]["parameters"]["workflows"][0])
        )
        for value in (unpinned, duplicate):
            with self.subTest(value=value), self.assertRaises(RejectedProposal):
                replace_workflow_sha(value, SOURCE_ID, NEW_SHA)


class BrokerTests(unittest.TestCase):
    def test_kill_switch_defaults_to_dry_run(self):
        audit = FakeAudit()
        github = FakeGithub([*canary_responses(), ruleset()])
        result = RulesetBroker(github, audit, SOURCE_ID, False).apply(
            proposal(), "owner", "test"
        )
        self.assertEqual(result["status"], "approved")
        self.assertTrue(result["dry_run"])
        self.assertEqual(
            [request[0] for request in github.requests], ["GET", "GET", "GET"]
        )
        self.assertEqual(audit.records[0]["result"], "approved")

    def test_applies_after_cas_and_reads_back_org_and_effective_rulesets(self):
        audit = FakeAudit()
        github = FakeGithub(
            [
                *canary_responses(),
                ruleset(),
                ruleset(),
                ruleset(NEW_SHA),
                ruleset(NEW_SHA),
            ]
        )
        result = RulesetBroker(github, audit, SOURCE_ID, True).apply(
            proposal(), "owner", "test"
        )
        self.assertEqual(
            result,
            {"status": "applied", "audit_id": result["audit_id"], "idempotent": False},
        )
        self.assertEqual(
            [request[0] for request in github.requests],
            ["GET", "GET", "GET", "GET", "PUT", "GET"],
        )
        self.assertIn(
            f"/repos/{EFFECTIVE_REPOSITORY}/rulesets/{RULESET_ID}",
            github.requests[-1][1],
        )
        self.assertEqual(audit.records[0]["github_request_id"], "request-id")

    def test_conflict_fails_closed_without_put(self):
        changed = ruleset()
        changed["enforcement"] = "evaluate"
        audit = FakeAudit()
        github = FakeGithub([*canary_responses(), ruleset(), changed])
        result = RulesetBroker(github, audit, SOURCE_ID, True).apply(
            proposal(), "owner", "test"
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [request[0] for request in github.requests], ["GET", "GET", "GET", "GET"]
        )

    def test_idempotent_candidate_does_not_mutate(self):
        audit = FakeAudit()
        github = FakeGithub([*canary_responses(), ruleset(NEW_SHA)])
        result = RulesetBroker(github, audit, SOURCE_ID, True).apply(
            proposal(), "owner", "test"
        )
        self.assertTrue(result["idempotent"])
        self.assertEqual(
            [request[0] for request in github.requests], ["GET", "GET", "GET"]
        )

    def test_forged_canary_is_rejected_before_ruleset_read(self):
        forged = canary_responses()
        forged[1]["check_suite_id"] = 100
        audit = FakeAudit()
        github = FakeGithub(forged)
        result = RulesetBroker(github, audit, SOURCE_ID, True).apply(
            proposal(), "owner", "test"
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(len(github.requests), 2)


class JwtTests(unittest.TestCase):
    def test_kms_signer_receives_header_and_payload_only(self):
        class FakeSigner:
            def __init__(self):
                self.message = None

            def sign(self, message):
                self.message = message
                return b"signature"

        signer = FakeSigner()
        token = github_app_jwt("client-id", signer, now=1000)
        self.assertEqual(token.count("."), 2)
        self.assertEqual(signer.message.decode(), token.rsplit(".", 1)[0])
        self.assertNotIn("signature", token)


class GithubClientTests(unittest.TestCase):
    class Response:
        def __init__(self, value):
            self.value = value
            self.headers = {"x-github-request-id": "request-id"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.value).encode()

    @staticmethod
    def error(status):
        return urllib.error.HTTPError(
            "https://api.github.com/test",
            status,
            "failure",
            {},
            io.BytesIO(b'{"message":"failure"}'),
        )

    def test_retries_5xx_then_succeeds(self):
        responses = [self.error(500), self.error(503), self.Response({"ok": True})]

        def opener(_request, timeout):
            self.assertEqual(timeout, 10)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        result = GithubClient("secret", opener).request("GET", "/test")
        self.assertEqual(result.body, {"ok": True})
        self.assertEqual(responses, [])

    def test_409_and_422_fail_without_retry(self):
        for status in (409, 422):
            calls = []

            def opener(_request, timeout):
                calls.append(timeout)
                raise self.error(status)

            with self.subTest(status=status), self.assertRaises(GithubFailure):
                GithubClient("secret", opener).request("PUT", "/test", {})
            self.assertEqual(calls, [10])

    def test_exhausted_5xx_does_not_expose_token(self):
        def opener(_request, timeout):
            self.assertEqual(timeout, 10)
            raise self.error(500)

        with self.assertRaises(GithubFailure) as failure:
            GithubClient("top-secret", opener).request("GET", "/test")
        self.assertNotIn("top-secret", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
