"""The paper view of a claimset (design §7.4, *Paper view*; paper.py): the claims in reading order, each with what
supports it, from the fields the format defines; a file without the new ones is shown without them."""

import copy
import json
import re
from pathlib import Path

import claimset

from portal import paper, site

BASE = "https://entrylib.test"
NATIVE = json.loads((Path(claimset.__file__).parent / "data" / "examples" / "submission-native.json")
                    .read_text(encoding="utf-8")) if (Path(claimset.__file__).parent / "data" / "examples"
                                                      / "submission-native.json").exists() else None


def proofs():
    """A small paper of proofs and one computed claim: C3 is proved from C1 and C2, C2's proof uses C1, and C4,
    computed, supports C3 through two rows of its table, which a figure shows."""
    def formal(cid, statement, by, eid, **more):
        return {"id": cid, "type": "formal", "role": "principal", "novelty": "no_prior_found",
                "statement": statement, "verification": "agent_checked",
                "support": [{"kind": "formal_proof", "evidence": eid}], **more}

    def proof(eid, steps):
        return {"id": eid, "profile": "formal", "foundation": "real analysis", "description": f"Proof {eid}.",
                "steps": [{"id": f"S{i}", "statement": s, "rule": rule, "by": by}
                          for i, (s, rule, by) in enumerate(steps, 1)]}
    return {
        "schema_version": "0.44",
        "paper": {"id": "entrylib:2026.000099", "version": 1, "date": "2026-11-17", "title": "A paper of proofs",
                  "licence": "CC-BY-4.0", "origin": "native", "contributions": ["C3"],
                  "summary": "Three results and a computation."},
        "contributors": [{"id": "P1", "type": "human", "name": "Ada Example", "positions": ["guarantor"],
                          "orcid": "0000-0002-1825-0097"}],
        "definitions": [
            {"id": "D1", "term": "the term", "kind": "variable", "symbol": "$s(y,f)$",
             "definition": "The contribution of one actual $y$ and one forecast $f$."},
            {"id": "D2", "term": "the cases", "kind": "data", "definition": "Two cases, never named in a claim."}],
        "claims": [
            formal("C1", "For $y > 0$, the [[D1:term]] depends on the ratio.", [], "E1",
                   name="The term depends on the ratio", summary="Only the ratio matters."),
            formal("C2", "For $y > 0$: (a) the term is symmetric; (b) it is bounded by 1.", [], "E2",
                   name="Symmetric and bounded", depends_on=["C1"]),
            formal("C3", "The target is a weighted median.", [], "E3", name="A weighted median",
                   summary="The best forecast balances the actuals.", depends_on=["C2"],
                   checks=[{"by": "P1", "outcome": "confirmed", "extent": "full", "notes": "Read and confirmed."}]),
            {"id": "C4", "type": "descriptive", "role": "secondary", "novelty": "no_prior_found",
             "name": "Computed on two cases", "statement": "On both cases the target is the weighted median.",
             "support": [{"kind": "empirical_quant", "evidence": "E4", "results": ["E4.T1.r1"]}],
             "relations": [{"type": "supports", "target": "C3", "id_type": "local", "results": ["E4.T1.r1", "E4.T1.r2"],
                            "note": "Computed on two cases, the target is as C3 proves."}]},
            {"id": "C5", "type": "descriptive", "role": "supporting", "assumption_category": "statistical",
             "statement": "The actuals are independent.", "support": [{"kind": "assumption"}]}],
        "evidence": [
            proof("E1", [("Divide by $f$.", "algebra", []),
                         ("So the term depends on the ratio.", "conclusion", ["S1"])]),
            proof("E2", [("By C1, replace $r$ by $1/r$.", "algebra", ["C1"]),
                         ("The term is at most 1.", "algebra", [])]),
            proof("E3", [("Differentiate under the expectation.", "calculus", ["C1"]),
                         ("The derivative is zero at the target.", "algebra", ["C2", "S1"]),
                         ("So the target is a weighted median.", "conclusion", ["S2"])]),
            {"id": "E4", "profile": "quant", "design": "other", "description": "Targets computed on two cases.",
             "tables": [{"id": "T1", "description": "The target by case", "row_labels": ["case"],
                         "columns": ["target"],
                         "rows": [{"id": "r1", "label": ["first"], "values": [0.5]},
                                  {"id": "r2", "label": ["second"], "values": [0.75]},
                                  {"id": "r3", "label": ["third"], "values": [0.9]}]}]}],
        "artefacts": [{"id": "A1", "kind": "figure", "function": "data_plot", "uri": "files/first.png",
                       "description": "The first case.", "shows": ["E4.T1.r1"]},
                      {"id": "A2", "kind": "figure", "function": "data_plot", "uri": "files/third.png",
                       "description": "The third case.", "shows": ["E4.T1.r3"]}],
        "limitations": [{"id": "L1", "category": "sampling", "affects": ["C4"], "statement": "Two cases only."}],
        "references": [],
    }


def view(doc):
    out = paper.render(doc, "/p/2026.000099/record", file_url=lambda a: "/f/" + a["uri"])
    return {sid: block for sid, _t, _n, block in out["sections"]}, out


def article(page, cid):
    """The part of a page that is one claim."""
    return page.split(f'<article class="pv-claim" id="{cid}">')[1].split("</article>")[0]


