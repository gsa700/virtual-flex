"""--help must document the setup/update commands — they're dispatched before
argparse, so without the epilog they'd be invisible to users."""
import pytest

from virtualflex.__main__ import parse_args


def test_help_documents_the_subcommands(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--help"])
    out = capsys.readouterr().out
    assert "setup" in out
    assert "update" in out
    assert "--check" in out


def test_version_flag(capsys):
    from virtualflex import __version__
    with pytest.raises(SystemExit):
        parse_args(["--version"])
    assert __version__ in capsys.readouterr().out
