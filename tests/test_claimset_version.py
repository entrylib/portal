"""The portal works with any claimset at least MIN_CLAIMSET, with no upper bound."""

import claimset

from portal import MIN_CLAIMSET, claimset_ok
from portal.cli import main


def test_versions():
    assert claimset_ok(MIN_CLAIMSET) and claimset_ok("0.44.20") and claimset_ok("0.45.0") and claimset_ok("1.0")
    assert not claimset_ok("0.44.18") and not claimset_ok("0.41.14")
    assert claimset_ok(claimset.__version__)


def test_an_old_claimset_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(claimset, "__version__", "0.36.0")
    assert main(["check", "--registry", "."]) == 2
    assert "older than" in capsys.readouterr().err
