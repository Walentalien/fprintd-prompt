#!/usr/bin/env python3
"""Comprehensive tests for fprintd_prompt.

All tests use temporary directories and never touch real system paths.
"""

import gettext
import io
import json
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


_NATIVE_ASPRINTF_SCRIPT = """
import ctypes
import gettext
import json
import resource
import sys

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
libc = ctypes.CDLL(None, use_errno=True)
libc.asprintf.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p]
libc.asprintf.restype = ctypes.c_int
libc.free.argtypes = [ctypes.c_void_p]
libc.free.restype = None
with open(sys.argv[1], "rb") as fh:
    translations = gettext.GNUTranslations(fh)
driver = ctypes.c_char_p(sys.argv[2].encode("utf-8"))
outputs = {}
for msgid in json.load(sys.stdin):
    fmt = translations.gettext(msgid).encode("utf-8")
    buffer = ctypes.c_void_p()
    length = libc.asprintf(ctypes.byref(buffer), fmt, driver)
    if length < 0:
        raise OSError(ctypes.get_errno(), "asprintf failed")
    try:
        outputs[msgid] = ctypes.string_at(buffer, length).decode("utf-8")
    finally:
        libc.free(buffer)
json.dump(outputs, sys.stdout)
"""


def _native_asprintf(catalog: Path, msgids: list[str], driver: str) -> dict[str, str]:
    """Format compiled translations in an isolated native process."""
    result = subprocess.run(
        [sys.executable, "-c", _NATIVE_ASPRINTF_SCRIPT, str(catalog), driver],
        input=json.dumps(msgids), capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Native asprintf process exited with {result.returncode}: {result.stderr}"
        )
    return json.loads(result.stdout)


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

    def test_short_writes_preserve_complete_utf8_data(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.conf"
            path.write_bytes(b"previous config")
            data = "Touch sensor 🔐 — 100%\n".encode("utf-8")
            real_write = os.write
            with patch.object(fp.os, "write", side_effect=lambda fd, chunk:
                              real_write(fd, chunk[:3])):
                fp._atomic_write(path, data, mode=0o640)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(td).iterdir()), [path])

    def test_failure_after_short_write_preserves_existing_file(self):
        for failure in ("storage failure", "no progress"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "config.conf"
                path.write_bytes(b"previous config")
                real_write = os.write
                calls = 0

                def fail_after_prefix(fd, chunk):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return real_write(fd, chunk[:3])
                    if calls == 2:
                        if failure == "no progress":
                            return 0
                        raise OSError("storage failure")
                    raise AssertionError("retried after zero progress")

                with patch.object(fp.os, "write", side_effect=fail_after_prefix):
                    with self.assertRaisesRegex(OSError, failure):
                        fp._atomic_write(path, b"new config\n")
                self.assertEqual(path.read_bytes(), b"previous config")
                self.assertEqual(list(Path(td).iterdir()), [path])

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
    def test_short_po_writes_preserve_all_generic_translations(self):
        with tempfile.TemporaryDirectory() as td:
            mo = Path(td) / "fprintd.mo"
            prompt = "Touch sensor 🔐 — 100%"
            po = fp.render_po(prompt)
            # A header-only PO is valid input to msgfmt but loses translations.
            header_size = po.encode("utf-8").index(b"\n\n") + 2
            real_write = os.write
            with patch.object(fp.tempfile, "tempdir", td), \
                 patch.object(fp.os, "write", side_effect=lambda fd, chunk:
                              real_write(fd, chunk[:header_size])):
                fp.compile_catalog(po, mo)
            with mo.open("rb") as fh:
                translations = gettext.GNUTranslations(fh)
            for msgid in fp.INITIAL_MSGIDS:
                if "%s" not in msgid:
                    with self.subTest(msgid=msgid):
                        self.assertEqual(translations.gettext(msgid), prompt)
            self.assertEqual(mo.stat().st_mode & 0o777, 0o644)
            self.assertEqual(list(Path(td).iterdir()), [mo])

    def test_failure_after_short_po_write_preserves_existing_catalog(self):
        for failure in ("storage failure", "no progress"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                mo = Path(td) / "fprintd.mo"
                mo.write_bytes(b"previous catalog")
                real_write = os.write
                calls = 0

                def fail_after_prefix(fd, chunk):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return real_write(fd, chunk[:3])
                    if calls == 2:
                        if failure == "no progress":
                            return 0
                        raise OSError("storage failure")
                    raise AssertionError("retried after zero progress")

                with patch.object(fp.tempfile, "tempdir", td), \
                     patch.object(fp.os, "write", side_effect=fail_after_prefix), \
                     patch.object(fp.subprocess, "run") as compiler:
                    with self.assertRaisesRegex(OSError, failure):
                        fp.compile_catalog(fp.render_po("Touch sensor"), mo)
                    compiler.assert_not_called()
                self.assertEqual(mo.read_bytes(), b"previous catalog")
                self.assertEqual(list(Path(td).iterdir()), [mo])

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
        "Touch sensor",
        "100%",
        "%s",
        "%d",
        "%p",
        "%n",
        "%%",
        "hello %s world",
        "Authenticate 🔐 — 100% Linux",
        "literal %.0s",
        r'He said "touch \\ sensor" — 100%',
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
    def test_device_specific_catalog_matches_native_asprintf(self):
        """Use libc's formatter on all compiled device-specific translations."""
        msgids = [m for m in fp.INITIAL_MSGIDS if "%s" in m]
        self.assertEqual(len(msgids), 22)
        for prompt in self.PROMPTS:
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as td:
                mo = Path(td) / "fprintd.mo"
                fp.compile_catalog(fp.render_po(prompt), mo)
                for driver in ("Test Reader", "Reader %s 🔐"):
                    with self.subTest(driver=driver):
                        outputs = _native_asprintf(mo, msgids, driver)
                        self.assertEqual(set(outputs), set(msgids))
                        for msgid in msgids:
                            with self.subTest(msgid=msgid):
                                self.assertEqual(outputs[msgid], prompt)


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

    def test_whitespace_preserved_on_read(self):
        prompts = ["  hello  ", "\thello\t", " \t ",
                   "\u00a0hello\u2003", " \tAuthenticate 🔐 100%\t "]
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    fp.write_config(prompt, config_path=cfg)
                    self.assertEqual(fp.read_config(cfg), prompt)

    def test_read_removes_only_terminating_newline(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            cfg.write_text("  hello  \n\n", encoding="utf-8")
            self.assertEqual(fp.read_config(cfg), "  hello  \n")

    def test_read_without_terminating_newline(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            cfg.write_text("  hello\t", encoding="utf-8")
            self.assertEqual(fp.read_config(cfg), "  hello\t")

    def test_read_newline_only(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            cfg.write_text("\n", encoding="utf-8")
            self.assertIsNone(fp.read_config(cfg))

    def test_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            fp.write_config("old", config_path=cfg)
            fp.write_config("new", config_path=cfg)
            result = fp.read_config(config_path=cfg)
            self.assertEqual(result, "new")


class TestApplyPrompt(unittest.TestCase):
    """Test apply_prompt with temporary paths."""

    def test_rejects_invalid_explicit_prompts_before_compiling(self):
        prompts = ("", "line\nbreak", "nul\x00byte", "control\x1b",
                   "a" * 4097, "🔐" * 1025)
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            mo.write_bytes(b"existing catalog")
            for prompt in prompts:
                with self.subTest(prompt=repr(prompt[:30])), \
                     patch.object(fp, "compile_catalog") as compile_catalog:
                    with self.assertRaises(ValueError):
                        fp.apply_prompt(prompt, config_path=cfg, catalog_path=mo)
                    compile_catalog.assert_not_called()
                    self.assertEqual(mo.read_bytes(), b"existing catalog")

    def test_rejects_invalid_saved_prompts_before_compiling(self):
        prompts = ("line\nbreak", "nul\x00byte", "control\x1b",
                   "a" * 4097, "🔐" * 1025)
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.conf"
            mo = Path(td) / "test.mo"
            mo.write_bytes(b"existing catalog")
            for prompt in prompts:
                cfg.write_text(prompt + "\n", encoding="utf-8")
                with self.subTest(prompt=repr(prompt[:30])), \
                     patch.object(fp, "compile_catalog") as compile_catalog:
                    with self.assertRaises(ValueError):
                        fp.apply_prompt(config_path=cfg, catalog_path=mo)
                    compile_catalog.assert_not_called()
                    self.assertEqual(mo.read_bytes(), b"existing catalog")
                    self.assertEqual(cfg.read_text(encoding="utf-8"), prompt + "\n")

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


class TestConfigurationCli(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.config = self.root / "config.conf"
        self.catalog = self.root / "fprintd.mo"
        self.catalog.write_bytes(b"existing catalog")

    def run_cli(self, command):
        # Use the real CLI in a child process, with temporary system paths.
        script = (
            "import sys\n"
            "from pathlib import Path\n"
            "import fprintd_prompt as fp\n"
            "fp.CONFIG_PATH = Path(sys.argv[1])\n"
            "fp.CATALOG_PATH = Path(sys.argv[2])\n"
            "fp.SYSTEM_CATALOG_PATH = Path(sys.argv[3])\n"
            "fp._require_root = lambda: None\n"
            "fp.main(sys.argv[4:])\n"
        )
        return subprocess.run(
            [sys.executable, "-c", script, str(self.config), str(self.catalog),
             str(self.root / "system.mo"), command],
            cwd=Path(fp.__file__).resolve().parent,
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )

    def assert_read_failure(self, expected):
        for command in ("apply", "get", "status"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("Error:", result.stderr)
                self.assertIn(str(self.config), result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.catalog.read_bytes(), b"existing catalog")

    def test_malformed_utf8_is_reported_without_traceback(self):
        self.config.write_bytes(b"\xff\n")
        self.assert_read_failure("not valid UTF-8")

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_unreadable_config_is_reported_without_traceback(self):
        self.config.write_text("Touch sensor\n", encoding="utf-8")
        self.config.chmod(0o000)
        try:
            self.assert_read_failure("Permission denied")
        finally:
            self.config.chmod(0o600)

    def test_directory_config_is_reported_without_traceback(self):
        self.config.mkdir()
        self.assert_read_failure("Is a directory")

    def test_invalid_saved_prompt_is_reported_without_traceback(self):
        self.config.write_text("line\nbreak\n", encoding="utf-8")
        result = self.run_cli("apply")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("control characters", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.catalog.read_bytes(), b"existing catalog")

    def test_missing_config_remains_a_noop_for_apply(self):
        result = self.run_cli("apply")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Nothing to apply", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.catalog.read_bytes(), b"existing catalog")

    @unittest.skipUnless(_have_msgfmt(), "msgfmt not installed")
    def test_valid_saved_prompt_is_applied_through_cli(self):
        prompt = " \tTouch sensor 🔐 100%\t "
        fp.write_config(prompt, config_path=self.config)
        result = self.run_cli("apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"Custom prompt applied: {prompt}\n")
        with self.catalog.open("rb") as fh:
            translations = gettext.GNUTranslations(fh)
        self.assertEqual(translations.gettext(
            "Place your finger on the fingerprint reader"), prompt)


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
                os.environ.pop("LANGUAGE", None)
                info = fp.inspect_status(
                    config_path=cfg,
                    catalog_path=mo,
                    system_catalog_path=sys_cat,
                )
                self.assertEqual(info["Shell message locale"], "en_US.UTF-8")
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
                self.assertEqual(info["Shell message locale"], "C")
                self.assertIn("Locale warning", info)
            finally:
                os.environ.clear()
                os.environ.update(old_env)


class TestLocaleStatus(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        self.paths = dict(config_path=root / "config.conf",
                          catalog_path=root / "fprintd.mo",
                          system_catalog_path=root / "system.mo")

    def status(self, env, locales="C\nC.utf8\nen_US.utf8\n"):
        result = subprocess.CompletedProcess(["locale", "-a"], 0,
                                             stdout=locales)
        with patch.dict(os.environ, env, clear=True), \
             patch.object(fp.subprocess, "run", return_value=result):
            return fp.inspect_status(**self.paths)

    def test_installed_utf8_spelling_variants(self):
        for name in ("en_US.UTF-8", "en_US.utf8", "en_US.UTF8", "en_US.utf_8"):
            with self.subTest(name=name):
                info = self.status({"LANG": "en_US.UTF-8"}, locales=name + "\n")
                self.assertEqual(info["Installed en_US.UTF-8 locale"], "available")

    def test_other_locales_do_not_count_as_installed_en_us_utf8(self):
        for name in ("en_GB.utf8", "pl_PL.utf8", "C.utf8",
                     "en_US.iso88591", "en_US.utf8@custom"):
            with self.subTest(name=name):
                info = self.status({"LANG": "en_US.UTF-8"}, locales=name + "\n")
                self.assertEqual(info["Installed en_US.UTF-8 locale"],
                                 "not listed by locale -a")

    def test_installed_locale_does_not_suppress_polish_locale_warning(self):
        info = self.status({"LANG": "pl_PL.UTF-8"})
        self.assertEqual(info["Installed en_US.UTF-8 locale"], "available")
        self.assertEqual(info["Shell message locale"], "pl_PL.UTF-8")
        self.assertIn("en_US", info["Locale warning"])

    def test_shell_setting_does_not_imply_locale_is_installed(self):
        info = self.status({"LANG": "en_US.UTF-8"}, locales="C\n")
        self.assertEqual(info["Shell message locale"], "en_US.UTF-8")
        self.assertEqual(info["Installed en_US.UTF-8 locale"],
                         "not listed by locale -a")

    def test_en_us_message_locale_variants_do_not_warn(self):
        for name in ("en_US", "en_US.UTF-8", "en_US.utf8"):
            with self.subTest(name=name):
                info = self.status({"LANG": name})
                self.assertNotIn("Locale warning", info)

    def test_c_and_posix_locales_warn_even_with_language_override(self):
        for name in ("C", "POSIX", "C.UTF-8", "C.utf8"):
            with self.subTest(name=name):
                info = self.status({"LANG": name, "LANGUAGE": "en_US"})
                self.assertIn("disabled", info["Locale warning"])
                self.assertIn("LANGUAGE is ignored", info["Locale warning"])

    def test_unset_locale_warns(self):
        info = self.status({})
        self.assertEqual(info["Shell message locale"], "(unset; defaults to C)")
        self.assertIn("disabled", info["Locale warning"])

    def test_empty_locale_variables_follow_precedence(self):
        cases = [
            ({"LANG": "pl_PL.UTF-8", "LC_MESSAGES": "en_US.utf8", "LC_ALL": ""},
             "en_US.utf8"),
            ({"LANG": "en_US.UTF-8", "LC_MESSAGES": "", "LC_ALL": ""},
             "en_US.UTF-8"),
            ({"LANG": "en_US.UTF-8", "LC_MESSAGES": "pl_PL.UTF-8",
              "LC_ALL": "C.utf8"}, "C.utf8"),
        ]
        for env, expected in cases:
            with self.subTest(env=env):
                self.assertEqual(self.status(env)["Shell message locale"], expected)

    def test_language_override_is_reported_without_predicting_selection(self):
        for message_locale, languages in (("en_US.UTF-8", "pl_PL:en_US"),
                                          ("pl_PL.UTF-8", "en_US")):
            with self.subTest(message_locale=message_locale, languages=languages):
                info = self.status({"LANG": message_locale, "LANGUAGE": languages})
                self.assertEqual(info["Shell LANGUAGE"], languages)
                self.assertIn("LANGUAGE overrides", info["Locale warning"])
                self.assertIn("preference list", info["Locale warning"])

    def test_empty_language_is_ignored(self):
        info = self.status({"LANG": "en_US.UTF-8", "LANGUAGE": ""})
        self.assertEqual(info["Shell LANGUAGE"], "(unset)")
        self.assertNotIn("Locale warning", info)

    def test_pam_locale_is_unknown_regardless_of_shell_locale(self):
        for name in ("en_US.UTF-8", "pl_PL.UTF-8", "C"):
            with self.subTest(name=name):
                info = self.status({"LANG": name})
                self.assertIn("unknown", info["PAM application locale"])
                self.assertIn("may differ", info["PAM application locale"])

    def test_locale_command_failure_keeps_shell_and_pam_diagnostics(self):
        for error in (FileNotFoundError("locale"),
                      subprocess.CalledProcessError(1, ["locale", "-a"])):
            with self.subTest(error=error), \
                 patch.dict(os.environ, {"LANG": "pl_PL.UTF-8"}, clear=True), \
                 patch.object(fp.subprocess, "run", side_effect=error):
                info = fp.inspect_status(**self.paths)
                self.assertEqual(info["Installed en_US.UTF-8 locale"],
                                 "could not determine")
                self.assertEqual(info["Shell message locale"], "pl_PL.UTF-8")
                self.assertIn("Locale warning", info)
                self.assertIn("unknown", info["PAM application locale"])


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
    def test_set_and_apply_preserve_whitespace(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "prompt.conf"
            mo = Path(td) / "state" / "fprintd.mo"
            prompt = " \tScan finger 🔐 100%\t "
            fp.set_prompt(prompt, config_path=cfg, catalog_path=mo)
            self.assertEqual(fp.read_config(cfg), prompt)
            fp.apply_prompt(config_path=cfg, catalog_path=mo)
            with mo.open("rb") as fh:
                translations = gettext.GNUTranslations(fh)
            self.assertEqual(translations.gettext(
                "Place your finger on the fingerprint reader"), prompt)
            info = fp.inspect_status(
                config_path=cfg, catalog_path=mo,
                system_catalog_path=Path(td) / "system.mo",
            )
            self.assertEqual(info["Catalog verification"],
                             "OK — translates correctly")

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
        """Verify a saved prompt through apply and native C formatting."""
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "prompt.conf"
            mo = Path(td) / "test.mo"
            prompt = "Sensor 🔐 — 100%"
            fp.write_config(prompt, config_path=cfg)
            fp.apply_prompt(config_path=cfg, catalog_path=mo)
            msgid = "Place your left index finger on %s"
            outputs = _native_asprintf(mo, [msgid], "goodix")
            self.assertEqual(outputs[msgid], prompt)


if __name__ == "__main__":
    unittest.main()
