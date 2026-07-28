from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BROKER = (ROOT / "policy_broker" / "ruleset_pin_broker.py").read_text()
TEMPLATE = (ROOT / "policy_broker" / "template.yaml").read_text()


class PolicyBrokerProviderContractTest(unittest.TestCase):
    def test_uses_sign_only_kms_and_default_deny(self) -> None:
        self.assertIn('Action: kms:Sign', TEMPLATE)
        self.assertNotIn('kms:Decrypt', TEMPLATE)
        self.assertIn("Default: 'false'", TEMPLATE)
        self.assertIn('RSASSA_PKCS1_V1_5_SHA_256', BROKER)

    def test_fixes_the_non_weakening_target(self) -> None:
        self.assertIn('RULESET_ID = 19456040', BROKER)
        self.assertIn('root["operation"] != "ruleset-workflow-pin"', BROKER)
        self.assertIn('WORKFLOW_PATH = ".github/workflows/org-quality-gate.yml"', BROKER)


if __name__ == "__main__":
    unittest.main()
