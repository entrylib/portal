"""Scores on the site (design §7.6): computed by the rubric at publication, shown on the page, the reading view and
score.json; the close-match check against earlier claimsets."""

import json

import pytest
from publishing import BASE, example, write

from portal import score_html, scores, site
from portal.publish import publish

pytest.importorskip("rubric")

KEY = "2026.000001"


def test_scores_are_written_and_shown(env):
    ctx, tmp = env
    publish(write(tmp, example()), **ctx)
    p = ctx["published_dir"] / "p"
    data = json.loads((p / f"{KEY}.score.json").read_text())
    assert data == json.loads((p / f"{KEY}@v1.score.json").read_text())
    assert data["rubric"] == scores.version() and data["paper"]["score"] is not None
    assert data["note"].startswith("Scores are computed by rules")
    page = (p / f"{KEY}.html").read_text()
    paper = data["paper"]
    assert f'<span class="score-num">{paper["score"]}</span>' in page
    assert 'id="score"' in page and 'id="score-paper"' in page and '<a href="#score">Score</a>' in page
    for cid in data["claims"]:
        assert f'id="score-{cid}"' in page
        assert f'href="#score-{cid}" data-popup="score-{cid}"' in page
    assert page.count('class="dots"') >= len(data["claims"])
    assert "SCORES" in (p / f"{KEY}.txt").read_text()
    assert "SCORES" in (p / f"{KEY}.read.html").read_text()
    issues = (p / f"{KEY}.issues.txt").read_text()
    assert issues == (p / f"{KEY}@v1.issues.txt").read_text() and "To fix:" in issues
    assert all(f"{pid}. " in issues for pid in data["paper"]["problems"])
    assert page.count(f'href="/p/{KEY}@v1.issues.txt"') == 2            # the panel and the section Score


def test_problem_text_is_escaped():
    doc = example()
    doc["limitations"] = [{"id": "L9", "category": "other", "statement": "<script>alert(1)</script>",
                           "affects": ["C2"], "impact": "could_reverse", "mitigation": "none"}]
    html = score_html.section(scores.compute(None, doc))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_the_rubric_scores_and_reports():
    """One place for scoring (design §7.6): the portal's scores are rubric.assess on the file with the verifiability
    the platform sets, and the issues are rubric.report, the same as `claimset score` gives before submission."""
    import rubric
    from claimset.validate import with_verifiability
    if not hasattr(rubric, "assess"):
        pytest.skip("the installed rubric is older than rubric.assess")
    doc = with_verifiability(example())
    result = scores.compute(None, doc)
    assert {k: v for k, v in result.items() if k != "note"} == rubric.assess(doc)
    assert all(not n["checked"] for n in result["novelty"].values())       # no database: nothing compared
    text = scores.issues_text(result, "entrylib:2026.000001", 1, "https://entrylib.org")
    assert text.endswith(rubric.report(result)) and "claimset score" in text


def test_the_rubric_reads_the_validators_warnings(monkeypatch):
    """Design §7.6: the portal gives the rubric the current validator's warnings, from rubric 0.3, and says how the
    paper's score is made (the mean, with the lowest) in the page and the reading view."""
    import rubric
    if "warnings" not in __import__("inspect").signature(rubric.score).parameters:
        pytest.skip("the installed rubric is older than 0.3")
    seen = {}
    real = scores._warnings
    monkeypatch.setattr(scores, "_warnings", lambda doc: seen.setdefault("w", real(doc)))
    doc = example()
    doc["paper"]["id"] = "entrylib:2026.000001"
    result = scores.compute(None, doc)
    assert isinstance(seen["w"], list) and result["paper"]["lowest_score"] is not None
    assert "the mean of its" in scores.text(result) and "The mean of its" in score_html.section(result)
    assert scores.paper_score(doc)["score"] == result["paper"]["score"]       # lists and pages agree


def test_without_scores_the_page_shows_a_dash():
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    page = site.claimset_page(doc, base_url="https://entrylib.org", listing=[])
    assert '<p class="score">–</p>' in page and 'id="score"' not in page and 'class="lights"' in page
    assert score_html.marker(None)({"id": "C1"}, "claim") is None              # the package's light then


