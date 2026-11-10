#!/usr/bin/env python3
"""fprintd-prompt — CLI to set a custom pam_fprintd authentication prompt.

Overrides the en_US gettext messages used by pam_fprintd so that the
fingerprint reader prompt displays user-chosen text instead of the
upstream default.

The core technique (GNU gettext catalog override) is unchanged;
this tool simply automates PO generation, compilation, and
symlink management so the user never edits files manually.
"""

from __future__ import annotations

import argparse
import gettext
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

__version__ = "2.0.0"

# ---------------------------------------------------------------------------
# Fixed system paths (production)
# ---------------------------------------------------------------------------

CONFIG_PATH = Path("/etc/fprintd-prompt.conf")
STATE_DIR = Path("/var/lib/fprintd-prompt")
CATALOG_PATH = STATE_DIR / "fprintd.mo"
SYSTEM_CATALOG_PATH = Path("/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo")

# ---------------------------------------------------------------------------
# Upstream fprintd initial-prompt msgids (from fingerprint-strings.h)
# ---------------------------------------------------------------------------

FINGERS = [
    "finger",
    "left thumb",
    "left index finger",
    "left middle finger",
    "left ring finger",
    "left little finger",
    "right thumb",
    "right index finger",
    "right middle finger",
    "right ring finger",
    "right little finger",
]

PLACE_GENERIC = "Place your {finger} on the fingerprint reader"
PLACE_SPECIFIC = "Place your {finger} on %s"
SWIPE_GENERIC = "Swipe your {finger} across the fingerprint reader"
SWIPE_SPECIFIC = "Swipe your {finger} across %s"

TEMPLATES = [PLACE_GENERIC, PLACE_SPECIFIC, SWIPE_GENERIC, SWIPE_SPECIFIC]


def build_initial_msgids() -> list[str]:
    """Return the 44 upstream initial-prompt msgid strings."""
    msgids: list[str] = []
    for finger in FINGERS:
        for tmpl in TEMPLATES:
            msgids.append(tmpl.format(finger=finger))
    return msgids


INITIAL_MSGIDS = build_initial_msgids()

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_MAX_PROMPT_BYTES = 4096

# Control characters we reject (NUL, CR, LF, and other C0/C1 controls).
# Tab (0x09) is allowed since some terminals use it.
_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0a-\x1f\x7f\x80-\x9f]"
)


def validate_prompt(prompt: str) -> None:
    """Raise ValueError if *prompt* is not a usable PAM prompt."""
    if not prompt:
        raise ValueError("Prompt must not be empty.")
    if _CONTROL_CHAR_RE.search(prompt):
        raise ValueError(
            "Prompt contains control characters (NUL, newline, "
            "carriage return, etc.) which are not allowed."
        )
    encoded = prompt.encode("utf-8")
    if len(encoded) > _MAX_PROMPT_BYTES:
        raise ValueError(
            f"Prompt is {len(encoded)} UTF-8 bytes; "
            f"maximum is {_MAX_PROMPT_BYTES}."
        )


# ---------------------------------------------------------------------------
# PO string escaping
# ---------------------------------------------------------------------------

def po_quote(text: str) -> str:
    """Escape *text* for inclusion inside a PO double-quoted string.

    Handles backslashes and double-quotes.  Newlines are not expected
    (they are rejected during validation).
    """
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    return text


# ---------------------------------------------------------------------------
# PO generation
# ---------------------------------------------------------------------------

def printf_safe_translation(prompt: str, *, is_device_specific: bool) -> str:
    """Build a msgstr for the upstream literal or C formatting path.

    Generic messages use strdup after gettext lookup, so their translations
    must preserve the prompt literally.

    For device-specific messages the upstream code does:
        asprintf(&s, translated_message, driver_name);

    We must ensure the user's literal ``%`` never becomes a printf
    directive while still consuming the required *driver_name* argument.

    For device-specific messages:
    - Escape every ``%`` as ``%%``.
    - Append ``%.0s`` to silently consume the driver-name string.
    """
    if not is_device_specific:
        return prompt
    return prompt.replace("%", "%%") + "%.0s"