def test_claims_in_reading_order_each_with_its_proof():
    sections, _ = view(proofs())
    claims = sections["claims"]
    assert re.findall(r'<article class="pv-claim" id="(C\d+)"', claims) == ["C1", "C2", "C3", "C4"]   # no assumption
    c3 = claims[claims.index('id="C3"'):claims.index('id="C4"')]
    assert '<span class="pv-claim-id">Claim C3.</span> <span class="pv-name">A weighted median</span>' in c3
    assert '<span class="pv-how">proved</span>' in c3
    assert '<p class="pv-summary">The best forecast balances the actuals.</p>' in c3
    statement, proof = c3.index("pv-statement"), c3.index('<details class="pv-proof">')
    assert statement < proof                                            # the proof under its statement
    assert "2 steps" not in c3 and "3 steps" in c3
    assert c3.count("<li>") >= 2 and "So the target is a weighted median." in c3      # the conclusion closes it
    assert 'aria-label="end of proof"' in c3
    assert "(algebra" not in claims and "from S1" not in claims         # the record's labels of a step stay there


def test_a_claim_is_named_where_a_text_gives_its_id():
    sections, _ = view(proofs())
    claims = sections["claims"]
    assert 'By <a class="pv-xref" href="#C1" title="The term depends on the ratio">claim C1</a>, replace' in claims
    c3 = claims[claims.index('id="C3"'):claims.index('id="C4"')]
    assert "as this claim proves" in c3                                 # under the claim itself
    assert '(by <a class="pv-xref" href="#C1"' in c3                    # a step that uses a claim it does not name


def test_the_parts_of_a_statement_are_a_list():
    sections, _ = view(proofs())
    assert ('<ol class="pv-parts"><li><span class="pv-mark">(a)</span><span class="pv-part">The term is symmetric'
            in sections["claims"])
    assert '<span class="pv-mark">(b)</span><span class="pv-part">It is bounded by 1.</span>' in sections["claims"]


def test_the_other_claims_that_bear_on_a_claim_with_their_rows_and_figures():
    sections, out = view(proofs())
    c3 = sections["claims"][sections["claims"].index('id="C3"'):sections["claims"].index('id="C4"')]
    assert '<p class="pv-label">Supported by numerical check C4</p>' in c3
    assert 'data-gallery="gal-C3-C4" data-i="0">1 figure</a>' in c3     # the figure that shows a named row
    assert 'data-rows="rows-C3-C4">2 table rows</a>' in c3
    gallery = re.search(r'<ol class="pv-gallery" id="gal-C3-C4" hidden>(.*?)</ol>', out["extra"]).group(1)
    assert 'data-src="/f/files/first.png"' in gallery and "third.png" not in gallery
    rows = re.search(r'<template id="rows-C3-C4">(.*?)</template>', out["extra"], re.S).group(1)
    assert "first" in rows and "second" in rows and "third" not in rows
    doc = proofs()
    del doc["claims"][3]["relations"][0]["results"]                     # without results: a line, no box
    plain = view(doc)[0]["claims"]
    assert "pv-beside" not in plain and "Supported by" in plain and "Elsewhere in this paper" in plain
    doc = proofs()                                  # results recorded one by one, not in a table: a box too
    e4 = next(e for e in doc["evidence"] if e["id"] == doc["claims"][3]["support"][0]["evidence"])
    e4["results"] = [{"id": "R1", "variable": "the count", "value": 7}, {"id": "R2", "variable": "other", "value": 9}]
    doc["claims"][3]["relations"][0]["results"] = [f"{e4['id']}.R1"]
    alone, out = view(doc)
    c3 = alone["claims"][alone["claims"].index('id="C3"'):alone["claims"].index('id="C4"')]
    assert 'data-rows="rows-C3-C4">1 result</a>' in c3 and "table row" not in c3
    held = re.search(r'<template id="rows-C3-C4">(.*?)</template>', out["extra"], re.S).group(1)
    assert "the count" in held and "7" in held and "other" not in held
    assert "The results in full, under claim C4" in held


def test_a_scope_is_written_with_its_formulae():
    doc = proofs()
    doc["claims"][3]["scope"] = {"population": "two cases", "conditions": "errors with $s=0.32$"}
    c4 = article(site.paper_page(doc, base_url=BASE, listing=[{"version": 1, "date": "2026-11-17"}]), "C4")
    scope = c4.split("<dt>Scope</dt><dd>")[1].split("</dd>")[0]
    assert "<math>" in scope and "$s=0.32$" not in scope


def test_a_name_and_a_check_are_written_with_their_formulae():
    doc = proofs()
    c = doc["claims"][3]
    c["name"] = "The $\\mathrm{MSE}_h$ likelihood"
    c["checks"] = [{"by": doc["contributors"][0]["id"], "outcome": "confirmed", "extent": "full",
                    "notes": "Derived $s_1^2$ by hand.", "resolution": "Rechecked at $h = 2$."}]
    page = site.paper_page(doc, base_url=BASE, listing=[{"version": 1, "date": "2026-11-17"}])
    c4 = article(page, c["id"])
    assert "$\\mathrm{MSE}_h$" not in c4 and "$s_1^2$" not in c4 and "$h = 2$" not in c4
    assert c4.count("<math>") >= 3                                # the name, the note and the resolution
    toc = page.split('class="pv-toc')[1] if 'class="pv-toc' in page else ""
    assert "$\\mathrm{MSE}_h$" not in page.split("<main")[0] + toc   # nor in the contents
    assert 'title="The MSEh likelihood"' in page or "\\mathrm" not in page.split(c["id"])[0]


def test_evidence_under_a_computed_claim():
    sections, out = view(proofs())
    c4 = sections["claims"][sections["claims"].index('id="C4"'):]
    assert '<span class="pv-how">evidence</span>' in c4
    assert 'data-gallery="gal-E4"' in c4 and "/f/files/first.png" in c4 and "third.png" not in c4   # the cited row's
    assert 'id="E4.T1"' in c4                                           # the table it cites
    assert '<a href="/p/2026.000099/record#E4">E4 in the record</a>' in c4
    assert 'id="gal-E4"' in out["extra"] and out["extra"].count('id="gal-E4"') == 1


