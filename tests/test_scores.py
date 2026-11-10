"""Scores on the site (design §7.6): computed by the rubric at publication, shown on the page, the reading view and
score.json; the close-match check against earlier claimsets."""

import json

import pytest
from publishing import example, write

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


def test_without_scores_the_page_shows_a_dash():
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    page = site.claimset_page(doc, base_url="https://entrylib.org", listing=[])
    assert '<p class="score">–</p>' in page and 'id="score"' not in page and 'class="lights"' in page
    assert score_html.decorate("<p>x</p>", None) == "<p>x</p>"


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
