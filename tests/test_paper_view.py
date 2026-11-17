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
    out = paper.render(doc, "/p/2026.000099", file_url=lambda a: "/f/" + a["uri"])
    return {sid: block for sid, _t, _n, block in out["sections"]}, out


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
    assert '<p class="pv-label">Supported by claim C4</p>' in c3
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


def test_evidence_under_a_computed_claim():
    sections, out = view(proofs())
    c4 = sections["claims"][sections["claims"].index('id="C4"'):]
    assert '<span class="pv-how">evidence</span>' in c4
    assert 'data-gallery="gal-E4"' in c4 and "/f/files/first.png" in c4 and "third.png" not in c4   # the cited row's
    assert 'id="E4.T1"' in c4                                           # the table it cites
    assert '<a href="/p/2026.000099#E4">E4 in the record</a>' in c4
    assert 'id="gal-E4"' in out["extra"] and out["extra"].count('id="gal-E4"') == 1


def test_terms_are_those_the_claims_name_with_their_symbols():
    sections, _ = view(proofs())
    terms = sections["terms"]
    assert '<div class="pv-term" id="D1"><dt>the term <span class="pv-symbol">' in terms and "<math" in terms
    assert 'id="D2"' not in terms and '1 more definition' in terms and '/p/2026.000099#definitions' in terms


def test_a_file_without_the_new_fields():
    doc = proofs()
    for c in doc["claims"]:
        c.pop("name", None)
        c.pop("summary", None)
    doc["definitions"][0].pop("symbol")
    sections, _ = view(doc)
    assert '<span class="pv-claim-id">Claim C3</span>' in sections["claims"]
    assert "pv-name" not in sections["claims"] and "pv-summary" not in sections["claims"]
    assert "pv-symbol" not in sections["terms"]


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
    assert '<a href="/p/2026.000099/paper" aria-current="page"' in page and '<a href="/p/2026.000099" title=' in page
    for sid in ('id="summary"', 'id="terms"', 'id="claims"', 'id="limitations"', 'class="cs-body pv-body"'):
        assert sid in page, sid
    assert ('<ol class="pv-toc"><li><a href="#C1"><span class="pv-toc-id">C1</span> The term depends on the ratio'
            in page)
    record = site.claimset_page(doc, base_url=BASE, listing=listing)
    assert '<a href="/p/2026.000099" aria-current="page"' in record and 'href="/p/2026.000099/paper"' in record
    old = site.claimset_page(doc, base_url=BASE, listing=listing + [{"version": 2}], current=2)
    assert "view-switch" not in old                                     # the paper view is of the current version


def test_written_with_the_claimset(tmp_path):
    doc = proofs()
    site.write_claimset(tmp_path, BASE, "2026.000099", {1: doc}, [{"version": 1, "date": "2026-11-17"}], {})
    written = (tmp_path / "p" / "2026.000099" / "paper.html").read_text(encoding="utf-8")
    assert 'class="pv-claim" id="C3"' in written


def test_the_example_of_the_format():
    if NATIVE is None:
        return
    doc = copy.deepcopy(NATIVE)
    doc["paper"].update({"id": "entrylib:2026.000098", "version": 1, "date": "2026-11-17"})
    page = site.paper_page(doc, base_url=BASE, listing=[{"version": 1}])
    assert 'class="pv-claim" id="C2"' in page and 'id="C1"' in page     # C1, an assumption, in Assumptions
    assert page.index('id="claims"') < page.index('id="assumptions"')
