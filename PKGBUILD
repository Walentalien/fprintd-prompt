pkgname=fprintd-custom-prompt
pkgver=2.0.0
pkgrel=1
pkgdesc='CLI to set a custom pam_fprintd authentication prompt'
arch=('any')
url='https://github.com/Walentalien/fprintd-en-us-prompt-override'
license=('CC0-1.0')
depends=('fprintd' 'gettext' 'python')
makedepends=()
provides=('fprintd-en-us-prompt-override')
conflicts=('fprintd-en-us-prompt-override')
replaces=('fprintd-en-us-prompt-override')
install=fprintd-custom-prompt.install
source=('fprintd_prompt.py')
sha256sums=('0f9859532505c1fde3fc06b890ce0bab33872fb39dbc41adc2c2abe2bc835c6b')

package() {
    install -Dm755 "$srcdir/fprintd_prompt.py" \
        "$pkgdir/usr/bin/fprintd-prompt"

    install -d "$pkgdir/usr/share/locale/en_US/LC_MESSAGES"
    ln -s /var/lib/fprintd-custom-prompt/fprintd.mo \
        "$pkgdir/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo"

    install -d "$pkgdir/var/lib/fprintd-custom-prompt"
}
