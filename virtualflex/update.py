"""``sudo virtual-flex update`` — self-update from GitHub releases.

Checks the latest release, and if it's newer than what's installed, downloads
the .deb and installs it via apt (dependencies and service units handled the
normal Debian way). The running service is restarted only if it was active.
stdlib only, like the rest of the project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from . import __version__

RELEASES_API = "https://api.github.com/repos/gsa700/virtual-flex/releases/latest"
_TIMEOUT = 20


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def run(argv: list[str] | None = None) -> int:
    check_only = bool(argv) and argv[0] in ("--check", "-n")

    print(f"installed: v{__version__}")
    try:
        with urllib.request.urlopen(RELEASES_API, timeout=_TIMEOUT) as r:
            release = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"could not reach GitHub releases: {exc}", file=sys.stderr)
        return 1

    latest = str(release.get("tag_name", "")).lstrip("v")
    print(f"latest:    v{latest}")
    if _version_tuple(latest) <= _version_tuple(__version__):
        print("already up to date.")
        return 0

    asset = next((a for a in release.get("assets", [])
                  if str(a.get("name", "")).endswith("_all.deb")), None)
    if asset is None:
        print("latest release has no .deb asset", file=sys.stderr)
        return 1

    if check_only:
        print(f"update available: v{__version__} -> v{latest} (run: sudo virtual-flex update)")
        return 0

    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        print("updating needs root:  sudo virtual-flex update", file=sys.stderr)
        return 1

    url = asset["browser_download_url"]
    print(f"downloading {asset['name']} ...")
    with tempfile.TemporaryDirectory(prefix="virtual-flex-update-") as tmp:
        deb = os.path.join(tmp, asset["name"])
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(deb, "wb") as f:
                f.write(r.read())
        except (urllib.error.URLError, OSError) as exc:
            print(f"download failed: {exc}", file=sys.stderr)
            return 1

        print(f"installing v{latest} ...")
        result = subprocess.run(
            ["apt-get", "install", "-y", "--allow-downgrades", deb],
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        if result.returncode != 0:
            print("install failed; the previous version is still in place.", file=sys.stderr)
            return result.returncode

    # Pick up the new code only if the service was already running.
    subprocess.run(["systemctl", "try-restart", "virtual-flex.service"])
    print(f"updated to v{latest}.")
    return 0
