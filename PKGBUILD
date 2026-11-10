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
sha256sums=('7a666f55087af7203acbfd36d83bd8c9380577c55a854fa874920972daf54add')

package() {
    install -Dm755 "$srcdir/fprintd_prompt.py" \
        "$pkgdir/usr/bin/fprintd-prompt"

    install -d "$pkgdir/usr/share/locale/en_US/LC_MESSAGES"
    ln -s /var/lib/fprintd-prompt/fprintd.mo \
        "$pkgdir/usr/share/locale/en_US/LC_MESSAGES/fprintd.mo"

    install -d "$pkgdir/var/lib/fprintd-prompt"
}
