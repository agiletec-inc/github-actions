from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".github/scripts/feature_flag_check.py"


class FeatureFlagCheckTests(unittest.TestCase):
    def run_check(self, manifest: str | None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            if manifest is not None:
                airis = root / ".airis"
                airis.mkdir()
                (airis / "flags.toml").write_text(textwrap.dedent(manifest))
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--today", "2026-07-22"],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_skips_repositories_without_a_manifest(self) -> None:
        result = self.run_check(None)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runs_temporary_flag_off_and_on_tests(self) -> None:
        result = self.run_check(
            """
            [[flags]]
            key = "checkout.v2"
            kind = "release"
            type = "boolean"
            owner = "team:billing"
            expires = "2026-12-31"
            cleanup_issue = "https://github.com/agiletec-inc/example/issues/123"

            [flags.tests.off]
            command = 'test "$CHECKOUT_V2" = false'
            environment = { CHECKOUT_V2 = "false" }

            [flags.tests.on]
            command = 'test "$CHECKOUT_V2" = true'
            environment = { CHECKOUT_V2 = "true" }
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Feature flag check passed: 1 definitions", result.stdout)

    def test_rejects_temporary_flags_without_cleanup_or_tests(self) -> None:
        result = self.run_check(
            """
            [[flags]]
            key = "checkout.v2"
            kind = "release"
            type = "boolean"
            owner = "team:billing"
            expires = "2026-12-31"
            """
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cleanup_issue", result.stderr)

    def test_rejects_expired_temporary_flags(self) -> None:
        result = self.run_check(
            """
            [[flags]]
            key = "checkout.v2"
            kind = "experiment"
            type = "boolean"
            owner = "team:billing"
            expires = "2020-01-01"
            cleanup_issue = "https://github.com/agiletec-inc/example/issues/123"

            [flags.tests.off]
            command = "true"

            [flags.tests.on]
            command = "true"
            """
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expired", result.stderr)


if __name__ == "__main__":
    unittest.main()
