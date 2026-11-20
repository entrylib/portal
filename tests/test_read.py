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


def test_the_index_gives_the_page_the_files_give(env, monkeypatch):
    """Design §7.7: Read from the index (page_from_db) is the page Read made from every paper's file (page), for
    every view, area, filter, sort and page; only the papers shown are read."""
    import datetime as dt
    import itertools

    ctx, tmp = env
    for i, (sub, day) in enumerate([("1803", 3), ("2613", 1), ("1803", 2), ("1404", 3), ("2613", 5), ("1803", 1)]):
        d = doc_in(sub, f"Study {i}")
        publish(write(tmp, d, f"{i}.claimset.json"), **{**ctx, "today": dt.date(2026, 11, day)})
    conn = ctx["conn"]
    docs = [r[0] for r in conn.execute("SELECT v.file FROM papers p JOIN versions v ON v.concept_id = p.concept_id"
                                       " AND v.version = p.current_version ORDER BY p.updated DESC, p.concept_id")]
    monkeypatch.setattr(read, "PAGE", 2)                                    # several pages from few papers
    out = ctx["published_dir"]
    bands = [""] + sorted({x.get("band") for d in docs for x in (read.scores_of(d, out) or {}).get("claims", {})
                           .values() if x.get("band")})
    checked = 0
    for view, area, band, sort, everything, offset in itertools.product(
            ("claimsets", "claims"), ("", "d2", "18", "1803", "2613", "1404", "d3"), bands, ("newest", "support"),
            (False, True), (0, 2, 4)):
        params = {"view": view, "area": area, "band": band, "sort": sort, "all": "1" if everything else "",
                  "offset": str(offset)}
        q = read.Query.parse(params)
        assert read.page_from_db(conn, q, "https://e.test", set(), out) == read.page(docs, q, "https://e.test",
                                                                                     set(), out), params
        checked += 1
    for flt in ({"type": example()["claims"][0].get("type")}, {"planning": "exploratory"},
                {"novelty": example()["claims"][0].get("novelty") or ""}):
        q = read.Query.parse({"view": "claims", "all": "1", **flt})
        assert read.page_from_db(conn, q, "", set(), out) == read.page(docs, q, "", set(), out), flt
    assert checked > 100


def test_the_read_route_reads_only_the_papers_it_shows(app_client, monkeypatch):
    from portal import read as read_module
    seen = []
    real = read_module._files
    monkeypatch.setattr(read_module, "_files",
                        lambda conn, concepts: seen.append(len(concepts)) or real(conn, concepts))
    assert app_client.get("/read").status_code == 200
    assert all(n <= read_module.PAGE for n in seen)
