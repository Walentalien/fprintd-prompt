#!/usr/bin/env python3
"""Comprehensive tests for fprintd_prompt.

All tests use temporary directories and never touch real system paths.
"""

import gettext
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure the module under test is importable from the repo root.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fprintd_prompt as fp


def _have_msgfmt() -> bool:
    return shutil.which("msgfmt") is not None


def _get_msgstr_from_po(po_text: str, msgid: str) -> str | None:
    """Extract the msgstr for a given msgid from a PO string."""
    lines = po_text.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].startswith('msgid "') and msgid in lines[i]:
            # Found the msgid line; next non-empty, non-comment line is msgstr
            j = i + 1
            while j < len(lines):
                line = lines[j].strip()
                if line.startswith("#") or line == "":
                    j += 1
                    continue
                if line.startswith('msgstr "'):
                    # Extract content between quotes
                    content = line[len('msgstr "'):]
                    if content.endswith('"'):
                        content = content[:-1]
                    # Handle escaped sequences
                    content = content.replace('\\"', '"').replace("\\\\", "\\")
                    return content
                break
        i += 1
    return None


class TestBuildInitialMsgids(unittest.TestCase):
    """Verify the 44 upstream initial-prompt msgids are generated."""

    def test_count(self):
        self.assertEqual(len(fp.INITIAL_MSGIDS), 44)

    def test_unique(self):
        self.assertEqual(len(set(fp.INITIAL_MSGIDS)), 44)

    def test_finger_generic(self):
        self.assertIn("Place your finger on the fingerprint reader",
                      fp.INITIAL_MSGIDS)

    def test_right_index_place_generic(self):
        self.assertIn(
            "Place your right index finger on the fingerprint reader",
            fp.INITIAL_MSGIDS,
        )

    def test_left_thumb_place_specific(self):
        self.assertIn("Place your left thumb on %s", fp.INITIAL_MSGIDS)

    def test_right_little_swipe_specific(self):
        self.assertIn("Swipe your right little finger across %s",
                      fp.INITIAL_MSGIDS)

    def test_place_and_swipe_balanced(self):
        places = [m for m in fp.INITIAL_MSGIDS if m.startswith("Place")]
        swipes = [m for m in fp.INITIAL_MSGIDS if m.startswith("Swipe")]
        self.assertEqual(len(places), 22)
        self.assertEqual(len(swipes), 22)

    def test_generic_and_specific_balanced(self):
        generics = [m for m in fp.INITIAL_MSGIDS if "%s" not in m]
        specifics = [m for m in fp.INITIAL_MSGIDS if "%s" in m]
        self.assertEqual(len(generics), 22)
        self.assertEqual(len(specifics), 22)

    def test_all_start_with_place_or_swipe(self):
        for mid in fp.INITIAL_MSGIDS:
            self.assertTrue(
                mid.startswith("Place") or mid.startswith("Swipe"),
                f"Unexpected msgid: {mid}",
            )

    def test_exact_right_index_on_reader(self):
        self.assertIn(
            "Place your right index finger on the fingerprint reader",
            fp.INITIAL_MSGIDS,
        )


class TestValidatePrompt(unittest.TestCase):
    """Test prompt validation."""

    def test_valid_basic(self):
        fp.validate_prompt("Touch the sensor")

    def test_valid_unicode(self):
        fp.validate_prompt("Zażółć gęślą jaźń")

    def test_valid_emoji(self):
        fp.validate_prompt("Authenticate 🔐")

    def test_valid_percent(self):
        fp.validate_prompt("100% ready")

    def test_valid_quotes(self):
        fp.validate_prompt('He said "hello"')

    def test_valid_backslash(self):
        fp.validate_prompt("path\\to\\file")

    def test_valid_apostrophe(self):
        fp.validate_prompt("It's me")

    def test_valid_max_bytes(self):
        fp.validate_prompt("A" * 4096)

    def test_reject_empty(self):
        with self.assertRaises(ValueError):
            fp.validate_prompt("")

    def test_reject_nul(self):
        with self.assertRaises(ValueError):
            fp.validate_prompt("hello\x00world")

    def test_reject_newline(self):
        with self.assertRaises(ValueError):
            fp.validate_prompt("hello\nworld")

    def test_reject_carriage_return(self):
        with self.assertRaises(ValueError):
            fp.validate_prompt("hello\rworld")

    def test_reject_tab_allowed(self):
        # Tab (0x09) is allowed since terminals use it
        fp.validate_prompt("hello\tworld")

    def test_reject_other_control(self):
        with self.assertRaises(ValueError):
            fp.validate_prompt("hello\x01world")

    def test_reject_over_size(self):
        with self.assertRaises(ValueError):
            fp.validate_prompt("A" * 4097)