def render_po(prompt: str) -> str:
    """Return a complete PO file body for the 44 upstream msgids."""
    lines: list[str] = []
    lines.append('msgid ""')
    lines.append('msgstr ""')
    lines.append('"Project-Id-Version: fprintd-prompt\\n"')
    lines.append('"Language: en_US\\n"')
    lines.append('"MIME-Version: 1.0\\n"')
    lines.append('"Content-Type: text/plain; charset=UTF-8\\n"')
    lines.append('"Content-Transfer-Encoding: 8bit\\n"')

    for msgid in INITIAL_MSGIDS:
        is_device_specific = "%s" in msgid
        trans = printf_safe_translation(prompt, is_device_specific=is_device_specific)
        lines.append("")
        if is_device_specific:
            lines.append("#, c-format")
        lines.append(f'msgid "{po_quote(msgid)}"')
        lines.append(f'msgstr "{po_quote(trans)}"')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _write_all(fd: int, data: bytes) -> None:
    """Write all bytes, retrying short writes."""
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written == 0:
            raise OSError("write made no progress")
        remaining = remaining[written:]


def _atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Write *data* to *path* atomically via a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        try:
            _write_all(fd, data)
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Catalog compilation
# ---------------------------------------------------------------------------

def compile_catalog(po_text: str, output: Path) -> None:
    """Compile *po_text* into a .mo file at *output* atomically using msgfmt."""
    output.parent.mkdir(parents=True, exist_ok=True)
    fd_po, po_tmp = tempfile.mkstemp(suffix=".po")
    fd_mo, mo_tmp = tempfile.mkstemp(dir=output.parent, suffix=".mo.tmp")
    os.close(fd_mo)
    try:
        try:
            _write_all(fd_po, po_text.encode("utf-8"))
        finally:
            os.close(fd_po)
        subprocess.run(
            ["msgfmt", "--check", "--check-format", po_tmp, "-o", mo_tmp],
            check=True,
            capture_output=True,
            text=True,
        )
        os.chmod(mo_tmp, 0o644)
        os.replace(mo_tmp, output)
    finally:
        for tmp in (po_tmp, mo_tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def read_config(config_path: Path = CONFIG_PATH) -> str | None:
    """Return the configured prompt, or None if no config exists."""
    try:
        text = config_path.read_text(encoding="utf-8").removesuffix("\n")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Configuration file {config_path} is not valid UTF-8."
        ) from exc
    return text if text else None


def write_config(prompt: str, config_path: Path = CONFIG_PATH) -> None:
    """Atomically write the prompt to the configuration file."""
    _atomic_write(config_path, prompt.encode("utf-8") + b"\n", mode=0o644)


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------

def set_prompt(
    prompt: str,
    *,
    config_path: Path = CONFIG_PATH,
    catalog_path: Path = CATALOG_PATH,
) -> None:
    """Prepare both files, then publish with rollback on catalog failure.

    This handles I/O errors, not crashes or concurrent writers. If restoring
    an existing config fails, keep its backup for manual recovery.
    """
    validate_prompt(prompt)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    config_staging = Path(tempfile.mkdtemp(
        prefix=".fprintd-prompt-", dir=config_path.parent,
    ))
    backup = config_staging / "previous.conf"
    new_config = config_staging / "new.conf"
    keep_backup = False
    try:
        with tempfile.TemporaryDirectory(
            prefix=".fprintd-prompt-", dir=catalog_path.parent,
            ignore_cleanup_errors=True,
        ) as td:
            new_catalog = Path(td) / "fprintd.mo"
            compile_catalog(render_po(prompt), new_catalog)
            try:
                shutil.copy2(config_path, backup)
                had_config = True
            except FileNotFoundError:
                had_config = False
            write_config(prompt, config_path=new_config)
            os.replace(new_config, config_path)
            try:
                os.replace(new_catalog, catalog_path)
            except OSError as update_error:
                try:
                    if had_config:
                        os.replace(backup, config_path)
                    else:
                        config_path.unlink()
                except OSError as rollback_error:
                    keep_backup = had_config
                    recovery = (
                        f"Restore {backup} to {config_path}."
                        if had_config else
                        f"Remove {config_path} to restore the previous state."
                    )
                    raise OSError(
                        f"Catalog update failed ({update_error}); configuration "
                        f"rollback failed ({rollback_error}). {recovery}"
                    ) from update_error
                raise
    finally:
        if not keep_backup:
            shutil.rmtree(config_staging, ignore_errors=True)


