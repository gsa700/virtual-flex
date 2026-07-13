#!/usr/bin/env bash
#
# build-zip.sh — build a generic source .zip (Windows / any platform).
# Usage: bash deploy/build-zip.sh [version]   (version defaults to pyproject)
# Contains the tracked source at HEAD; run with `python -m virtualflex`.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(sed -nE 's/^version *= *"([^"]+)".*/\1/p' "${REPO_DIR}/pyproject.toml" | head -1)}"
[ -n "$VERSION" ] || { echo "could not determine version"; exit 1; }

mkdir -p "${REPO_DIR}/dist"
OUT="${REPO_DIR}/dist/virtual-flex-${VERSION}.zip"
git -C "$REPO_DIR" archive --format=zip --prefix="virtual-flex-${VERSION}/" -o "$OUT" HEAD
echo "built: $OUT"
