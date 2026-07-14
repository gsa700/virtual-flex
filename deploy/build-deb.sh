#!/usr/bin/env bash
#
# build-deb.sh — build the virtual-flex .deb (architecture: all, pure Python).
# Usage: bash deploy/build-deb.sh [version]   (version defaults to pyproject)
# Needs dpkg-deb (Debian/Ubuntu, or `apt install dpkg`). Output: dist/*.deb
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${REPO_DIR}/deploy/pkg"
VERSION="${1:-$(sed -nE 's/^version *= *"([^"]+)".*/\1/p' "${REPO_DIR}/pyproject.toml" | head -1)}"
[ -n "$VERSION" ] || { echo "could not determine version"; exit 1; }
PKG=virtual-flex
ARCH=all

command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found (apt install dpkg)"; exit 1; }

STAGE="$(mktemp -d)/${PKG}_${VERSION}_${ARCH}"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib/virtual-flex" "$STAGE/lib/systemd/system" \
         "$STAGE/etc/virtual-flex" "$STAGE/usr/share/doc/virtual-flex"

# --- payload ---
cp -r "${REPO_DIR}/virtualflex" "$STAGE/usr/lib/virtual-flex/"
find "$STAGE/usr/lib/virtual-flex" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "${PKG_DIR}/virtual-flex.service" "${PKG_DIR}/virtual-flex-rigctld.service" "$STAGE/lib/systemd/system/"
cp "${PKG_DIR}/config.toml" "${PKG_DIR}/rigctld.env" "$STAGE/etc/virtual-flex/"
cp "${REPO_DIR}/README.md" "$STAGE/usr/share/doc/virtual-flex/"

# --- control metadata ---
INSTALLED_KB="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: hamradio
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.11), libhamlib-utils, libnss-mdns, avahi-daemon
Maintainer: AB0R <gsa700@users.noreply.github.com>
Homepage: https://github.com/gsa700/virtual-flex
Installed-Size: ${INSTALLED_KB}
Description: Virtual FlexRadio for the 4O3A Genius stack
 Impersonates a FLEX-6000/8000 on the LAN so a non-Flex rig (via Hamlib) drives
 the 4O3A PGXL/TGXL/AGXL stack automatically, as if it were a Flex - band-follow
 and keying, over the network.
EOF

cat > "$STAGE/DEBIAN/conffiles" <<'EOF'
/etc/virtual-flex/config.toml
/etc/virtual-flex/rigctld.env
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload || true
systemctl enable virtual-flex-rigctld.service virtual-flex.service >/dev/null 2>&1 || true
echo "virtual-flex installed. Next:"
echo "  1. edit /etc/virtual-flex/rigctld.env  (K4_HOST, RIG_MODEL)"
echo "  2. edit /etc/virtual-flex/config.toml   (serial, broadcast, ptt K4 host)"
echo "  3. sudo systemctl start virtual-flex-rigctld virtual-flex"
echo "The host must share the 4O3A stack's LAN subnet (discovery is a broadcast)."
exit 0
EOF

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
  systemctl stop virtual-flex.service virtual-flex-rigctld.service >/dev/null 2>&1 || true
  systemctl disable virtual-flex.service virtual-flex-rigctld.service >/dev/null 2>&1 || true
fi
exit 0
EOF

cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
exit 0
EOF

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

mkdir -p "${REPO_DIR}/dist"
OUT="${REPO_DIR}/dist/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo "built: $OUT"