def test_a_table_is_open_only_when_small_and_of_the_claims_main_evidence():
    """Design §7.4, *Tables*: under a claim, a table of its main evidence (its first support entry's) with fewer than
    10 rows stays open; a longer one, or one of other evidence, starts closed under a line with its ID, description
    and size."""
    c4 = article(site.paper_page(proofs(), base_url=BASE, listing=[{"version": 1}]), "C4")
    assert '<div class="cs-table" id="E4.T1">' in c4 and "cs-table-fold" not in c4
    doc = proofs()
    doc["evidence"][3]["tables"][0]["rows"] = [{"id": f"r{i}", "label": [f"case {i}"], "values": [i]}
                                               for i in range(1, 17)]
    c4 = article(site.paper_page(doc, base_url=BASE, listing=[{"version": 1}]), "C4")
    assert ('<details class="cs-table-fold"><summary>E4.T1 · The target by case <span class="cs-size">'
            '(16 rows × 1 column)</span></summary><div class="cs-table cs-table-long" id="E4.T1">') in c4
    doc = proofs()                                  # the same small table, of evidence that is not the claim's main
    doc["claims"][3]["support"].insert(0, {"kind": "cited", "target": "Earlier work, 2020."})
    c4 = article(site.paper_page(doc, base_url=BASE, listing=[{"version": 1}]), "C4")
    assert '<details class="cs-table-fold"><summary>E4.T1 · The target by case' in c4
    js = (Path(site.__file__).parent / "static" / "page.js").read_text(encoding="utf-8")
    assert 'el.closest("details.cs-table-fold")' in js              # opening the page at a row opens its table
    assert 'querySelectorAll("details.pv-proof, details.cs-table-fold")' in js      # and the page prints them open


def test_figures_belong_to_their_evidence_before_its_tables():
    """Design §7.4: a figure stands in its evidence, before the evidence's tables, under a claim as on the record;
    the paper view has no block of the paper's figures at its top (removed 20 November 2026)."""
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(proofs(), base_url=BASE, listing=listing)
    assert "pv-paper-figures" not in page and 'id="gal-paper"' not in page
    head = page[:page.index('class="pv-opening"')]
    assert "<img" not in head and "<figure" not in head                  # the page opens with its header, no images
    c4 = article(page, "C4")
    assert "first.png" in c4 and c4.index("<figure") < c4.index('id="E4.T1"')     # the figure, then the table
    record = site.claimset_page(proofs(), base_url=BASE, listing=listing)
    e4 = record[record.index('<div class="cs-item cs-evidence" id="E4">'):]
    assert e4.index("<figure") < e4.index('id="E4.T1"')
    assert record.count('src="files/first.png"') == 1                   # once, in its evidence


def test_a_term_stands_before_the_claim_that_first_uses_it():
    doc = proofs()
    doc["definitions"].append({"id": "D3", "term": "the ratio", "kind": "variable", "symbol": "$r$",
                               "definition": "The actual over the forecast, as the [[D1:term]] reads it."})
    doc["claims"][1]["statement"] = ("For $y > 0$: (a) the [[D1:term]] is symmetric in the [[D3:ratio]]; "
                                     "(b) it is bounded.")
    sections, _ = view(doc)
    assert "terms" not in sections                                      # no section of terms
    claims = sections["claims"]
    c1, c2 = claims.index('id="C1"'), claims.index('id="C2"')
    d1 = claims.index('<div class="pv-term" id="D1"><dt>the term <span class="pv-symbol">')
    # under the heading of the claim that first uses it, before its statement (design §7.4, *The order of a claim*)
    assert c1 < claims.index("Claim C1.") < d1 < claims.index("pv-statement", c1)
    assert claims.count('id="D1"') == 1                                 # and only there
    assert c2 < claims.index("Claim C2.") < claims.index('<div class="pv-term" id="D3">')
    assert "Term this claim uses" in claims[c1:c2] and "pv-defs" not in claims[claims.index('id="C3"'):]
    assert 'id="D2"' not in claims and "1 more definition" in claims and "/p/2026.000099/record#definitions" in claims
    doc["definitions"][0]["definition"] = "What the [[D3:ratio]] gives."   # a term whose text names a later one
    claims = view(doc)[0]["claims"]
    assert claims.index("Claim C1.") < claims.index('id="D3"') < claims.index('id="D1"')


def test_a_finding_keeps_its_place_and_a_proof_follows_what_it_uses():
    doc = proofs()
    doc["claims"][3]["depends_on"] = ["C5"]                             # C4, computed, rests on a later claim
    doc["claims"].append({"id": "C6", "type": "descriptive", "role": "supporting", "novelty": "no_prior_found",
                          "statement": "A check.", "support": [{"kind": "empirical_quant", "evidence": "E4"}]})
    doc["claims"][3]["depends_on"] = ["C6"]
    assert re.findall(r'class="pv-claim" id="(C\d+)"', view(doc)[0]["claims"]) == ["C1", "C2", "C3", "C4", "C6"]
    doc["claims"][0]["depends_on"] = ["C3"]                             # C1, proved, needs a later claim
    doc["claims"][2]["depends_on"] = []
    doc["evidence"][2]["steps"] = doc["evidence"][2]["steps"][-1:]
    assert re.findall(r'class="pv-claim" id="(C\d+)"', view(doc)[0]["claims"]) == ["C3", "C1", "C2", "C4", "C6"]


def test_a_file_without_the_new_fields():
    doc = proofs()
    for c in doc["claims"]:
        c.pop("name", None)
        c.pop("summary", None)
    doc["definitions"][0].pop("symbol")
    sections, _ = view(doc)
    assert '<span class="pv-claim-id">Claim C3</span>' in sections["claims"]
    assert "pv-name" not in sections["claims"] and "pv-summary" not in sections["claims"]
    assert "pv-symbol" not in sections["claims"]


