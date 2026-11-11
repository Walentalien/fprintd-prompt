pkgname=fprintd-prompt
pkgver=2.0.0
pkgrel=1
pkgdesc='CLI to set a custom pam_fprintd authentication prompt'
arch=('any')
url='https://github.com/Walentalien/fprintd-prompt'
license=('CC0-1.0')
depends=('fprintd' 'gettext' 'python')
install=fprintd-prompt.install
source=('fprintd_prompt.py')
sha256sums=('bcc7aaae91c790470c799140763fd554a7255fc967ccee2d1453d75869c69848')

package() {
    install -Dm755 "$srcdir/fprintd_prompt.py" \
        "$pkgdir/usr/bin/fprintd-prompt"

    install -d "$pkgdir/usr/share/locale/en_US/LC_MESSAGES"
    ln -s /var/lib/fprintd-prompt/fprintd.mo \
        "$pkgdir/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo"

    install -d "$pkgdir/var/lib/fprintd-prompt"
}