def test_close_match_with_an_earlier_claimset(env):
    ctx, tmp = env
    first = example()
    publish(write(tmp, first, "a.claimset.json"), **ctx)
    second = example()
    second["paper"]["title"] = "A different study of the same thing"
    ctx2 = {**ctx, "today": ctx["today"].replace(day=ctx["today"].day + 1)}
    concept, _ = publish(write(tmp, second, "b.claimset.json"), **ctx2)
    data = json.loads((ctx["published_dir"] / "p" / f"{concept.split(':')[1]}.score.json").read_text())
    principal = data["paper"]["principal"][0]
    n = data["novelty"][principal]
    assert n["checked"] and n["check"] == "unacknowledged"
    assert n["matches"][0]["claim"] == f"entrylib:2026.000001#{principal}"
    first_scores = json.loads((ctx["published_dir"] / "p" / f"{KEY}.score.json").read_text())
    assert first_scores["novelty"][principal]["check"] == "none"     # only earlier claimsets count


def test_lists_show_reliability(env):
    ctx, tmp = env
    publish(write(tmp, example()), **ctx)
    score = json.loads((ctx["published_dir"] / "p" / f"{KEY}.score.json").read_text())["paper"]
    for page in ("index.html", "all.html"):
        text = (ctx["published_dir"] / page).read_text()
        assert f'<span class="card-score-num">{score["score"]}</span>' in text, page
        assert f'href="/p/{KEY}#score"' in text


def test_a_rubric_without_what_the_portal_calls_counts_as_not_installed(monkeypatch):
    import importlib
    import types

    old = types.ModuleType("rubric")
    old.VERSION, old.RUBRIC = "0.2.0", {"groups": []}
    old.score = old.stems = lambda *a: None                     # no assess and no report, as before they were added
    monkeypatch.setitem(__import__("sys").modules, "rubric", old)
    try:
        reloaded = importlib.reload(scores)
        assert reloaded.rubric is None
        assert reloaded.compute(None, example()) is None and reloaded.version() is None
    finally:
        monkeypatch.undo()
        importlib.reload(scores)
    assert scores.rubric is not None


def test_a_failing_rubric_leaves_out_the_scores_and_nothing_else(env, monkeypatch, capsys):
    ctx, tmp = env

    def broken(doc, find):
        raise ValueError("a bug in the rubric")

    monkeypatch.setattr(scores.rubric, "assess", broken)
    concept, version = publish(write(tmp, example()), **ctx)          # published all the same
    assert (concept, version) == ("entrylib:2026.000001", 1)
    p = ctx["published_dir"] / "p"
    assert (p / f"{KEY}.html").exists() and (p / f"{KEY}@v1.json").exists()
    assert not (p / f"{KEY}.score.json").exists()
    assert ctx["conn"].execute("SELECT current_version FROM papers").fetchall() == [(1,)]
    err = capsys.readouterr().err
    assert "RUBRIC ERROR while scoring entrylib:2026.000001@v1" in err and "a bug in the rubric" in err


def test_a_failed_query_of_the_rubric_does_not_abort_a_rebuild(env, monkeypatch, capsys):
    from portal.indexer import reindex
    ctx, tmp = env
    publish(write(tmp, example()), **ctx)
    publish(write(tmp, example(), "b.claimset.json"), **ctx)
    monkeypatch.setattr(scores, "_candidates", lambda conn, *a, **k: conn.execute("SELECT nonsense FROM nowhere"))
    monkeypatch.setattr(scores.rubric, "assess", lambda doc, find: find("forecast accuracy"))
    reindex(ctx["conn"], ctx["registry"], ctx["published_dir"], BASE)
    rows = ctx["conn"].execute("SELECT concept_id, current_version FROM papers ORDER BY 1").fetchall()
    assert rows == [("entrylib:2026.000001", 1), ("entrylib:2026.000002", 1)]
    assert "RUBRIC ERROR" in capsys.readouterr().err


def test_a_failing_report_leaves_out_the_issues(env, monkeypatch):
    ctx, tmp = env

    def broken(result):
        raise KeyError("group")

    monkeypatch.setattr(scores.rubric, "report", broken)
    publish(write(tmp, example()), **ctx)
    p = ctx["published_dir"] / "p"
    assert (p / f"{KEY}.score.json").exists() and not (p / f"{KEY}.issues.txt").exists()