def test_what_the_file_holds_is_escaped():
    doc = proofs()
    doc["claims"][0]["name"] = '<script>alert(1)</script>'
    doc["claims"][0]["summary"] = '<img src=x onerror=alert(1)>'
    doc["claims"][3]["relations"][0]["note"] = '<b>bold</b>'
    sections, out = view(doc)
    for text in (sections["claims"], out["extra"]):
        assert "<script>" not in text and "<img src=x" not in text and "<b>bold" not in text


def test_the_pages_and_the_switch_between_them():
    doc = proofs()
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(doc, base_url=BASE, listing=listing)
    assert '<link rel="canonical" href="https://entrylib.test/p/2026.000099">' in page
    assert '<a href="/p/2026.000099" aria-current="page"' in page and '<a href="/p/2026.000099/record" title=' in page
    for kind in ("application/json", "text/plain", "application/x-bibtex"):     # what a program is pointed to
        assert f'<link rel="alternate" type="{kind}" href="/p/2026.000099@v1.' in page, kind
    anchors, held = set(re.findall(r'href="#([^"]+)"', page)), set(re.findall(r'\bid="([^"]+)"', page))
    assert anchors - held <= {"content"}, anchors - held      # nothing links to what the page does not hold
    assert 'href="/p/2026.000099/record#E3"' in page                # what only the record holds is linked there
    for sid in ('id="summary"', 'id="claims"', 'id="limitations"', 'id="versions"',
                'class="cs-page entry" data-view="paper"', 'class="cs-claim-page" href="/p/2026.000099/C3"'):
        assert sid in page, sid
    # the claims by name in the contents, folded until asked for: a paper may have dozens
    assert ('<details class="pv-toc-fold"><summary>The claims by name</summary><ol class="pv-toc"><li><a href="#C1">'
            '<span class="pv-toc-id">C1</span> <span>The term depends on the ratio' in page)
    assert "<details class=\"pv-toc-fold\" open" not in page
    # what a program is given at the claimset's address does not depend on the view (design §7.1): the server's
    # rules look at the address, and the page still tells an assistant where the overview is
    assert f"Read {BASE}/p/2026.000099, a research paper" in page and "/p/2026.000099@v1.txt" in page
    caddy = (Path(site.__file__).parents[2] / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "rewrite @assistant /p/{re.paper.1}/overview.read.html" in caddy                 # the overview (§7.1)
    assert "rewrite @wants_text /p/{re.paper.1}/overview.txt" in caddy
    assert "rewrite @wants_text_claim {re.claim.1}.txt" in caddy
    assert "rewrite @wants_json {re.json.1}.json" in caddy and "/record" not in caddy
    assert "rewrite @slash {re.slash.1}" in caddy                    # /p/<id>/ is /p/<id>, for people too
    record = site.claimset_page(doc, base_url=BASE, listing=listing)
    assert '<a href="/p/2026.000099/record" aria-current="page"' in record
    assert '<a href="/p/2026.000099" title' in record
    assert '<link rel="canonical" href="https://entrylib.test/p/2026.000099">' in record
    old = site.claimset_page(doc, base_url=BASE, listing=listing + [{"version": 2}], current=2)
    assert "view-switch" not in old                                     # the paper view is of the current version


def test_highlights_are_marked_where_they_stand_not_listed():
    doc = proofs()
    doc["paper"]["highlights"] = ["C3", "D1"]
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(doc, base_url=BASE, listing=listing)
    assert 'id="highlights"' not in page and 'href="#highlights"' not in page       # no section in the paper view
    c3, c1 = article(page, "C3"), article(page, "C1")
    assert '<span class="pv-how pv-key">key claim</span>' in c3 and "pv-key" not in c1[:c1.index("</h3>")]
    assert '<span class="pv-how pv-key">key term</span>' in page                    # a highlighted term, at the term
    assert "pv-toc-key" not in page and '<li><a href="#C3">' in page                # no mark in the contents
    record = site.claimset_page(doc, base_url=BASE, listing=listing)
    assert 'id="highlights"' in record                                              # the record keeps the section
    plain = proofs()                                                                # no highlights: nothing marked
    assert "pv-key" not in site.paper_page(plain, base_url=BASE, listing=listing)


def test_the_page_prints_whole_and_the_manuscript_is_linked():
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(proofs(), base_url=BASE, listing=listing)
    assert ('<button type="button" class="button-quiet pv-print" aria-label="Print or save as PDF" '
            'title="Print or save as PDF: the whole paper, every proof open" hidden>PDF</button>') in page
    assert ('<p class="pv-print-id">entrylib:2026.000099@v1 · <a href="https://entrylib.test/p/2026.000099@v1">'
            'https://entrylib.test/p/2026.000099@v1</a></p>') in page          # on paper: the link to this version
    assert "pv-print-score" not in page                                    # no scores given: no line
    from portal import scores as scoring
    scored = scoring.compute(None, proofs())
    if scored:                                                             # with the rubric: the split, in one line
        line = site.paper_page(proofs(), base_url=BASE, listing=listing, scores=scored)
        line = line.split('<p class="pv-print-score">')[1].split("</p>")[0]
        assert line.startswith(f"<strong>Support: {scored['paper']['score']}/100</strong> (EntryLib rubric ")
        assert "points lost: Evidence " in line and "Open problems " in line and "Checks the record" in line
        assert "To fix" not in line and "<a" not in line                   # no explanations, no links
    assert "as its authors wrote it" not in page                          # no manuscript: the button alone
    doc = proofs()
    files = "https://entrylib.test/p/2026.000099/v1/files/"
    doc["artefacts"] += [{"id": "A3", "kind": "proof", "uri": files + "proofs.md", "description": "The proofs."},
                         {"id": "A4", "kind": "proof", "uri": files + "proofs.pdf", "description": "The same, as PDF."}]
    page = site.paper_page(doc, base_url=BASE, listing=listing)
    head = page.split('<article class="cs-body">')[0].split('<template id="artefacts-help">')[0]
    assert "proofs.pdf" not in head                  # the page itself is that document (the Files pop-up lists it)
    assert site.own_document(doc) is None
    doc["artefacts"].append({"id": "A5", "kind": "manuscript", "uri": files + "paper.PDF", "description": "The paper."})
    assert site.own_document(doc) == ("The paper as its authors wrote it", files + "paper.PDF")
    assert f'<a class="button-quiet" href="{files}paper.PDF">The paper as its authors wrote it</a>' in site.paper_page(
        doc, base_url=BASE, listing=listing)
    for uri in ("files/paper.pdf", "javascript:alert(1)//x.pdf", files + "paper.docx", None, 3):
        assert site.own_document({"artefacts": [{"id": "A1", "kind": "manuscript", "uri": uri}]}) is None, uri
    css = (Path(site.__file__).parent / "static" / "site.css").read_text(encoding="utf-8")
    js = (Path(site.__file__).parent / "static" / "page.js").read_text(encoding="utf-8")
    assert "@media print {" in css and ".entry > .panel, .entry-rail, #score, #versions" in css
    assert ".toc-bar, .to-top, .intro-strip, .for-ai, .view-switch, .ask-ai," in css   # nor the row of buttons
    assert 'window.addEventListener("beforeprint", openAll)' in js and 'querySelectorAll("details.pv-proof")' in js


def test_one_column_of_text_and_a_rail_with_the_panel_and_the_contents():
    """Design §7.4, *One column of text*: the header with the Summary, then the rail (the panel and directly under
    it the contents), then the claims; the record keeps its layout."""
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(proofs(), base_url=BASE, listing=listing)
    main = page.split('<div class="cs-page entry" data-view="paper">')[1]
    order = [main.index(s) for s in ('<div class="cs-header entry-header">', '<div class="pv-opening">',
                                     '<div class="entry-rail"><aside class="panel"', "</aside><nav class=\"cs-toc\"",
                                     '</nav></div><article class="cs-body">')]
    assert order == sorted(order)                         # header and Summary; panel, then contents; the text
    rail = main.split('<div class="entry-rail">')[1].split('<article class="cs-body">')[0]
    assert rail.count("<aside") == rail.count("<nav") == 1 and rail.endswith("</nav></div>")
    assert '<a class="toc-top" href="#top">' in rail and '<a href="#summary">Summary</a>' in rail
    assert '<a href="#claims">' in rail and 'id="summary"' in main and 'id="claims"' in main
    record = site.claimset_page(proofs(), base_url=BASE, listing=listing)
    assert "entry-rail" not in record and '</aside><nav class="cs-toc"' in record
    css = (Path(site.__file__).parent / "static" / "site.css").read_text(encoding="utf-8")
    wide = css.split(".entry-rail > .toc-bar { grid-area: bar; }")[1].split("@media (max-width: 1100px)")[0]
    assert "@media (min-width: 861px) {" in wide and 'grid-template-areas: "head rail" "body rail"' in wide
    assert "grid-template-columns: minmax(0, 50rem) 270px" in wide         # one width of text; the panel's width
    assert ".entry-rail { display: block; grid-area: rail; align-self: stretch;" in wide   # as tall as the page
    assert ".entry-rail { display: contents; }" in css                    # narrow: the one column's own items
    js = (Path(site.__file__).parent / "static" / "page.js").read_text(encoding="utf-8")
    assert 'document.querySelector(".cs-toc")' in js and "nav.parentNode.insertBefore(bar, nav)" in js


def test_three_buttons_in_one_row_under_the_byline():
    """Design §7.4, *Three buttons*: PDF, Ask your AI, and the reading view of this version as a file."""
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(proofs(), base_url=BASE, listing=listing)
    head = page.split('<div class="cs-header entry-header">')[1].split('<div class="pv-opening">')[0]
    row = head.split('<div class="ask-row">')[1].split("</div>")[0]
    assert re.findall(r"<(button|a) [^>]*>([^<]+)</", row) == [
        ("button", "PDF"), ("button", "Ask your AI about this paper"), ("a", "Text file for AI")]
    assert row.endswith('<a class="button-quiet" href="/p/2026.000099@v1.txt" download="entrylib-2026.000099-v1.txt" '
                        'title="The whole paper as plain text, to attach when your assistant cannot open the address">'
                        'Text file for AI</a>')
    assert 'class="button" data-copy="ask-message"' in row and row.count(" hidden>") == 2   # shown by the script
    assert page.count("pv-print\"") == 1 and "pv-document" not in page    # one print button; no manuscript, no line
    # what each button does is its tooltip; no line under the row, and the message is not shown (design §7.4)
    assert 'title="Copies a message with this paper&#x27;s address, to paste into ChatGPT, Claude or Gemini"' in row
    assert "ask-note" not in head and "The message</summary>" not in head
    assert '<span class="ask-message" id="ask-message" hidden>Read ' in head
    # the record: the same row without the PDF button, which is the paper view's
    record = site.claimset_page(proofs(), base_url=BASE, listing=listing)
    row = record.split('<div class="ask-row">')[1].split("</div>")[0]
    assert re.findall(r"<(button|a) [^>]*>([^<]+)</", row) == [
        ("button", "Ask your AI about this paper"), ("a", "Text file for AI")]
    assert 'href="/p/2026.000099@v1.txt" download="entrylib-2026.000099-v1.txt"' in row
    assert "pv-print" not in record
    # a claim's page: the claim's own reading view
    claim = site.claim_page(proofs(), "C3", base_url=BASE)
    row = claim.split('<div class="ask-row">')[1].split("</div>")[0]
    assert ">Ask your AI about this claim</button>" in row and "pv-print" not in claim
    assert 'href="/p/2026.000099/C3.txt" download="entrylib-2026.000099-v1-C3.txt"' in row
    assert 'title="The claim with what it rests on as plain text' in row
    js = (Path(site.__file__).parent / "static" / "page.js").read_text(encoding="utf-8")
    assert "pv-print-note" not in js and "ask-copy-note" not in js
    css = (Path(site.__file__).parent / "static" / "site.css").read_text(encoding="utf-8")
    assert ".ask-row { display: flex; flex-wrap: wrap;" in css and ".ask-row [hidden] { display: none; }" in css


def test_the_claims_stand_under_the_papers_sections():
    doc = proofs()
    doc["paper"]["sections"] = [{"title": "The weighted median", "claims": ["C3", "C1"]},
                                {"title": "Computed", "claims": ["C4"]}]
    listing = [{"version": 1, "date": "2026-11-17"}]
    page = site.paper_page(doc, base_url=BASE, listing=listing)
    claims = page.split('<article class="cs-body">')[1]
    order = re.findall(r'<h2 class="pv-sec" id="(sec-\d)">([^<]+)</h2>|<article class="pv-claim" id="(C\d)"', claims)
    # the sections' order, not the IDs' nor the proofs'; a claim no section holds follows under a heading of its own
    assert [a or c for a, _t, c in order] == ["sec-1", "C3", "C1", "sec-2", "C4", "sec-3", "C2"]
    assert [t for _a, t, _c in order if t] == ["The weighted median", "Computed", "Other claims"]
    # the line under Claims says nothing of the order, with sections or without (design §7.4, *Sections*)
    # nor of the layout (design §7.4, *A leaner paper page*): the line holds the button alone
    lead = '<h2>Claims</h2><p class="pv-lead"><button type="button" class="button-quiet pv-open-all"'
    assert lead in claims and "A term is defined" not in claims and "In the paper's" not in claims
    # the contents (design §7.4, *Sections*): under Claims each section is an entry whose title opens the list of its
    # claims, in the section's order, each shown as the claims by name show one; an arrow leads to its heading
    nav = page.split('<nav class="cs-toc"')[1].split("</nav>")[0]
    assert ('<a href="#claims">Claims</a> <span class="count">4</span><ol class="pv-toc-parts">'
            '<li class="pv-toc-sec"><details><summary>The weighted median</summary>') in nav
    entries = re.findall(
        r'<li class="pv-toc-sec"><details><summary>([^<]+)</summary><ol class="pv-toc">(.*?)</ol></details>'
        r'<a class="pv-toc-go" href="#(sec-\d)" title="Go to this section" aria-label="([^"]+)">\u2192</a></li>', nav)
    assert [(title, re.findall(r'<li><a href="#(C\d)"><span class="pv-toc-id">(C\d)</span> <span>[^<]+</span></a></li>',
                               inside), sec, label) for title, inside, sec, label in entries] == [
        ("The weighted median", [("C3", "C3"), ("C1", "C1")], "sec-1", "Go to the section The weighted median"),
        ("Computed", [("C4", "C4")], "sec-2", "Go to the section Computed"),
        ("Other claims", [("C2", "C2")], "sec-3", "Go to the section Other claims")]     # a claim in no section
    assert nav.count("<details") == nav.count("<details>") == 3                # every list closed until opened
    assert nav.count('href="#C') == 4 and "The claims by name" not in nav and "pv-toc-fold" not in nav
    assert '<li><a href="#C1"><span class="pv-toc-id">C1</span> <span>The term depends on the ratio' in nav
    # no sections: the contents as before, one folded list of every claim by name
    plain = site.paper_page(proofs(), base_url=BASE, listing=listing)
    assert 'class="pv-sec"' not in plain and lead in plain and "a proved claim comes after" not in plain
    assert 'data-close="Close all proofs">Open all proofs</button></p>' in plain          # the button stays
    for new in ("pv-toc-parts", "pv-toc-sec", "pv-toc-go", "Go to this section"):
        assert new not in plain, new
    nav = plain.split('<nav class="cs-toc"')[1].split("</nav>")[0]
    shown = re.findall(r'<article class="pv-claim" id="(C\d)"', plain)
    names = {c["id"]: " ".join(c.get("name", "").split()) for c in proofs()["claims"]}
    assert len(shown) == 4 and ('<li><a href="#claims">Claims</a> <span class="count">4</span>'
                                '<details class="pv-toc-fold"><summary>The claims by name</summary><ol class="pv-toc">'
                                + "".join(f'<li><a href="#{cid}"><span class="pv-toc-id">{cid}</span> '
                                          f'<span>{site.esc(names[cid])}</span></a></li>' for cid in shown)
                                + "</ol></details></li>") in nav
    broken = proofs()                                                             # what is not a section is left out
    broken["paper"]["sections"] = [{"title": "", "claims": ["C1"]}, "C2", {"title": "Real", "claims": ["C9", "C5"]}]
    assert 'class="pv-sec"' not in site.paper_page(broken, base_url=BASE, listing=listing)
    escaped = proofs()
    escaped["paper"]["sections"] = [{"title": "<b>Bold</b>", "claims": ["C1", "C2", "C3", "C4"]}]
    escaped["claims"][0]["name"] = 'A <i>name</i> & "quoted"'
    page = site.paper_page(escaped, base_url=BASE, listing=listing)
    nav = page.split('<nav class="cs-toc"')[1].split("</nav>")[0]
    assert '<h2 class="pv-sec" id="sec-1">&lt;b&gt;Bold&lt;/b&gt;</h2>' in page and "<b>Bold" not in page
    assert ("<summary>&lt;b&gt;Bold&lt;/b&gt;</summary>" in nav
            and 'aria-label="Go to the section &lt;b&gt;Bold&lt;/b&gt;"' in nav)
    assert "<span>A &lt;i&gt;name&lt;/i&gt; &amp; &quot;quoted&quot;</span>" in nav and "<i>name" not in page
    # the script marks the entry of the section being read and opens no list; the styles of the entries and headings
    js = (Path(site.__file__).parent / "static" / "page.js").read_text(encoding="utf-8")
    assert 'nav.querySelectorAll("a.pv-toc-go")' in js and 'classList.toggle("pv-toc-here", on)' in js
    assert ".open = " not in js.split("// The site's header")[0]              # the lists are the reader's to open
    css = (Path(site.__file__).parent / "static" / "site.css").read_text(encoding="utf-8")
    assert ".pv-toc-here > details > summary { font-weight: 600;" in css
    # a section's heading: an h2 of the page's size, over the claims' h3, and not outranked by the rules of
    # claimset.css for the headings in a section, one of which drew it smaller than a claim's
    assert ".pv-section > .pv-sec { margin: 34px 0 6px; padding-top: 20px; border-top: 2px solid var(--ink); " \
           "font-size: 26px;" in css
    record_css = (Path(site.__file__).parent / "page_css.py").read_text(encoding="utf-8")
    assert ".cs-section h2 { margin: 0 0 10px; font-size: 26px;" in record_css
    assert ".cs-section h3 { margin: 22px 0 8px; font-size: 19px;" in record_css and "\n.pv-sec {" not in css
    assert ".pv-claim h3 { margin: 0; font-size: 20px;" in css                     # and the one below it
    printed = css.split("@media print {")[1]
    assert (".pv-section > .pv-sec { font-size: 15pt; margin: 16pt 0 0; padding-top: 8pt; border-top: 1px solid #000; "
            "break-after: avoid; }") in printed                # on paper: never alone at the foot of a page
    assert ".pv-sec + .pv-claim, .pv-sec + .pv-claim > :first-child { break-before: avoid; }" in printed


def test_a_claim_that_checks_others_by_computation_is_a_numerical_check():
    sections, _ = view(proofs())                    # C4, computed and secondary, supports C3 and nothing else
    claims = sections["claims"]
    assert '<span class="pv-claim-id">Numerical check C4.</span>' in claims
    assert '<p class="pv-label">Supported by numerical check C4</p>' in claims
    assert '<span class="pv-claim-id">Claim C3.</span>' in claims
    doc = proofs()
    doc["claims"][3]["relations"].append({"type": "qualifies", "target": "C2", "id_type": "local", "note": "A limit."})
    assert "Numerical check" not in view(doc)[0]["claims"]                 # it also limits a claim: a claim
    doc = proofs()
    doc["claims"][3]["role"] = "principal"
    doc["paper"]["contributions"].append("C4")
    assert "Numerical check" not in view(doc)[0]["claims"]                 # a principal result of the paper: a claim



def test_a_relation_from_a_claim_argued_before_its_evidence():
    """A claim whose first support is an argument (no evidence) and whose relation names no observations: the paper
    view lists it as a line beside its target. It raised a KeyError on the consent page of two corrections."""
    doc = proofs()
    doc["warrants"] = [{"id": "W1", "reasoning": "abductive", "premises": ["C3"], "text": "Why C3 holds in practice."}]
    doc["claims"].append({"id": "C6", "type": "interpretive", "role": "secondary", "novelty": "no_prior_found",
                          "statement": "The bound is tight in practice.", "provenance": "author_stated",
                          "support": [{"kind": "argument", "warrant": "W1"},
                                      {"kind": "empirical_quant", "evidence": "E4"}],
                          "relations": [{"type": "explains", "target": "C3", "id_type": "local", "note": "Why."}]})
    claims = view(doc)[0]["claims"]
    assert "C6" in claims and "Why." in claims

def test_written_with_the_claimset(tmp_path):
    doc = proofs()
    site.write_claimset(tmp_path, BASE, "2026.000099", {1: doc}, [{"version": 1, "date": "2026-11-17"}], {})
    p = tmp_path / "p"
    assert 'class="pv-claim" id="C3"' in (p / "2026.000099.html").read_text(encoding="utf-8")   # people: the paper
    record = (p / "2026.000099" / "record.html").read_text(encoding="utf-8")
    assert 'class="pv-claim"' not in record and 'id="evidence"' in record and 'data-view="paper"' not in record
    assert record == (p / "2026.000099@v1.html").read_text(encoding="utf-8")    # a version's page is its record


def test_the_example_of_the_format():
    if NATIVE is None:
        return
    doc = copy.deepcopy(NATIVE)
    doc["paper"].update({"id": "entrylib:2026.000098", "version": 1, "date": "2026-11-17"})
    page = site.paper_page(doc, base_url=BASE, listing=[{"version": 1}])
    assert 'class="pv-claim" id="C2"' in page and 'id="C1"' in page     # C1, an assumption, in Assumptions
    assert page.index('id="claims"') < page.index('id="assumptions"')


def test_a_claim_from_a_lab_links_its_trail():
    trail = "/p/2026.000001/v1/lab/C3.txt"
    page = site.claim_page(proofs(), "C3", base_url=BASE, trail=trail)
    assert f'<a href="{trail}">Its trail</a>' in page
    assert "Its trail" not in site.claim_page(proofs(), "C3", base_url=BASE)


def test_a_step_written_as_bare_latex_is_a_formula():
    """Claimset spec §3.4: a proof step's statement is LaTeX, with or without $…$."""
    from portal.page import bare_formula
    first = r"y - \mu_1 \overset{d}{=} \mu_1 - y"
    second = (r"\mathcal{R}(\mu_{0.5}) = \mathrm{E}[(y-\mu_1)_+^{0.5}] = \mathrm{E}[(\mu_1-y)_+^{0.5}]"
              r" = \mathcal{I}(\mu_{0.5})")
    assert bare_formula(first) and bare_formula(second) and bare_formula(r"x_1 = \text{the first value}")
    for text in ("By symmetry, $y - \\mu_1$ and $\\mu_1 - y$ have one law.", "Substitute step 1 into step 2.",
                 r"Since \mu_1 is the mean of the variable", "`a_b`", "[[D1:term]] with x_1", "", None):
        assert not bare_formula(text)
    doc = proofs()
    e = next(x for x in doc["evidence"] if x.get("steps"))
    e["steps"][0]["statement"] = first
    e["steps"][1]["statement"] = second
    listing = [{"version": 1, "date": "2026-11-17"}]
    for page in (site.paper_page(doc, base_url=BASE, listing=listing),
                 site.claimset_page(doc, base_url=BASE, listing=listing)):
        shown = re.sub(r"<annotation.*?</annotation>", "", page, flags=re.S)   # the TeX kept in the MathML
        assert "\\mu_1" not in shown and page.count('<span class="cs-step-math"><math') >= 2


def test_an_agent_is_named_with_its_model():
    """Design §7.4 (option C): the model, "Claude Opus 5.5"; the harness on hover and in the Contributions fold."""
    from portal.page import agent_name, harness, model_names
    models = [{"id": "M1", "name": "Claude Opus", "version": "5.5"}, {"id": "M2", "name": "GPT-6", "version": "6"},
              {"id": "M3", "name": "Model <b>", "version": None}]
    code = {"type": "agent", "name": "Claude Code", "system": {"name": "Claude Code", "version": "2.1"},
            "models": [{"model": "M1"}]}
    assert agent_name(code, models) == "Claude Opus 5.5" and harness(code) == "Claude Code 2.1"
    two = {"type": "agent", "name": "Review agent", "models": [{"model": "M1"}, {"model": "M2"}, {"model": "M1"}]}
    assert agent_name(two, models) == "Claude Opus 5.5 and GPT-6" and harness(two) is None
    assert agent_name({"type": "agent", "name": "Claude Code"}, models) == "Claude Code"          # none known
    assert agent_name({"type": "agent", "models": [{"model": "M9"}]}, models) == "an AI agent"
    assert model_names({"models": [{"model": "M3"}]}, models) == ["Model <b>"]
    assert model_names({"models": "M1"}, models) == [] and model_names({"models": [{"model": "M1"}]}, "x") == []

    doc = proofs()
    doc["models"] = models
    doc["contributors"].append({"id": "P9", "type": "agent", "name": "Claude Code", "positions": ["author"],
                                "system": {"name": "Claude <Code>"}, "models": [{"model": "M3", "role": "sole"}],
                                "credit_roles": ["software"]})
    page = site.paper_page(doc, base_url=BASE, listing=[{"version": 1, "date": "2026-11-17"}])
    assert "Model &lt;b&gt;" in page and "Model <b>" not in page                                  # escaped
    assert 'title="Run in Claude &lt;Code&gt;"' in page and "in Claude &lt;Code&gt;</span>" in page   # hover; fold


def test_an_agent_named_by_its_model_is_not_also_called_an_ai_agent():
    """A model's name says what the agent is; the icon marks it. "(AI agent)" stays for an agent without a model."""
    from portal.page import _author, _contributions
    models = [{"id": "M1", "name": "Claude Opus", "version": "5.5"}]
    named = {"type": "agent", "name": "Claude Code", "system": {"name": "Claude Code"},
             "models": [{"model": "M1"}], "credit_roles": ["software"]}
    assert _author(named, models=models) == "Claude Opus 5.5"
    assert _author({"type": "agent", "name": "Claude Code"}, models=models) == "Claude Code (AI agent)"
    assert "AI agent" not in _contributions([named], models)


def test_a_claim_lists_the_assumptions_it_rests_on_through_the_claims_between():
    doc = proofs()
    doc["claims"][0]["depends_on"] = ["C5"]                       # C1 assumes C5; C2 and C3 rest on C1
    sections, _ = view(doc)
    claims = sections["claims"]
    for cid in ("C1", "C2", "C3"):
        block = claims[claims.index(f'id="{cid}"'):]
        block = block[:block.index("</article>")]
        line = '<p class="pv-assumes"><span class="pv-label">Assumption</span> <a class="pv-xref" href="#C5">C5</a></p>'
        assert line in block, cid
        assert block.index("</h3>") < block.index(line) < block.index("pv-statement")   # after the terms, before it
    c4 = claims[claims.index('id="C4"'):]
    assert "pv-assumes" not in c4[:c4.index("</article>")]                            # C4 rests on no claim


def test_every_orcid_carries_the_id_icon():
    """The iD icon beside every ORCID iD on a paper's page, the co-authors' as the responsible researcher's; only
    the researcher's says it was verified."""
    doc = copy.deepcopy(NATIVE)
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1})
    doc["contributors"].append({"id": "AC9", "type": "human", "name": "B. Coauthor", "orcid": "0000-0002-1825-0097",
                                "positions": ["coauthor"]})
    page = site.paper_page(doc, base_url=BASE, listing=[{"version": 1}])
    assert '<a class="orcid" href="https://orcid.org/0000-0002-1825-0097">' in page
    css = (Path(site.__file__).parent / "static" / "site.css").read_text(encoding="utf-8")
    rule = re.search(r"\n\.orcid, \.orcid-verified \{([^}]*)\}", css)
    assert rule and "url(/img/orcid.svg)" in rule.group(1)
