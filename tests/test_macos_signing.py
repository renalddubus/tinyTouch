"""Check that release signing cannot silently revert to a changing identity."""

import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MacOSSigningTests(unittest.TestCase):
    def reject_signing(self, **settings):
        environment = os.environ.copy()
        environment.update(settings)
        result = subprocess.run(
            ["zsh", str(ROOT / "release/sign-macos-cli.sh"), "/nonexistent/cli"],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        return result.stderr

    def test_ad_hoc_signature_requires_explicit_test_opt_in(self):
        error = self.reject_signing(
            TINYTOUCH_SIGNING_IDENTITY="-", TINYTOUCH_ALLOW_ADHOC="0"
        )
        self.assertIn("Ad hoc signing changes Keychain identity", error)

    def test_release_forbids_ad_hoc_even_with_test_opt_in(self):
        error = self.reject_signing(
            TINYTOUCH_SIGNING_IDENTITY="-",
            TINYTOUCH_ALLOW_ADHOC="1",
            TINYTOUCH_REQUIRE_STABLE_IDENTITY="1",
        )
        self.assertIn("require a stable certificate signature", error)

    def test_release_requires_an_explicit_team_pin(self):
        error = self.reject_signing(
            TINYTOUCH_SIGNING_IDENTITY="certificate",
            TINYTOUCH_SIGNING_TEAM_ID="",
            TINYTOUCH_REQUIRE_STABLE_IDENTITY="1",
        )
        self.assertIn("require a pinned", error)

    def test_signing_script_requests_hardened_runtime_for_every_binary(self):
        script = (ROOT / "release/sign-macos-cli.sh").read_text()
        self.assertGreaterEqual(script.count("--options runtime"), 3)
        self.assertIn("_internal", script)
        self.assertNotIn("--timestamp=none --identifier", script)
        self.assertIn("must be signed with hardened runtime", script)


class InstallerStampTests(unittest.TestCase):
    def stamp(self, team_id, required="0"):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "install.sh"
            environment = {
                **os.environ,
                "TINYTOUCH_SIGNING_TEAM_ID": team_id,
                "TINYTOUCH_REQUIRE_STABLE_IDENTITY": required,
            }
            result = subprocess.run(
                ["python3", str(ROOT / "release/stamp-installer.py"),
                 str(ROOT / "release/install.sh"), str(output)],
                env=environment, capture_output=True, text=True,
            )
            text = output.read_text() if output.exists() else ""
            return result, text

    def test_release_installer_pins_the_team(self):
        result, text = self.stamp("ABCDE12345", required="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pinned_team_id='ABCDE12345'", text)
        self.assertNotIn("'__TINYTOUCH_TEAM_ID__'", text)

    def test_release_installer_requires_a_valid_team(self):
        for team_id in ("", "abc", "ABCDE1234!"):
            with self.subTest(team_id=team_id):
                result, _ = self.stamp(team_id, required="1")
                self.assertNotEqual(result.returncode, 0)

    def test_development_installer_stays_unstamped(self):
        result, text = self.stamp("", required="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'__TINYTOUCH_TEAM_ID__'", text)


if __name__ == "__main__":
    unittest.main()
