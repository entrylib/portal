"""Reading a published lab record: its reading view and each claim's trail (design §5.2, *Reading a lab record*)."""

import io
import json

import pytest

from portal import indexer, labrecord, site
from portal.page import _contributions

COMMIT = "1dffa04" + "0" * 33
PINNED = f"https://github.com/entrylib/study-planning/blob/{COMMIT}/claimset/smape/lab/lab.jsonl"
DOC = {"paper": {"title": "A study"}, "claims": [{"id": "C1", "hypothesis": {"lab_event": "H1"}}, {"id": "C2"}]}


def record(tmp_path):
    from claimset.lab.core import Lab
    lab = Lab.create(tmp_path / "lab", "Test study")
    me = lab.append("actor", {"kind": "human", "name": "A. Researcher", "orcid": "0000-0000-0000-0000"},
                    by="AC1")["id"]
    q = lab.append("question", {"text": "Does X help?"}, by=me)["id"]
    lab.append("hypothesis", {"statement": "X helps.", "question": q, "origin": "a_priori"}, by=me)
    return lab.log_path.read_text(encoding="utf-8")


def needs_views():
    pytest.importorskip("claimset.lab.view")


def test_only_a_log_pinned_to_a_commit_is_fetched():
    assert labrecord.raw_url(PINNED) == ("https://raw.githubusercontent.com/entrylib/study-planning/"
                                         f"{COMMIT}/claimset/smape/lab/lab.jsonl")
    assert labrecord.where(PINNED) == "entrylib/study-planning, commit 1dffa04"
    for moving in ("https://github.com/entrylib/study-planning/blob/main/lab/lab.jsonl",
                   "https://example.org/lab.jsonl", None, 7):
        assert labrecord.raw_url(moving) is None and labrecord.where(moving) is None


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_is_off_in_tests_and_capped(monkeypatch):
    asked = []

    def opener(req, timeout):
        asked.append(req.full_url)
        return Answer(b"x" * (labrecord.MAX_BYTES + 10))

    assert labrecord.fetch(PINNED, opener) is None and asked == []          # PORTAL_LAB_FETCH=0
    monkeypatch.setenv("PORTAL_LAB_FETCH", "1")
    assert labrecord.fetch(PINNED, opener) is None                          # too large
    assert asked == [labrecord.raw_url(PINNED)]
    assert labrecord.fetch(PINNED, lambda req, timeout: Answer(b'{"seq": 1}\n')) == '{"seq": 1}\n'

    def broken(req, timeout):
        raise OSError("unreachable")
    assert labrecord.fetch(PINNED, broken) is None


def test_views_of_a_record(tmp_path):
    needs_views()
    reading, trails = labrecord.views(record(tmp_path), DOC)
    assert reading.startswith("LAB RECORD: A study") and "A. Researcher" in reading
    assert list(trails) == ["C1"] and "TRAIL OF H1 (claim C1)" in trails["C1"]
    assert labrecord.views("not json", DOC) is None


def test_views_are_written_once_per_package_version(tmp_path, monkeypatch):
    needs_views()
    text, out = record(tmp_path), tmp_path / "v1"
    fetched = []
    monkeypatch.setattr(labrecord, "fetch", lambda uri: fetched.append(uri) or text)
    made = indexer.write_lab_views(out, "/p/2026.000001/v1", DOC, None, PINNED)
    assert made == {"view": "/p/2026.000001/v1/lab.txt", "trails": {"C1": "/p/2026.000001/v1/lab/C1.txt"}}
    assert (out / "lab.txt").read_text().startswith("LAB RECORD") and (out / "lab" / "C1.txt").exists()
    assert indexer.write_lab_views(out, "/p/2026.000001/v1", DOC, None, PINNED) == made
    assert fetched == [PINNED]                                               # not asked again
    monkeypatch.setattr(labrecord, "package_version", lambda: "9.9.9")
    indexer.write_lab_views(out, "/p/2026.000001/v1", DOC, None, PINNED)
    assert fetched == [PINNED, PINNED]                                       # a new package makes them again
    assert json.loads((out / "lab.views.json").read_text())["claimset"] == "9.9.9"


def test_the_registry_copy_needs_no_fetch_and_no_record_gives_no_view(tmp_path, monkeypatch):
    needs_views()
    monkeypatch.setattr(labrecord, "fetch", lambda uri: pytest.fail("fetched"))
    made = indexer.write_lab_views(tmp_path / "a", "/x", DOC, record(tmp_path), PINNED)
    assert made["view"] == "/x/lab.txt"
    monkeypatch.setattr(labrecord, "fetch", lambda uri: None)
    assert indexer.write_lab_views(tmp_path / "b", "/x", DOC, None, PINNED) is None


def test_the_panel_row_and_the_claim_link():
    lab = {"copy": PINNED, "view": "/p/k/v1/lab.txt", "where": "entrylib/study-planning, commit 1dffa04"}
    row = site._lab_row(lab)
    assert "<h2>Lab record</h2>" in row and 'href="/p/k/v1/lab.txt">Readable record' in row
    assert f'href="{PINNED}">Log' in row and "Kept in entrylib/study-planning, commit 1dffa04" in row
    assert site._lab_row(None) == "" and site._lab_row({"summary": "x"}) == ""
    assert "Readable" not in site._lab_row({"copy": "/p/k/v1/lab.jsonl"})


def test_contributions_list_credit_roles():
    people = [{"type": "human", "name": "A <b>", "credit_roles": ["conceptualization", "writing_original_draft"]},
              {"type": "agent", "name": "Claude Code", "credit_roles": ["formal_analysis"]},
              {"type": "human", "name": "B"}]
    fold = _contributions(people)
    assert fold.startswith('<details class="cs-credit"><summary>Contributions</summary>')
    assert "A &lt;b&gt;: Conceptualization, Writing – original draft" in fold
    assert "Claude Code" in fold and "Formal analysis" in fold and ">B" not in fold
    assert _contributions([{"name": "B"}]) == ""


def test_the_record_is_named_once_in_the_panel_not_under_the_byline():
    row = site._lab_row({"copy": "/p/k/v1/lab.jsonl", "summary": "49 events", "verified": True})
    assert "49 events; hash chain verified" in row
    line = site._origin_line({"paper": {}}, "lab", {"copy": "/p/k/v1/lab.jsonl", "summary": "49 events"})
    assert line == '<p class="origin-line">Made with <a href="/lab">claimset-lab</a>.</p>'
