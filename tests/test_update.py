"""`virtual-flex update` — version comparison and the check/refuse paths.
Network and apt are mocked; the real download/install path is exercised on the
station, not in CI."""
import io
import json
from unittest import mock

from virtualflex import update
from virtualflex.update import _version_tuple


def test_package_version_matches_pyproject():
    # The updater compares GitHub's latest tag against __version__ — if this
    # constant goes stale (it happened: stuck at 0.2.1 through v0.2.4), update
    # would reinstall on every run. Keep the two sources pinned together.
    import pathlib
    import tomllib
    pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject, "rb") as f:
        assert tomllib.load(f)["project"]["version"] == update.__version__


def test_version_tuple_ordering():
    assert _version_tuple("0.2.5") > _version_tuple("0.2.4")
    assert _version_tuple("v0.2.5") == _version_tuple("0.2.5")
    assert _version_tuple("0.10.0") > _version_tuple("0.9.9")
    assert _version_tuple("garbage") == (0,)          # never explodes


def _fake_release(tag, with_deb=True):
    assets = [{"name": f"virtual-flex_{tag.lstrip('v')}_all.deb",
               "browser_download_url": "https://example.invalid/x.deb"}] if with_deb else []
    body = json.dumps({"tag_name": tag, "assets": assets}).encode()
    resp = io.BytesIO(body)
    resp.__enter__ = lambda *a: resp                 # context-manager shim
    resp.__exit__ = lambda *a: False
    return resp


def test_up_to_date_is_a_noop():
    with mock.patch.object(update.urllib.request, "urlopen",
                           return_value=_fake_release(f"v{update.__version__}")):
        assert update.run([]) == 0                   # no root needed, nothing installed


def test_check_mode_reports_without_installing():
    with mock.patch.object(update.urllib.request, "urlopen",
                           return_value=_fake_release("v99.0.0")):
        assert update.run(["--check"]) == 0          # reports, never installs


def test_install_refused_without_root():
    with mock.patch.object(update.urllib.request, "urlopen",
                           return_value=_fake_release("v99.0.0")), \
         mock.patch.object(update.os, "geteuid", create=True, return_value=1000):
        assert update.run([]) == 1                   # needs sudo


def test_missing_deb_asset_fails_cleanly():
    with mock.patch.object(update.urllib.request, "urlopen",
                           return_value=_fake_release("v99.0.0", with_deb=False)):
        assert update.run(["--check"]) == 1
