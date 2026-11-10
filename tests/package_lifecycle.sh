#!/bin/bash
# This test changes the package database; run only in a disposable Arch container.
set -euo pipefail

if (( EUID != 0 )) || [[ ! -e /.dockerenv ]]; then
    echo "This test requires root inside a disposable Docker container." >&2
    exit 1
fi

package=$(realpath "${1:?usage: package_lifecycle.sh PACKAGE}")
if pacman -Qq fprintd-prompt >/dev/null 2>&1 || [[ -e /etc/fprintd-prompt.conf ]]; then
    echo "This test requires a clean fprintd-prompt installation state." >&2
    exit 1
fi

pacman -U --noconfirm "$package"
prompt='  Package test 🔐 100%  '
fprintd-prompt set "$prompt"
[[ $(fprintd-prompt get) == "$prompt" ]]
[[ $(readlink /usr/share/locale/en_US/LC_MESSAGES/fprintd.mo) == /var/lib/fprintd-prompt/fprintd.mo ]]
fprintd-prompt status | grep -F 'Catalog verification: OK — translates correctly'

# A reinstall invokes post_upgrade; remove the generated catalog to require regeneration.
rm /var/lib/fprintd-prompt/fprintd.mo
pacman -U --noconfirm "$package"
[[ $(fprintd-prompt get) == "$prompt" ]]
fprintd-prompt status | grep -F 'Catalog verification: OK — translates correctly'

pacman -R --noconfirm fprintd-prompt
[[ ! -e /usr/share/locale/en_US/LC_MESSAGES/fprintd.mo ]]
[[ ! -L /usr/share/locale/en_US/LC_MESSAGES/fprintd.mo ]]
[[ ! -e /var/lib/fprintd-prompt/fprintd.mo ]]
[[ $(</etc/fprintd-prompt.conf) == "$prompt" ]]
rm /etc/fprintd-prompt.conf
echo "Package install, upgrade-hook regeneration, and removal checks passed."
