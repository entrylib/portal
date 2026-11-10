"""Reading (design §7.1, §7.2): claim bundles, the HTML page and /llms.txt written at publication, and full-text search
over claims and papers of current versions."""

import datetime as dt
import json

import pytest
from publishing import BASE, example, write

from portal import search
from portal.indexer import reindex
from portal.publish import publish

KEY = "2026.000001"


def published(env):
    ctx, tmp = env
    concept, _ = publish(write(tmp, example()), **ctx)
    return ctx, tmp, concept


def test_claim_bundles_page_and_llms_txt(env):
    ctx, _, concept = published(env)
    out = ctx["published_dir"]
    text = (out / "p" / KEY / "C2.txt").read_text()
    assert text.startswith(f"CLAIM C2 of {concept} Method M")
    bundle = json.loads((out / "p" / KEY / "C2.json").read_text())
    assert bundle["bundle_of"] == "C2" and bundle["paper"]["id"] == concept
    assert [c["id"] for c in bundle["claims"]] == ["C2", "C1", "C3"]
    assert {f.name for f in (out / "p" / KEY).glob("C*")} == {f"C{i}.{e}" for i in (1, 2, 3) for e in ("json", "txt")}
    page = (out / "p" / f"{KEY}.html").read_text()
    assert page.startswith("<!doctype html>") and page.count("<script") == 1 and 'class="cs-page entry"' in page
    assert "<title>Method M" in page and f'href="/p/{KEY}@v1.json"' in page
    llms = (out / "llms.txt").read_text()
    assert f"{BASE}/api/search/claims?q=" in llms and "data" in llms and "{base}" not in llms
    assert f"{BASE}/mcp" in llms and f"{BASE}/api/submissions/from-url" in llms and "new_paper" in llms
    assert "## Extensions" in llms and "`ext` blocks" in llms


def test_submitted_text_is_escaped_in_the_page(env):
    ctx, tmp = env
    doc = example()
    doc["paper"]["title"] = "Method M <script>alert(1)</script> & co"
    publish(write(tmp, doc), **ctx)
    page = (ctx["published_dir"] / "p" / f"{KEY}.html").read_text()
    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in page


def test_bundles_follow_the_current_version(env):
    ctx, tmp, concept = published(env)
    doc = example()
    doc["paper"]["id"] = concept
    doc["paper"]["correction_reason"] = "The first claim was not needed."
    doc["claims"] = [c for c in doc["claims"] if c["id"] != "C1"]
    for c in doc["claims"]:
        c["assumptions"] = [a for a in c.get("assumptions") or [] if a != "C1"]
        if not c["assumptions"]:
            c.pop("assumptions")
    for d in doc["definitions"] + doc["evidence"]:
        if "assumptions" in d:
            d["assumptions"] = [a for a in d["assumptions"] if a != "C1"] or d.pop("assumptions")
    publish(write(tmp, doc, "fixed.claimset.json"), **{**ctx, "today": dt.date(2026, 11, 5)})
    names = {f.name for f in (ctx["published_dir"] / "p" / KEY).glob("C*")}
    assert "C1.txt" not in names and "C2.txt" in names


