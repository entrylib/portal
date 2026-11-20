"""Updating the pages after an upgrade (design §7.1): each claimset is left as it is, wrapped again in a new chrome
from its kept parts, or drawn again, by what changed; the database index is rebuilt only when its own code changed;
files are written only when they change; the publisher's lock is held for one claimset at a time."""

import contextlib
import json

from publishing import BASE, example, write

from portal import chrome, indexer, scores, site
from portal.publish import publish


def published(env, n=2):
    ctx, tmp = env
    for i in range(n):
        publish(write(tmp, example(), f"{i}.claimset.json"), **ctx)
    out = ctx["published_dir"]
    args = (ctx["conn"], ctx["registry"], out, BASE)
    assert indexer.refresh_if_claimset_changed(*args, "0.44.12")          # the first marker
    return ctx, out, args


def counting(monkeypatch, *names):
    calls = {n: 0 for n in names}
    for name in names:
        real = getattr(site, name)

        def counted(*a, _real=real, _name=name, **k):
            calls[_name] += 1
            return _real(*a, **k)
        monkeypatch.setattr(site, name, counted)
    return calls


def test_a_page_keeps_its_parts_out_of_what_is_served(env):
    _, out, _ = published(env)
    parts = out / site.PARTS / "p" / "2026.000001.html.json"
    held = json.loads(parts.read_text())
    assert set(held) == {"title", "main", "active", "description", "head", "canonical", "script"}
    assert chrome.shell(**held) == (out / "p" / "2026.000001.html").read_text()
    assert site.parts_path(out / "index.html") is None
    claim = out / "p" / "2026.000001" / "C1.html"
    assert site.parts_path(claim) == out / site.PARTS / "p" / "2026.000001" / "C1.html.json"


def test_nothing_changed_nothing_written(env, monkeypatch):
    _, out, args = published(env)
    page = out / "p" / "2026.000001.html"
    before = page.stat().st_mtime_ns
    calls = counting(monkeypatch, "paper_page", "claimset_page")
    assert not indexer.refresh_if_claimset_changed(*args, "0.44.13")         # a release that renders the same
    assert calls == {"paper_page": 0, "claimset_page": 0} and page.stat().st_mtime_ns == before


def test_a_new_chrome_rewraps_without_drawing(env, monkeypatch):
    _, out, args = published(env)
    page = out / "p" / "2026.000001.html"
    calls = counting(monkeypatch, "paper_page", "claimset_page", "claim_page")
    computed = []
    monkeypatch.setattr(scores, "compute", lambda *a: computed.append(1))
    monkeypatch.setattr(chrome, "NAV", chrome.NAV + [("/new", "Something new", "new")])
    monkeypatch.setattr(chrome, "fingerprint", lambda: "a new header")
    assert indexer.refresh_if_claimset_changed(*args, "0.44.12")
    assert "Something new" in page.read_text() and "Something new" in (out / "p" / "2026.000002.html").read_text()
    assert calls == {"paper_page": 0, "claimset_page": 0, "claim_page": 0} and computed == []


def test_a_change_to_the_drawing_draws_again(env, monkeypatch):
    _, out, args = published(env)
    calls = counting(monkeypatch, "paper_page")
    monkeypatch.setattr(site, "fingerprint", lambda: "a new paper view")
    assert indexer.refresh_if_claimset_changed(*args, "0.44.12")
    assert calls["paper_page"] == 2


def test_the_index_is_rebuilt_only_when_its_code_changed(env, monkeypatch):
    _, out, args = published(env)
    rebuilt = []
    real = indexer.reindex_rows
    monkeypatch.setattr(indexer, "reindex_rows", lambda *a: rebuilt.append(1) or real(*a))
    monkeypatch.setattr(site, "fingerprint", lambda: "a new paper view")
    indexer.refresh_if_claimset_changed(*args, "0.44.12")
    assert rebuilt == []
    monkeypatch.setattr(indexer, "index_fingerprint", lambda: "a new index")
    indexer.refresh_if_claimset_changed(*args, "0.44.12")
    assert rebuilt == [1]


def test_the_lock_is_held_for_one_claimset_at_a_time(env, monkeypatch):
    _, out, args = published(env, n=3)
    held = []

    @contextlib.contextmanager
    def lock():
        held.append(1)
        yield
    monkeypatch.setattr(site, "fingerprint", lambda: "a new paper view")
    progress = []
    indexer.refresh_if_claimset_changed(*args, "0.44.12", lock=lock, progress=lambda d, t: progress.append((d, t)))
    assert len(held) == 3 + 1                                                # each claimset, then the lists
    assert progress[-1] == (3, 3)


def test_a_file_is_written_only_when_it_changes(tmp_path):
    f = tmp_path / "a.txt"
    assert site._write(f, "x") is True
    before = f.stat().st_mtime_ns
    assert site._write(f, "x") is False and f.stat().st_mtime_ns == before
    assert site._write(f, "y") is True and f.read_text() == "y"
