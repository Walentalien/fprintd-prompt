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

Gettext ignores translation catalogs when the PAM application uses the `C`
or `POSIX` locale. The locale of `sudo`, GDM, lock screens, etc. can differ
from your terminal. Ensure your desktop session uses `en_US.UTF-8` for the
override to take effect.

Run `fprintd-prompt status` to check your locale settings.

## Compatibility

The utility relies on exact upstream gettext `msgid` strings from:

[fingerprint-strings.h](https://github.com/FrameworkComputer/fprintd/blob/master/pam/fingerprint-strings.h)

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

- **Locale warning**: Your shell or PAM session may be using `C` or `POSIX`.
  Set `LANG=en_US.UTF-8` in your environment.
- **Gettext link missing**: Reinstall the package or run
  `sudo fprintd-prompt apply`.
- **Catalog missing but config present**: Run `sudo fprintd-prompt apply`.
