"""The Read page (design §7.7): the tree of fields, claims and claimsets of a part, filters."""

import pytest
from publishing import example, write

from portal import read
from portal.publish import publish


def doc_in(sub, title):
    d = example()
    d["paper"]["title"] = title
    d["paper"]["classification"] = {**(d["paper"].get("classification") or {}), "subfield": f"openalex:subfields/{sub}"}
    return d


def test_the_tree_and_the_claims(env, app_client=None):
    ctx, tmp = env
    publish(write(tmp, doc_in("1803", "Forecasting study"), "a.claimset.json"), **ctx)
    publish(write(tmp, doc_in("2613", "Probability study"), "b.claimset.json"), **ctx)
    docs = [r[0] for r in ctx["conn"].execute("SELECT v.file FROM papers p JOIN versions v ON v.concept_id ="
                                              " p.concept_id AND v.version = p.current_version").fetchall()]
    html = read.page(docs, read.Query.parse({"view": "claims"}))
    for name in ("Social Sciences", "Decision Sciences", "Management Science and Operations Research",
                 "Physical Sciences", "Mathematics", "Statistics and Probability"):
        assert name in html, name
    assert "Life Sciences" not in html                                   # empty parts are not shown
    principal = [c for c in example()["claims"] if c.get("role") == "principal"]
    assert f"{2 * len(principal)} principal claims" in html
    only = read.page(docs, read.Query.parse({"area": "18"}))
    assert "Forecasting study" in only and "Probability study" not in only
    cards = read.page(docs, read.Query.parse({"area": "d3"}))      # claimsets by default
    assert "Probability study" in cards and "Forecasting study" not in cards and 'class="card' in cards
    everything = read.page(docs, read.Query.parse({"all": "1", "view": "claims"}))
    assert "principal claims" not in everything.split("</nav>")[-1].split("</p>")[0]


@pytest.mark.parametrize("params", [{"area": "9999"}, {"view": "<x>"}, {"offset": "x"}, {"type": "x", "band": "y"},
                                    {"area": "<script>"}])
def test_odd_parameters_are_ignored(params):
    q = read.Query.parse(params)
    assert q.area == "" and q.view in ("claims", "claimsets") and q.offset >= 0
    assert "<script>" not in read.page([], q)


def test_filters(env):
    ctx, tmp = env
    publish(write(tmp, doc_in("1803", "Forecasting study"), "a.claimset.json"), **ctx)
    docs = [r[0] for r in ctx["conn"].execute("SELECT file FROM versions").fetchall()]
    types = {c.get("type") for c in example()["claims"] if c.get("role") == "principal"}
    t = sorted(types)[0]
    rows = read.claims(docs, read.Query.parse({"type": t}))
    assert rows and all(c.get("type") == t for _, c, _, _ in rows)
    assert read.claims(docs, read.Query.parse({"type": "formal" if t != "formal" else "causal"})) == []
    scores = [s for *_, s in read.claims(docs, read.Query.parse({"all": "1"}))]
    assert scores == sorted(scores, reverse=True)


def test_route(app_client):
    r = app_client.get("/read", params={"view": "claimsets", "sort": "newest"})
    assert r.status_code == 200 and "<h1>Read</h1>" in r.text and 'href="/read"' in r.text
