pkgname=fprintd-prompt
pkgver=1.0.0
pkgrel=1
pkgdesc='CLI to set a custom pam_fprintd authentication prompt'
arch=('any')
url='https://github.com/Walentalien/fprintd-prompt'
license=('CC0-1.0')
depends=('fprintd' 'gettext' 'python')
install=fprintd-prompt.install
source=('fprintd_prompt.py')
sha256sums=('bf9d39452591d8dc61ea53790fd0f01fd631cf60a6f7521f1562a6717ad8fbd0')

package() {
    install -Dm755 "$srcdir/fprintd_prompt.py" \
        "$pkgdir/usr/bin/fprintd-prompt"

    install -d "$pkgdir/usr/share/locale/en_US/LC_MESSAGES"
    ln -s /var/lib/fprintd-prompt/fprintd.mo \
        "$pkgdir/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo"

    install -d "$pkgdir/var/lib/fprintd-prompt"
}
