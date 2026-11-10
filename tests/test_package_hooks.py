"""Run the package hooks with all system paths redirected to temporary files."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestPackageHooks(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="fprintd-hooks-")
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.config = self.root / "etc" / "fprintd-prompt.conf"
        self.config.parent.mkdir()
        self.config.write_text("Touch sensor\n", encoding="utf-8")
        self.calls = self.root / "calls"
        self.command = self.root / "fprintd-prompt"
        self.command.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$FPRINTD_TEST_CALLS"\n'
            'if [ "$FPRINTD_TEST_EXIT" -ne 0 ]; then\n'
            '    printf "injected catalog rebuild failure\\n" >&2\n'
            'fi\n'
            'exit "$FPRINTD_TEST_EXIT"\n',
            encoding="utf-8",
        )
        self.command.chmod(0o755)
        hook = Path(__file__).resolve().parent.parent / "fprintd-prompt.install"
        self.script = (
            hook.read_text(encoding="utf-8")
            .replace("/etc/", str(self.root / "etc") + "/")
            .replace("/var/lib/", str(self.root / "var" / "lib") + "/")
            .replace("/usr/bin/fprintd-prompt", str(self.command))
        )

    def run_hook(self, hook, exit_code=0):
        return subprocess.run(
            ["bash", "-c", self.script + '\n"$1"\n', "package-hook", hook],
            capture_output=True, text=True,
            env=dict(os.environ, FPRINTD_TEST_CALLS=str(self.calls),
                     FPRINTD_TEST_EXIT=str(exit_code)),
        )

    def test_rebuild_failure_keeps_error_and_warning_without_failing_hook(self):
        for hook in ("post_install", "post_upgrade"):
            with self.subTest(hook=hook):
                result = self.run_hook(hook, exit_code=23)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("injected catalog rebuild failure", result.stderr)
                self.assertIn("Warning: failed to regenerate catalog", result.stdout)
                self.assertIn("fprintd-prompt apply", result.stdout)
                self.assertEqual(self.config.read_text(), "Touch sensor\n")
        self.assertEqual(self.calls.read_text(), "apply\napply\n")

    def test_successful_rebuild_does_not_warn(self):
        for hook in ("post_install", "post_upgrade"):
            with self.subTest(hook=hook):
                result = self.run_hook(hook)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertNotIn("Warning:", result.stdout)
        self.assertEqual(self.calls.read_text(), "apply\napply\n")

    def test_no_config_skips_rebuild(self):
        self.config.unlink()
        for hook in ("post_install", "post_upgrade"):
            with self.subTest(hook=hook):
                result = self.run_hook(hook, exit_code=23)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "")
        self.assertFalse(self.calls.exists())

    def test_removal_deletes_catalog_but_keeps_configuration(self):
        state = self.root / "var" / "lib" / "fprintd-prompt"
        state.mkdir(parents=True)
        catalog = state / "fprintd.mo"
        catalog.write_bytes(b"generated catalog")
        result = self.run_hook("post_remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(catalog.exists())
        self.assertFalse(state.exists())
        self.assertEqual(self.config.read_text(), "Touch sensor\n")
        self.assertFalse(self.calls.exists())

    def test_install_migrates_legacy_configuration_and_removes_old_catalog(self):
        self.config.unlink()
        legacy_config = self.config.with_name("fprintd-custom-prompt.conf")
        legacy_config.write_text("  Legacy prompt 🔐  \n", encoding="utf-8")
        legacy_state = self.root / "var" / "lib" / "fprintd-custom-prompt"
        legacy_state.mkdir(parents=True)
        (legacy_state / "fprintd.mo").write_bytes(b"old catalog")
        result = self.run_hook("post_install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(encoding="utf-8"), "  Legacy prompt 🔐  \n")
        self.assertFalse(legacy_config.exists())
        self.assertFalse(legacy_state.exists())
        self.assertEqual(self.calls.read_text(), "apply\n")

    def test_install_preserves_current_configuration_when_legacy_exists(self):
        legacy_config = self.config.with_name("fprintd-custom-prompt.conf")
        legacy_config.write_text("Legacy prompt\n", encoding="utf-8")
        result = self.run_hook("post_install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), "Touch sensor\n")
        self.assertEqual(legacy_config.read_text(), "Legacy prompt\n")
