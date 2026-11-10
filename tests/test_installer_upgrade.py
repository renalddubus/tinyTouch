"""Exercise the installer without accessing real devices or user credentials."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "The installer requires macOS tools")
class InstallerUpgradeTests(unittest.TestCase):
    def test_helper_authorization_precedes_replacing_the_cli_command(self):
        for upgrade_result in (0, 1):
            with self.subTest(
                upgrade_result=upgrade_result
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                release, commands, home = root / "release", root / "bin", root / "home"
                for path in (release, commands, home):
                    path.mkdir()
                old_cli = commands / "tinytouch"
                old_cli.write_text("old CLI")
                fake_cli = b"""#!/bin/sh
if [ "$1" = --version ]; then
  echo 'tinyTouch CLI 0.1.32'
else
  test "$1" = _upgrade-helper || exit 2
  echo checked > "$TINYTOUCH_TEST_CHECK"
  exit "$TINYTOUCH_TEST_RESULT"
fi
"""
                archive = release / "tinytouch-macos-arm64.tar.gz"
                with tarfile.open(archive, "w:gz") as bundle:
                    for name, data in (
                        ("tinytouch/tinytouch", fake_cli),
                        ("tinytouch/_internal/runtime", b"test"),
                    ):
                        entry = tarfile.TarInfo(name)
                        entry.size, entry.mode = len(data), 0o755
                        bundle.addfile(entry, io.BytesIO(data))
                manifest = {
                    "version": "0.1.32",
                    "cli": {
                        "macos-arm64": {
                            "file": archive.name,
                            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        }
                    },
                }
                (release / "release-manifest.json").write_text(json.dumps(manifest))
                for name, script in {
                    "codesign": (
                        "#!/bin/sh\n"
                        'case $1 in\n'
                        '  --verify) exit "${TINYTOUCH_TEST_SIGNATURE:-0}";;\n'
                        '  -d) echo "flags=0x10000(runtime)" >&2;;\n'
                        'esac\n'
                    ),
                    "uname": "#!/bin/sh\ncase $1 in -s) echo Darwin;; -m) echo arm64;; esac\n",
                    "curl": '#!/bin/sh\n/bin/cp "$TINYTOUCH_TEST_RELEASE/${2##*/}" "$4"\n',
                }.items():
                    command = commands / name
                    command.write_text(script)
                    command.chmod(0o755)
                environment = {
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{commands}:{os.environ['PATH']}",
                    "TINYTOUCH_INSTALL_DIR": str(commands),
                    "TINYTOUCH_RELEASE_ROOT": "https://test",
                    "TINYTOUCH_TEST_RELEASE": str(release),
                    "TINYTOUCH_TEST_CHECK": str(root / "checked"),
                    "TINYTOUCH_TEST_RESULT": str(upgrade_result),
                    "TINYTOUCH_EXPECTED_TEAM_ID": "TESTTEAM01",
                }
                result = subprocess.run(
                    ["/bin/sh", str(ROOT / "release/install.sh")],
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertTrue((root / "checked").exists(), result.stderr)
                if upgrade_result:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(old_cli.is_symlink())
                    self.assertEqual(old_cli.read_text(), "old CLI")
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(old_cli.is_symlink())

    def run_installer(self, root, **settings):
        release, commands, home = root / "release", root / "bin", root / "home"
        for path in (release, commands, home):
            path.mkdir(exist_ok=True)
        fake_cli = b"#!/bin/sh\necho executed > \"$TINYTOUCH_TEST_CHECK\"\n"
        archive = release / "tinytouch-macos-arm64.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in (
                ("tinytouch/tinytouch", fake_cli),
                ("tinytouch/_internal/runtime", b"test"),
            ):
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode = len(data), 0o755
                bundle.addfile(entry, io.BytesIO(data))
        manifest = {
            "version": "0.1.32",
            "cli": {
                "macos-arm64": {
                    "file": archive.name,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                }
            },
        }
        (release / "release-manifest.json").write_text(json.dumps(manifest))
        for name, script in {
            "codesign": '#!/bin/sh\ncase $1 in --verify) exit "${TINYTOUCH_TEST_SIGNATURE:-0}";; esac\n',
            "uname": "#!/bin/sh\ncase $1 in -s) echo Darwin;; -m) echo arm64;; esac\n",
            "curl": '#!/bin/sh\n/bin/cp "$TINYTOUCH_TEST_RELEASE/${2##*/}" "$4"\n',
        }.items():
            command = commands / name
            command.write_text(script)
            command.chmod(0o755)
        environment = {
            **os.environ,
            "HOME": str(home),
            "PATH": f"{commands}:{os.environ['PATH']}",
            "TINYTOUCH_INSTALL_DIR": str(commands),
            "TINYTOUCH_RELEASE_ROOT": "https://test",
            "TINYTOUCH_TEST_RELEASE": str(release),
            "TINYTOUCH_TEST_CHECK": str(root / "executed"),
            **settings,
        }
        return subprocess.run(
            ["/bin/sh", str(ROOT / "release/install.sh")],
            env=environment,
            capture_output=True,
            text=True,
        )

    def test_unsigned_or_wrong_team_cli_is_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_installer(
                root,
                TINYTOUCH_EXPECTED_TEAM_ID="TESTTEAM01",
                TINYTOUCH_TEST_SIGNATURE="1",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not signed by the expected developer", result.stderr)
            self.assertFalse((root / "executed").exists())
            self.assertEqual(list((root / "home").rglob("tinytouch*")), [])

    def test_installer_without_a_pinned_team_refuses_to_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_installer(root, TINYTOUCH_EXPECTED_TEAM_ID="")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no pinned signing team", result.stderr)
            self.assertFalse((root / "executed").exists())


if __name__ == "__main__":
    unittest.main()