class TestPoQuote(unittest.TestCase):
    """Test PO string escaping."""

    def test_simple(self):
        self.assertEqual(fp.po_quote("Hello"), "Hello")

    def test_backslash(self):
        self.assertEqual(fp.po_quote("back\\slash"), "back\\\\slash")

    def test_double_quote(self):
        self.assertEqual(fp.po_quote('"fingerprint"'), '\\"fingerprint\\"')

    def test_backslash_and_quote(self):
        self.assertEqual(fp.po_quote('a\\"b'), 'a\\\\\\"b')

    def test_unicode(self):
        self.assertEqual(fp.po_quote("Zażółć gęślą jaźń"),
                         "Zażółć gęślą jaźń")

    def test_cyrillic(self):
        self.assertEqual(fp.po_quote("Приклади палець"),
                         "Приклади палець")

    def test_emoji(self):
        self.assertEqual(fp.po_quote("🔐👆"), "🔐👆")

    def test_apostrophe(self):
        self.assertEqual(fp.po_quote("It's me"), "It's me")

    def test_percent(self):
        self.assertEqual(fp.po_quote("100%"), "100%")


class TestPrintfSafeTranslation(unittest.TestCase):
    """Test printf-safe translation generation."""

    def test_generic_no_escaping(self):
        result = fp.printf_safe_translation("Touch sensor",
                                            is_device_specific=False)
        self.assertEqual(result, "Touch sensor")

    def test_generic_with_percent(self):
        result = fp.printf_safe_translation("100% ready",
                                            is_device_specific=False)
        self.assertEqual(result, "100% ready")

    def test_device_specific_no_percent(self):
        result = fp.printf_safe_translation("Touch sensor",
                                            is_device_specific=True)
        self.assertEqual(result, "Touch sensor%.0s")

    def test_device_specific_with_percent(self):
        result = fp.printf_safe_translation("100% ready",
                                            is_device_specific=True)
        self.assertEqual(result, "100%% ready%.0s")

    def test_device_specific_multiple_percent(self):
        result = fp.printf_safe_translation("100% done %s test",
                                            is_device_specific=True)
        self.assertEqual(result, "100%% done %%s test%.0s")

    def test_device_specific_percent_percent(self):
        result = fp.printf_safe_translation("hello %% world",
                                            is_device_specific=True)
        self.assertEqual(result, "hello %%%% world%.0s")

    def test_device_specific_d_percent(self):
        result = fp.printf_safe_translation("%d items",
                                            is_device_specific=True)
        self.assertEqual(result, "%%d items%.0s")

    def test_device_specific_p_percent(self):
        result = fp.printf_safe_translation("%p ptr",
                                            is_device_specific=True)
        self.assertEqual(result, "%%p ptr%.0s")


class TestRenderPo(unittest.TestCase):
    """Test PO file rendering."""

    def test_has_header(self):
        po = fp.render_po("test")
        self.assertIn('Project-Id-Version: fprintd-prompt', po)
        self.assertIn('Language: en_US', po)
        self.assertIn('charset=UTF-8', po)

    def test_count_msgid_entries(self):
        po = fp.render_po("test")
        # Count all msgid lines (including header)
        msgid_count = sum(1 for line in po.split("\n")
                          if line.startswith('msgid '))
        # Header (1) + 44 entries = 45
        self.assertEqual(msgid_count, 45)

    def test_count_translation_entries(self):
        po = fp.render_po("test")
        msgstr_count = sum(1 for line in po.split("\n")
                           if line.startswith('msgstr '))
        self.assertEqual(msgstr_count, 45)

    def test_all_msgids_present(self):
        po = fp.render_po("test")
        for mid in fp.INITIAL_MSGIDS:
            self.assertIn(f'msgid "{fp.po_quote(mid)}"', po)

    def test_device_specific_has_c_format(self):
        po = fp.render_po("test")
        lines = po.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("msgid ") and "%s" in line:
                preceding = "\n".join(lines[max(0, i - 2):i])
                self.assertIn("#, c-format", preceding,
                              f"Missing c-format for {line}")

    def test_generic_no_c_format(self):
        po = fp.render_po("test")
        lines = po.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("msgid ") and "%s" not in line:
                if i >= 2:
                    self.assertNotIn("#, c-format", lines[i - 1])