def apply_prompt(
    prompt: str | None = None,
    *,
    config_path: Path = CONFIG_PATH,
    catalog_path: Path = CATALOG_PATH,
) -> str:
    """Generate the .mo catalog from the stored or supplied prompt.

    Returns a status message.
    """
    if prompt is None:
        prompt = read_config(config_path)
    if prompt is None:
        return "No custom prompt is configured. Nothing to apply."

    validate_prompt(prompt)
    po_text = render_po(prompt)
    compile_catalog(po_text, catalog_path)
    return f"Custom prompt applied: {prompt}"


def reset_prompt(
    *,
    config_path: Path = CONFIG_PATH,
    catalog_path: Path = CATALOG_PATH,
    state_dir: Path = STATE_DIR,
) -> str:
    """Remove configuration and generated catalog. Idempotent."""
    removed: list[str] = []
    for p in (config_path, catalog_path):
        try:
            p.unlink()
            removed.append(str(p))
        except FileNotFoundError:
            pass
    if state_dir.is_dir() and not any(state_dir.iterdir()):
        try:
            state_dir.rmdir()
            removed.append(str(state_dir))
        except OSError:
            pass
    if removed:
        return "Removed: " + ", ".join(removed)
    return "Nothing to remove."


def _normalize_locale(name: str) -> str:
    """Compare locale names without encoding case or separator differences."""
    locale_name, at, modifier = name.partition("@")
    language, dot, codeset = locale_name.partition(".")
    codeset = codeset.lower().replace("-", "").replace("_", "")
    return language.lower() + dot + codeset + at + modifier


