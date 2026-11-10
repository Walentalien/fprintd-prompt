# fprintd-prompt

Set a custom fingerprint reader prompt for `pam_fprintd` with one command:
```bash
sudo fprintd-prompt set "Touch the sensor"
```

The utility generates a GNU gettext catalog that overrides `pam_fprintd`'s `en_US` messages. 

## Installation

Build and install the Arch package:

```bash
git clone https://github.com/Walentalien/fprintd-prompt
cd fprintd-prompt
makepkg -si
```

## Usage

```bash
# Set a custom prompt
sudo fprintd-prompt set "Touch the sensor"

# View the current prompt
fprintd-prompt get

# Show diagnostic status
fprintd-prompt status

# Rebuild the catalog (e.g. after a package upgrade)
sudo fprintd-prompt apply

# Remove the custom prompt and restore upstream defaults
sudo fprintd-prompt reset
```

## Tests

With Python and gettext installed, run:

```bash
python3 -m unittest -v
```

CI runs the suite as an unprivileged user and fails if any test is skipped.
It also checks the package hook script, verifies `.SRCINFO`, and builds the
Arch package. A disposable container test installs the package, verifies catalog
regeneration during reinstall, and checks removal preserves the configuration.

## How it works

`pam_fprintd` uses GNU gettext to look up the `en_US` translation of its fingerprint prompt messages.
The package installs a symlink:

```
/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo
  -> /var/lib/fprintd-prompt/fprintd.mo
```

When `fprintd-prompt set` is run, the tool:

1. Validates the prompt text.
2. Generates a `.po` file covering all 44 upstream initial prompt variants.
3. Compiles it with `msgfmt` and stages the new catalog and configuration.
4. Saves the prompt to `/etc/fprintd-prompt.conf`, then activates the catalog.

If catalog activation fails, the previous configuration is restored. If that
rollback also fails, the error reports how to recover and, when a previous
configuration existed, where its backup was kept. Each file replacement is
atomic; the pair is not a single transaction and does not protect against
process crashes or simultaneous updates.

Authentication behavior is completely unchanged. Only the displayed text is affected.

## Locale caveat

Gettext ignores translation catalogs in `C`/`POSIX` message locales, including
`C.UTF-8`. For the override to appear, the PAM application must select the
`en_US` catalog. GNU gettext's `LANGUAGE` preference list can override the
message language, except in those C/POSIX locales.

`fprintd-prompt status` reports installed `en_US.UTF-8` availability separately
from the shell's message-locale environment (`LC_ALL` > `LC_MESSAGES` > `LANG`)
and `LANGUAGE`. Names such as `en_US.UTF-8` and `en_US.utf8` are equivalent for
this availability check. The command cannot determine the actual locale used
by sudo, GDM, or a lock screen; check the calling application's settings.

## Compatibility

The utility relies on exact upstream gettext `msgid` strings. The 44 initial
prompt identifiers are verified against fprintd 1.94.5's
[fingerprint-strings.h](https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/pam/fingerprint-strings.h).
Unit tests use a committed reference without network access. CI also compares
the identifiers with upstream source for the fprintd release installed by Arch.

If upstream changes these strings in a future release, authentication will
still work, but the custom prompt may not appear until the utility is updated
with the new identifiers.

## Uninstall

```bash
sudo pacman -Rns fprintd-prompt
```

This removes the package, the symlink, and the generated catalog. Upstream
prompt behavior is immediately restored. The configuration file
`/etc/fprintd-prompt.conf` is preserved; remove it manually if desired.

## Troubleshooting

Run the diagnostic command first:

```bash
fprintd-prompt status
```

Common issues:

- **Locale warning**: Check `LC_ALL`, `LC_MESSAGES`, `LANG`, and `LANGUAGE` in
  the PAM application's environment. Shell settings alone do not establish
  which catalog that application selects.
- **Gettext link missing or incorrect**: Reinstall the package to restore the
  symlink. `apply` rebuilds the catalog but does not create or repair that link.
- **Catalog missing but config present**: Run `sudo fprintd-prompt apply`.