class TestSearch:
    def test_claims_by_words_and_stems(self, env):
        ctx, _, concept = published(env)
        wide = search.search_claims(ctx["conn"], BASE, "seasonality")["results"]   # stems: "seasonal" too
        assert {r["claim"] for r in wide} == {"C1", "C2", "C3"}            # C3 through the paper's title
        assert search.search_claims(ctx["conn"], BASE, "d2")["results"] == []          # term markup is not indexed
        out = search.search_claims(ctx["conn"], BASE, "annual seasonality")  # every word must match
        assert [r["claim"] for r in out["results"]] == ["C1"]
        r = out["results"][0]
        assert r["id"] == f"{concept}@v1#C1" and r["bundle"] == f"{BASE}/p/{KEY}/C1.txt"
        assert r["status"] == "active" and r["paper_title"].startswith("Method M") and r["licence"] == "CC-BY-4.0"
        assert isinstance(r["warnings"], list)
        assert "C1" in [r["claim"] for r in search.search_claims(ctx["conn"], BASE, "seasonal")["results"]]

    def test_scope_and_terms_find_the_claim(self, env):
        ctx, _, _ = published(env)
        hits = search.search_claims(ctx["conn"], BASE, "horizons")["results"]     # only in C2's scope
        assert [r["claim"] for r in hits] == ["C2"]

    def test_filters(self, env):
        ctx, _, _ = published(env)
        q = "method"
        assert {r["role"] for r in search.search_claims(ctx["conn"], BASE, q, role="principal")["results"]} == {
            "principal"}
        assert search.search_claims(ctx["conn"], BASE, q, role="principal", type="causal")["results"] == []
        assert all("empirical_quant" in r["support"]
                   for r in search.search_claims(ctx["conn"], BASE, q, support="empirical_quant")["results"])
        assert search.search_claims(ctx["conn"], BASE, q, licence="CC0-1.0")["results"] == []
        for bad in ({"type": "Causal"}, {"role": "main"}, {"support": "data"}, {"assumption": "maybe"}):
            with pytest.raises(search.SearchError):
                search.search_claims(ctx["conn"], BASE, q, **bad)
        for limit, offset in ((0, 0), (51, 0), (10, -1), ("x", 0)):
            with pytest.raises(search.SearchError):
                search.search_claims(ctx["conn"], BASE, q, limit, offset)
        with pytest.raises(search.SearchError):
            search.search_claims(ctx["conn"], BASE, "   ")

    def test_papers(self, env):
        ctx, _, concept = published(env)
        out = search.search_papers(ctx["conn"], BASE, "retail sales")
        assert [r["id"] for r in out["results"]] == [concept]
        assert out["results"][0]["principal_claims"] and out["results"][0]["version"] == 1
        assert search.search_papers(ctx["conn"], BASE, "photosynthesis")["results"] == []

    def test_only_current_versions(self, env):
        ctx, tmp, concept = published(env)
        doc = example()
        doc["paper"]["id"] = concept
        doc["paper"]["correction_reason"] = "Clearer wording."
        c1 = next(c for c in doc["claims"] if c["id"] == "C1")
        c1["statement"] = "Monthly retail sales series show yearly cycles."
        publish(write(tmp, doc, "fixed.claimset.json"), **{**ctx, "today": dt.date(2026, 11, 5)})
        assert search.search_claims(ctx["conn"], BASE, "annual")["results"] == []          # only in version 1
        hits = search.search_claims(ctx["conn"], BASE, "yearly cycles")["results"]
        assert [(r["claim"], r["version"], r["status"]) for r in hits] == [("C1", 2, "corrected")]
        assert hits[0]["status_notice"]["statement"] == "Clearer wording."

    def test_reindex_rebuilds_the_search(self, env):
        ctx, _, _ = published(env)
        ctx["conn"].execute("UPDATE claims SET search = ''::tsvector")
        reindex(ctx["conn"], ctx["registry"], ctx["published_dir"], BASE)
        assert search.search_claims(ctx["conn"], BASE, "annual")["results"]


def test_search_over_http(client):
    r = client.get("/api/search/claims", params={"q": "seasonality"})
    assert r.status_code == 200 and r.json()["results"] == []
    r = client.get("/api/search/claims", params={"q": "x", "type": "nonsense"})
    assert r.status_code == 400 and "type: one of" in r.json()["error"]
    assert client.get("/api/search/papers").status_code == 400


def test_reading_views_follow_claimset_updates(env, monkeypatch):
    from portal import indexer
    ctx, tmp, _ = published(env)
    out = ctx["published_dir"]
    args = (ctx["conn"], ctx["registry"], out, BASE)
    assert indexer.refresh_if_claimset_changed(*args, "0.39.2")              # no marker yet: rebuilt
    assert (out / indexer.RENDERED_BY).read_text().startswith("0.39.2 site ")
    (out / "p" / f"{KEY}.txt").write_text("stale rendering")
    assert not indexer.refresh_if_claimset_changed(*args, "0.39.2")          # same claimset: left alone
    assert (out / "p" / f"{KEY}.txt").read_text() == "stale rendering"
    assert indexer.refresh_if_claimset_changed(*args, "0.40.0")              # a new claimset: rebuilt
    assert (out / "p" / f"{KEY}.txt").read_text().startswith("CLAIMSET")
    assert indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.40.1")   # no registry yet


def test_entry_files_exist_before_anything_is_published(env):
    from portal import indexer
    ctx, _ = env
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.39.2")
    assert (out / "llms.txt").read_text().startswith("# EntryLib") and (out / "index.jsonl").read_text() == ""