def inspect_status(
    *,
    config_path: Path = CONFIG_PATH,
    catalog_path: Path = CATALOG_PATH,
    system_catalog_path: Path = SYSTEM_CATALOG_PATH,
) -> dict[str, str]:
    """Gather diagnostic status information."""
    info: dict[str, str] = {}

    prompt = read_config(config_path)
    info["Custom prompt"] = prompt if prompt else "disabled"
    info["Prompt"] = prompt if prompt else "(none)"
    info["Config"] = "present" if config_path.is_file() else "missing"
    info["Catalog"] = "present" if catalog_path.is_file() else "missing"

    # Symlink check
    if system_catalog_path.is_symlink():
        target = os.readlink(system_catalog_path)
        if target == str(catalog_path):
            info["Gettext link"] = "OK"
        else:
            info["Gettext link"] = f"wrong target ({target})"
    elif system_catalog_path.exists():
        info["Gettext link"] = "exists (not a symlink)"
    else:
        info["Gettext link"] = "missing"

    # Message locale requested by the shell environment, not the PAM process.
    lang = os.environ.get("LANG", "")
    lc_messages = os.environ.get("LC_MESSAGES", "")
    lc_all = os.environ.get("LC_ALL", "")
    effective = lc_all if lc_all else (lc_messages if lc_messages else lang)
    info["Shell message locale"] = effective or "(unset; defaults to C)"
    language_pref = os.environ.get("LANGUAGE", "")
    info["Shell LANGUAGE"] = language_pref or "(unset)"
    info["PAM application locale"] = "unknown — may differ from this shell"
    message_base = _normalize_locale(effective).split("@", 1)[0].split(".", 1)[0]

    if not effective or message_base in ("c", "posix"):
        info["Locale warning"] = (
            "Gettext translations are disabled by the shell message locale; "
            "LANGUAGE is ignored."
        )
    elif language_pref:
        info["Locale warning"] = (
            "LANGUAGE overrides the shell message locale; en_US catalog "
            "selection depends on its preference list."
        )
    elif message_base != "en_us":
        info["Locale warning"] = (
            "The shell message locale does not normally select the en_US catalog."
        )

    # Verify the catalog actually translates a representative message
    if catalog_path.is_file():
        try:
            with open(catalog_path, "rb") as fh:
                t = gettext.GNUTranslations(fh)
            test_msg = t.gettext(
                "Place your right index finger on the fingerprint reader"
            )
            if test_msg == prompt:
                info["Catalog verification"] = "OK — translates correctly"
            else:
                info["Catalog verification"] = (
                    f"unexpected translation: {test_msg!r}"
                )
        except Exception as exc:
            info["Catalog verification"] = f"error: {exc}"
    elif prompt:
        info["Catalog verification"] = "catalog missing but config present"

    # Installed locale availability is independent of the shell/PAM selection.
    try:
        result = subprocess.run(
            ["locale", "-a"],
            capture_output=True,
            text=True,
            check=True,
        )
        locales = result.stdout.strip().splitlines()
        if any(_normalize_locale(name) == "en_us.utf8" for name in locales):
            info["Installed en_US.UTF-8 locale"] = "available"
        else:
            info["Installed en_US.UTF-8 locale"] = "not listed by locale -a"
    except (OSError, subprocess.CalledProcessError):
        info["Installed en_US.UTF-8 locale"] = "could not determine"

    return info


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fprintd-prompt",
        description="Set a custom pam_fprintd fingerprint prompt.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    p_set = sub.add_parser("set", help="Set the custom prompt text.")
    p_set.add_argument("prompt", help="The prompt text to display.")

    sub.add_parser("get", help="Show the currently configured prompt.")
    sub.add_parser("apply", help="Rebuild the catalog from the saved config.")
    sub.add_parser("reset", help="Remove the custom prompt and restore defaults.")
    sub.add_parser("status", help="Show diagnostic status information.")

    return parser


# ---------------------------------------------------------------------------
# Root check
# ---------------------------------------------------------------------------

def _require_root() -> None:
    if os.geteuid() != 0:
        print("Error: this command must be run as root.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "get":
            prompt = read_config(config_path=CONFIG_PATH)
            if prompt is None:
                print("No custom prompt is configured.", file=sys.stderr)
                sys.exit(1)
            print(prompt)
            return

        if args.command == "status":
            for key, value in inspect_status(
                config_path=CONFIG_PATH, catalog_path=CATALOG_PATH,
                system_catalog_path=SYSTEM_CATALOG_PATH,
            ).items():
                print(f"{key}: {value}")
            return

        # Commands below require root
        _require_root()

        if args.command == "set":
            prompt = args.prompt
            set_prompt(prompt, config_path=CONFIG_PATH, catalog_path=CATALOG_PATH)
            print(f"Custom prompt set: {prompt}")
            return

        if args.command == "apply":
            result = apply_prompt(config_path=CONFIG_PATH, catalog_path=CATALOG_PATH)
            print(result)
            return

        if args.command == "reset":
            result = reset_prompt()
            print(result)
            return
    except FileNotFoundError as exc:
        if exc.filename == "msgfmt" or "msgfmt" in str(exc):
            print("Error: 'msgfmt' command not found. Please install gettext.", file=sys.stderr)
            sys.exit(1)
        print(f"Error: file not found: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.strip() if exc.stderr else str(exc)
        print(f"Error compiling catalog: {err}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