class TestAtomicWrite(unittest.TestCase):
    """Test atomic file writing."""

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sub" / "test.txt"
            fp._atomic_write(path, b"hello\n")
            self.assertEqual(path.read_bytes(), b"hello\n")

    def test_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            fp._atomic_write(path, b"data", mode=0o644)
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o644)

    def test_no_temp_files_left(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            fp._atomic_write(path, b"data")
            files = list(Path(td).iterdir())
            self.assertEqual(len(files), 1)

    def test_replaces_existing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            fp._atomic_write(path, b"old")
            fp._atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")


class TestCatalogCompilation(unittest.TestCase):
    """Test .mo catalog generation (requires msgfmt)."""

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_compile_basic(self):
        with tempfile.TemporaryDirectory() as td:
            mo_path = Path(td) / "test.mo"
            po_text = fp.render_po("Touch sensor")
            fp.compile_catalog(po_text, mo_path)
            self.assertTrue(mo_path.exists())
            self.assertGreater(mo_path.stat().st_size, 0)

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_compile_and_verify_translation(self):
        with tempfile.TemporaryDirectory() as td:
            mo_path = Path(td) / "test.mo"
            prompt = "Touch sensor 🔐"
            po_text = fp.render_po(prompt)
            fp.compile_catalog(po_text, mo_path)
            with open(mo_path, "rb") as fh:
                t = gettext.GNUTranslations(fh)
            result = t.gettext(
                "Place your right index finger on the fingerprint reader"
            )
            self.assertEqual(result, prompt)

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_compile_device_specific_returns_raw_msgstr(self):
        """gettext returns raw msgstr; C printf processes it."""
        with tempfile.TemporaryDirectory() as td:
            mo_path = Path(td) / "test.mo"
            prompt = "Touch sensor"
            po_text = fp.render_po(prompt)
            fp.compile_catalog(po_text, mo_path)
            with open(mo_path, "rb") as fh:
                t = gettext.GNUTranslations(fh)
            # Device-specific msgid contains %s
            raw = t.gettext("Place your left thumb on %s")
            # Raw msgstr includes %.0s — this is expected at Python level
            self.assertIn("%.0s", raw)
            self.assertIn(prompt, raw)

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_compile_rejects_malformed(self):
        with tempfile.TemporaryDirectory() as td:
            mo_path = Path(td) / "test.mo"
            bad_po = 'msgid "unclosed\nmsgstr "test"\n'
            with self.assertRaises(subprocess.CalledProcessError):
                fp.compile_catalog(bad_po, mo_path)

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_compile_no_temp_files_left(self):
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "catalog_dir"
            mo_path = out_dir / "test.mo"
            po_text = fp.render_po("Touch sensor")
            fp.compile_catalog(po_text, mo_path)
            files = list(out_dir.iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "test.mo")


class TestPercentSafety(unittest.TestCase):
    """Preserve literal generic prompts and safe device-specific formats.

    For device-specific messages the upstream does:
        asprintf(&s, translated_message, driver_name);

    Generic messages are copied directly after gettext lookup, so their
    translations must already contain the user's intended text.
    """

    PROMPTS = [
        "100%",
        "%s",
        "%d",
        "%p",
        "%%",
        "hello %s world",
        "Authenticate 🔐 — 100% Linux",
        "literal %.0s",
    ]

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_device_specific_msgstr_escaped(self):
        """Device-specific msgstr must escape % and add %.0s."""
        for prompt in self.PROMPTS:
            with self.subTest(prompt=prompt):
                po_text = fp.render_po(prompt)
                specific_msgids = [m for m in fp.INITIAL_MSGIDS if "%s" in m]
                for msgid in specific_msgids[:1]:
                    msgstr = _get_msgstr_from_po(po_text, msgid)
                    self.assertIsNotNone(msgstr)
                    self.assertTrue(
                        msgstr.endswith("%.0s"),
                        f"Expected %.0s suffix in {msgstr!r} for {prompt!r}",
                    )
                    # The entire msgstr, excluding the %.0s suffix, must
                    # contain only doubled %% for percent chars.
                    body = msgstr[:-4]  # strip %.0s (4 chars)
                    # Count unescaped %: any % not preceded by %
                    bare_pct = re.findall(r'(?<!%)%(?!%)', body)
                    self.assertEqual(
                        len(bare_pct), 0,
                        f"Bare % found in body {body!r} for prompt {prompt!r}",
                    )

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_generic_catalog_preserves_literal_percent(self):
        """Compiled generic translations must equal the literal prompt."""
        generic_msgids = [m for m in fp.INITIAL_MSGIDS if "%s" not in m]
        for prompt in self.PROMPTS:
            with tempfile.TemporaryDirectory() as td:
                mo = Path(td) / "test.mo"
                fp.compile_catalog(fp.render_po(prompt), mo)
                with mo.open("rb") as fh:
                    translations = gettext.GNUTranslations(fh)
                for msgid in generic_msgids:
                    with self.subTest(prompt=prompt, msgid=msgid):
                        self.assertEqual(translations.gettext(msgid), prompt)

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_msgfmt_accepts_all_percent_prompts(self):
        """msgfmt --check --check-format must succeed for all prompts."""
        for prompt in self.PROMPTS:
            with self.subTest(prompt=prompt):
                po_text = fp.render_po(prompt)
                with tempfile.TemporaryDirectory() as td:
                    mo = Path(td) / "test.mo"
                    fp.compile_catalog(po_text, mo)
                    self.assertTrue(mo.exists())

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_asprintf_simulation(self):
        """Simulate what C asprintf would produce after processing."""
        for prompt in self.PROMPTS:
            with self.subTest(prompt=prompt):
                po_text = fp.render_po(prompt)
                # For a device-specific entry:
                specific_msgids = [m for m in fp.INITIAL_MSGIDS if "%s" in m]
                msgstr = _get_msgstr_from_po(po_text, specific_msgids[0])
                # Simulate C printf: %% → %, %.0s → "" (consumes driver_name)
                simulated = msgstr.replace("%%", "\x00PERCENT\x00")
                simulated = simulated.replace("%.0s", "")
                simulated = simulated.replace("\x00PERCENT\x00", "%")
                self.assertEqual(
                    simulated, prompt,
                    f"asprintf simulation failed for {prompt!r}: got {simulated!r}",
                )


class TestConfiguration(unittest.TestCase):
    """Test config read/write with temporary paths."""

    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            fp.write_config("Touch sensor", config_path=cfg)
            result = fp.read_config(config_path=cfg)
            self.assertEqual(result, "Touch sensor")

    def test_read_missing(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "nonexistent.conf"
            result = fp.read_config(config_path=cfg)
            self.assertIsNone(result)

    def test_read_empty(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "empty.conf"
            cfg.write_text("")
            result = fp.read_config(config_path=cfg)
            self.assertIsNone(result)

    def test_unicode_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            prompt = "Zażółć gęślą jaźń 🔐"
            fp.write_config(prompt, config_path=cfg)
            result = fp.read_config(config_path=cfg)
            self.assertEqual(result, prompt)

    def test_leading_trailing_spaces_stripped_on_read(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            fp.write_config("  hello  ", config_path=cfg)
            result = fp.read_config(config_path=cfg)
            self.assertEqual(result, "hello")

    def test_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            fp.write_config("old", config_path=cfg)
            fp.write_config("new", config_path=cfg)
            result = fp.read_config(config_path=cfg)
            self.assertEqual(result, "new")


class TestApplyPrompt(unittest.TestCase):
    """Test apply_prompt with temporary paths."""

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_apply_with_explicit_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            result = fp.apply_prompt("Touch", config_path=cfg, catalog_path=mo)
            self.assertIn("applied", result)
            self.assertTrue(mo.exists())

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_apply_from_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            fp.write_config("From config", config_path=cfg)
            result = fp.apply_prompt(config_path=cfg, catalog_path=mo)
            self.assertIn("applied", result)
            self.assertTrue(mo.exists())

    def test_apply_no_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            result = fp.apply_prompt(config_path=cfg, catalog_path=mo)
            self.assertIn("Nothing to apply", result)


class TestResetPrompt(unittest.TestCase):
    """Test reset_prompt with temporary paths."""

    def test_reset_removes_files(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            state = Path(td) / "state"
            mo = state / "fprintd.mo"
            state.mkdir()
            cfg.write_text("test\n")
            mo.write_bytes(b"fake")
            result = fp.reset_prompt(
                config_path=cfg, catalog_path=mo, state_dir=state
            )
            self.assertIn("Removed", result)
            self.assertFalse(cfg.exists())
            self.assertFalse(mo.exists())

    def test_reset_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            state = Path(td) / "state"
            state.mkdir()
            mo = state / "fprintd.mo"
            # Create state dir but keep it non-empty so it survives reset
            (state / "placeholder").write_text("x")
            result1 = fp.reset_prompt(
                config_path=cfg, catalog_path=mo, state_dir=state
            )
            result2 = fp.reset_prompt(
                config_path=cfg, catalog_path=mo, state_dir=state
            )
            self.assertIn("Nothing to remove", result1)
            self.assertIn("Nothing to remove", result2)

    def test_reset_removes_empty_state_dir(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            state = Path(td) / "state"
            state.mkdir()
            mo = state / "test.mo"
            cfg.write_text("test\n")
            result = fp.reset_prompt(
                config_path=cfg, catalog_path=mo, state_dir=state
            )
            self.assertFalse(state.exists())

    def test_reset_preserves_nonempty_state_dir(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            state = Path(td) / "state"
            state.mkdir()
            (state / "other.txt").write_text("keep")
            mo = state / "test.mo"
            cfg.write_text("test\n")
            result = fp.reset_prompt(
                config_path=cfg, catalog_path=mo, state_dir=state
            )
            self.assertTrue(state.exists())
            self.assertTrue((state / "other.txt").exists())


class TestInspectStatus(unittest.TestCase):
    """Test status inspection with temporary paths."""

    def test_nothing_configured(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertEqual(info["Custom prompt"], "disabled")
            self.assertEqual(info["Config"], "missing")
            self.assertEqual(info["Catalog"], "missing")

    def test_config_only(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            fp.write_config("Touch", config_path=cfg)
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertEqual(info["Custom prompt"], "Touch")
            self.assertEqual(info["Config"], "present")
            self.assertEqual(info["Catalog"], "missing")

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_config_and_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            fp.write_config("Touch", config_path=cfg)
            fp.compile_catalog(fp.render_po("Touch"), mo)
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertEqual(info["Custom prompt"], "Touch")
            self.assertEqual(info["Config"], "present")
            self.assertEqual(info["Catalog"], "present")

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_catalog_verification_with_literal_percent(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            prompt = "Authenticate 🔐 — 100% Linux"
            fp.write_config(prompt, config_path=cfg)
            fp.compile_catalog(fp.render_po(prompt), mo)
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertEqual(info["Catalog verification"],
                             "OK — translates correctly")

    def test_wrong_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            sys_cat.symlink_to("/nonexistent/path")
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertIn("wrong target", info["Gettext link"])

    def test_correct_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            state = Path(td) / "state"
            state.mkdir()
            mo = state / "test.mo"
            sys_cat = Path(td) / "system.mo"
            sys_cat.symlink_to(str(mo))
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertEqual(info["Gettext link"], "OK")

    def test_system_catalog_not_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            sys_cat.write_bytes(b"fake")
            info = fp.inspect_status(
                config_path=cfg,
                catalog_path=mo,
                system_catalog_path=sys_cat,
            )
            self.assertIn("not a symlink", info["Gettext link"])

    def test_locale_hierarchy_lc_messages(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            old_env = os.environ.copy()
            try:
                os.environ["LANG"] = "C"
                os.environ["LC_MESSAGES"] = "en_US.UTF-8"
                os.environ.pop("LC_ALL", None)
                info = fp.inspect_status(
                    config_path=cfg,
                    catalog_path=mo,
                    system_catalog_path=sys_cat,
                )
                self.assertEqual(info["Current shell locale"], "en_US.UTF-8")
                self.assertNotIn("Locale warning", info)
            finally:
                os.environ.clear()
                os.environ.update(old_env)

    def test_locale_hierarchy_lc_all_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            sys_cat = Path(td) / "system.mo"
            old_env = os.environ.copy()
            try:
                os.environ["LANG"] = "en_US.UTF-8"
                os.environ["LC_MESSAGES"] = "en_US.UTF-8"
                os.environ["LC_ALL"] = "C"
                info = fp.inspect_status(
                    config_path=cfg,
                    catalog_path=mo,
                    system_catalog_path=sys_cat,
                )
                self.assertEqual(info["Current shell locale"], "C")
                self.assertIn("Locale warning", info)
            finally:
                os.environ.clear()
                os.environ.update(old_env)


class TestParser(unittest.TestCase):
    """Test CLI argument parsing."""

    def test_no_args(self):
        parser = fp.build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)

    def test_set(self):
        parser = fp.build_parser()
        args = parser.parse_args(["set", "hello"])
        self.assertEqual(args.command, "set")
        self.assertEqual(args.prompt, "hello")

    def test_get(self):
        parser = fp.build_parser()
        args = parser.parse_args(["get"])
        self.assertEqual(args.command, "get")

    def test_status(self):
        parser = fp.build_parser()
        args = parser.parse_args(["status"])
        self.assertEqual(args.command, "status")

    def test_apply(self):
        parser = fp.build_parser()
        args = parser.parse_args(["apply"])
        self.assertEqual(args.command, "apply")

    def test_reset(self):
        parser = fp.build_parser()
        args = parser.parse_args(["reset"])
        self.assertEqual(args.command, "reset")

    def test_version(self):
        parser = fp.build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)


@unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
class TestSetPrompt(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.config = self.root / "etc" / "prompt.conf"
        self.catalog = self.root / "state" / "fprintd.mo"
        fp.write_config("Old prompt", config_path=self.config)
        self.config.chmod(0o640)
        fp.compile_catalog(fp.render_po("Old prompt"), self.catalog)
        self.old_config = self.config.read_bytes()
        self.old_catalog = self.catalog.read_bytes()
        self.prompt = "New prompt 🔐 100%"
        self.real_replace = os.replace

    def run_set(self):
        fp.set_prompt(self.prompt, config_path=self.config,
                      catalog_path=self.catalog)

    def assert_no_staging_files(self):
        self.assertEqual(list(self.root.glob("*/.fprintd-prompt-*")), [])

    def assert_original_files(self):
        self.assertEqual(self.config.read_bytes(), self.old_config)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.catalog.read_bytes(), self.old_catalog)
        self.assert_no_staging_files()

    def fail_catalog_replace(self, src, dst):
        if Path(dst) == self.catalog:
            raise OSError("injected catalog replacement failure")
        return self.real_replace(src, dst)

    def test_set_updates_both_files(self):
        self.run_set()
        self.assertEqual(fp.read_config(self.config), self.prompt)
        with self.catalog.open("rb") as fh:
            translations = gettext.GNUTranslations(fh)
        self.assertEqual(translations.gettext(
            "Place your finger on the fingerprint reader"), self.prompt)
        self.assert_no_staging_files()

    def test_first_set_creates_both_files(self):
        self.config.unlink()
        self.catalog.unlink()
        self.run_set()
        self.assertEqual(fp.read_config(self.config), self.prompt)
        with self.catalog.open("rb") as fh:
            translations = gettext.GNUTranslations(fh)
        self.assertEqual(translations.gettext(
            "Swipe your finger across the fingerprint reader"), self.prompt)
        self.assert_no_staging_files()

    def test_failed_po_write_preserves_both_files(self):
        with patch.object(fp.os, "write", side_effect=OSError("PO write failed")):
            with self.assertRaisesRegex(OSError, "PO write failed"):
                self.run_set()
        self.assert_original_files()

    def test_failed_compilation_preserves_both_files(self):
        with patch.object(fp, "render_po", return_value='msgid "unclosed\n'):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_set()
        self.assert_original_files()

    def test_failed_config_backup_preserves_both_files(self):
        with patch.object(fp.shutil, "copy2",
                          side_effect=OSError("backup write failed")):
            with self.assertRaisesRegex(OSError, "backup write failed"):
                self.run_set()
        self.assert_original_files()

    def test_failed_config_write_preserves_both_files(self):
        real_write_config = fp.write_config

        def fail_write(prompt, config_path):
            with patch.object(fp.os, "write",
                              side_effect=OSError("config write failed")):
                real_write_config(prompt, config_path=config_path)

        with patch.object(fp, "write_config", side_effect=fail_write):
            with self.assertRaisesRegex(OSError, "config write failed"):
                self.run_set()
        self.assert_original_files()

    def test_failed_staged_catalog_replace_preserves_both_files(self):
        def fail_replace(src, dst):
            if Path(dst).name == "fprintd.mo":
                raise OSError("staged catalog replacement failed")
            return self.real_replace(src, dst)

        with patch.object(fp.os, "replace", side_effect=fail_replace):
            with self.assertRaisesRegex(OSError, "staged catalog replacement"):
                self.run_set()
        self.assert_original_files()

    def test_failed_staged_config_replace_preserves_both_files(self):
        def fail_replace(src, dst):
            if Path(dst).name == "new.conf":
                raise OSError("staged config replacement failed")
            return self.real_replace(src, dst)

        with patch.object(fp.os, "replace", side_effect=fail_replace):
            with self.assertRaisesRegex(OSError, "staged config replacement"):
                self.run_set()
        self.assert_original_files()

    def test_failed_config_replace_preserves_both_files(self):
        def fail_replace(src, dst):
            if Path(dst) == self.config:
                raise OSError("config replacement failed")
            return self.real_replace(src, dst)

        with patch.object(fp.os, "replace", side_effect=fail_replace):
            with self.assertRaisesRegex(OSError, "config replacement failed"):
                self.run_set()
        self.assert_original_files()

    def test_failed_catalog_replace_restores_config(self):
        with patch.object(fp.os, "replace",
                          side_effect=self.fail_catalog_replace):
            with self.assertRaisesRegex(OSError, "catalog replacement failure"):
                self.run_set()
        self.assert_original_files()
        fp.apply_prompt(config_path=self.config, catalog_path=self.catalog)
        self.assertEqual(self.catalog.read_bytes(), self.old_catalog)

    def test_failed_first_catalog_replace_removes_new_config(self):
        self.config.unlink()
        self.catalog.unlink()
        with patch.object(fp.os, "replace",
                          side_effect=self.fail_catalog_replace):
            with self.assertRaises(OSError):
                self.run_set()
        self.assertFalse(self.config.exists())
        self.assertFalse(self.catalog.exists())
        self.assert_no_staging_files()

    def test_failed_rollback_keeps_recoverable_config(self):
        def fail_replace(src, dst):
            if Path(src).name == "previous.conf":
                raise OSError("injected rollback failure")
            return self.fail_catalog_replace(src, dst)

        with patch.object(fp.os, "replace", side_effect=fail_replace):
            with self.assertRaisesRegex(OSError, "rollback failed") as raised:
                self.run_set()
        backups = list(self.root.glob("etc/.fprintd-prompt-*/previous.conf"))
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        self.assertEqual(backup.read_bytes(), self.old_config)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o640)
        self.assertIn(str(backup), str(raised.exception))
        self.assertIn(str(self.config), str(raised.exception))
        self.assertIn("catalog replacement failure", str(raised.exception))
        self.assertIn("injected rollback failure", str(raised.exception))
        self.assertEqual(fp.read_config(self.config), self.prompt)
        self.assertEqual(self.catalog.read_bytes(), self.old_catalog)
        self.assertEqual(list(self.catalog.parent.iterdir()), [self.catalog])
        os.replace(backup, self.config)
        backup.parent.rmdir()
        self.assert_original_files()

    def test_failed_first_rollback_reports_config_to_remove(self):
        self.config.unlink()
        self.catalog.unlink()
        real_unlink = Path.unlink

        def fail_unlink(path, *args, **kwargs):
            if path == self.config:
                raise OSError("injected unlink failure")
            return real_unlink(path, *args, **kwargs)

        with patch.object(fp.os, "replace",
                          side_effect=self.fail_catalog_replace), \
             patch.object(Path, "unlink", fail_unlink):
            with self.assertRaisesRegex(OSError, "rollback failed") as raised:
                self.run_set()
        self.assertIn(f"Remove {self.config}", str(raised.exception))
        self.assertEqual(fp.read_config(self.config), self.prompt)
        self.assertFalse(self.catalog.exists())
        self.assert_no_staging_files()

    @unittest.skipIf(os.geteuid() == 0, "root bypasses directory permissions")
    def test_cleanup_failure_does_not_hide_recovery_instructions(self):
        def fail_replace(src, dst):
            if Path(dst) == self.catalog:
                self.config.parent.chmod(0o555)
                self.catalog.parent.chmod(0o555)
                raise OSError("injected catalog replacement failure")
            return self.real_replace(src, dst)

        try:
            with patch.object(fp.os, "replace", side_effect=fail_replace):
                with self.assertRaisesRegex(OSError, "rollback failed") as raised:
                    self.run_set()
        finally:
            self.config.parent.chmod(0o755)
            self.catalog.parent.chmod(0o755)
        backups = list(self.root.glob("etc/.fprintd-prompt-*/previous.conf"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old_config)
        self.assertIn(f"Restore {backups[0]} to {self.config}",
                      str(raised.exception))
        self.assertEqual(self.catalog.read_bytes(), self.old_catalog)

    @unittest.skipIf(os.geteuid() == 0, "root bypasses directory permissions")
    def test_first_set_cleanup_failure_does_not_hide_recovery_instructions(self):
        self.config.unlink()
        self.catalog.unlink()

        def fail_replace(src, dst):
            if Path(dst) == self.catalog:
                self.config.parent.chmod(0o555)
                self.catalog.parent.chmod(0o555)
                raise OSError("injected catalog replacement failure")
            return self.real_replace(src, dst)

        try:
            with patch.object(fp.os, "replace", side_effect=fail_replace):
                with self.assertRaisesRegex(OSError, "rollback failed") as raised:
                    self.run_set()
        finally:
            self.config.parent.chmod(0o755)
            self.catalog.parent.chmod(0o755)
        self.assertIn(f"Remove {self.config}", str(raised.exception))
        self.assertEqual(fp.read_config(self.config), self.prompt)
        self.assertFalse(self.catalog.exists())

    def test_cli_reports_config_write_failure_without_changing_catalog(self):
        with patch.object(fp, "CONFIG_PATH", self.config), \
             patch.object(fp, "CATALOG_PATH", self.catalog), \
             patch.object(fp, "_require_root"), \
             patch.object(fp, "write_config",
                          side_effect=PermissionError("config write failed")), \
             patch("sys.stderr", new_callable=io.StringIO) as stderr, \
             patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaises(SystemExit) as raised:
                fp.main(["set", self.prompt])
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Error: config write failed", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assert_original_files()


class TestSetAndResetIntegration(unittest.TestCase):
    """Integration test: set then reset with temp paths."""

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_set_then_reset(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "prompt.conf"
            state = Path(td) / "state"
            mo = state / "fprintd.mo"
            prompt = "Touch 🔐 100%"
            fp.set_prompt(prompt, config_path=cfg, catalog_path=mo)
            self.assertTrue(mo.exists())
            self.assertEqual(fp.read_config(cfg), prompt)
            # Simulate reset
            fp.reset_prompt(config_path=cfg, catalog_path=mo, state_dir=state)
            self.assertFalse(cfg.exists())
            self.assertFalse(mo.exists())

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_apply_after_set(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "prompt.conf"
            mo = Path(td) / "test.mo"
            prompt = "Sensor please"
            fp.write_config(prompt, config_path=cfg)
            result = fp.apply_prompt(config_path=cfg, catalog_path=mo)
            self.assertIn("applied", result)
            with open(mo, "rb") as fh:
                t = gettext.GNUTranslations(fh)
            actual = t.gettext(
                "Place your right index finger on the fingerprint reader"
            )
            self.assertEqual(actual, prompt)

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_apply_device_specific_verification(self):
        """Verify device-specific translations via asprintf simulation."""
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "prompt.conf"
            mo = Path(td) / "test.mo"
            prompt = "Sensor 🔐 — 100%"
            fp.write_config(prompt, config_path=cfg)
            fp.compile_catalog(fp.render_po(prompt), mo)
            with open(mo, "rb") as fh:
                t = gettext.GNUTranslations(fh)
            raw = t.gettext("Place your left index finger on %s")
            # Simulate C asprintf: raw % driver_name
            driver = "goodix"
            try:
                result = raw % (driver,)
            except TypeError:
                self.fail(f"msgstr is not printf-safe: {raw!r}")
            self.assertEqual(result, prompt)


if __name__ == "__main__":
    unittest.main()
