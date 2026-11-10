pkgname=fprintd-prompt
pkgver=2.0.0
pkgrel=1
pkgdesc='CLI to set a custom pam_fprintd authentication prompt'
arch=('any')
url='https://github.com/Walentalien/fprintd-prompt'
license=('CC0-1.0')
depends=('fprintd' 'gettext' 'python')
makedepends=()
provides=('fprintd-custom-prompt' 'fprintd-en-us-prompt-override')
conflicts=('fprintd-custom-prompt' 'fprintd-en-us-prompt-override')
replaces=('fprintd-custom-prompt' 'fprintd-en-us-prompt-override')
install=fprintd-prompt.install
source=('fprintd_prompt.py')
sha256sums=('952a3838055854722032432f75363ce04015ea5c05e097c98beb211c509e7292')

package() {
    install -Dm755 "$srcdir/fprintd_prompt.py" \
        "$pkgdir/usr/bin/fprintd-prompt"

    install -d "$pkgdir/usr/share/locale/en_US/LC_MESSAGES"
    ln -s /var/lib/fprintd-prompt/fprintd.mo \
        "$pkgdir/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo"

    install -d "$pkgdir/var/lib/fprintd-prompt"
}
