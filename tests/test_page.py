"""The page view (portal/page.py, moved from claimset.html): order, lights, Highlights, terms, references, maths,
images, escaping."""

import contextlib  # noqa: F401
import copy
import io  # noqa: F401
import json
import re
import tempfile  # noqa: F401
import unittest
from importlib import resources
from pathlib import Path

from portal import page as H

EXAMPLES = Path(str(resources.files("claimset") / "data" / "examples"))


def example(name="submission-native.json"):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def claim(cid, role="principal", typ="descriptive", kind="argument", statement=None, **extra):
    c = {"id": cid, "type": typ, "role": role, "statement": statement or f"Statement {cid} about forecasting.",
         "support": [{"kind": kind}]}
    c.update(extra)
    return c


class TestWholeFiles(unittest.TestCase):
    def test_every_example_and_compat_file_renders(self):
        files = sorted(EXAMPLES.glob("*.json"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(f.name):
                page = H.render_html(json.loads(f.read_text(encoding="utf-8")))
                self.assertTrue(page.startswith("<!doctype html>"))
                self.assertNotIn("<script", page)

    def test_section_order(self):
        doc = example()
        doc["references"] = [{"id": "B1", "target": "Smith, J. (2020). A paper. Journal.", "id_type": "reference"}]
        doc["claims"][2]["relations"] = [{"type": "extends", "reference": "B1", "note": "Earlier result."}]
        doc["limitations"][0]["affects"] = ["C2"]
        body = H.render_parts(doc)["body"]
        order = ["highlights", "context", "definitions", "assumptions", "principal", "evidence", "limitations",
                 "references", "artefacts"]
        positions = [body.index(f'id="{s}"') for s in order]
        self.assertEqual(positions, sorted(positions))


class TestEscaping(unittest.TestCase):
    def test_submitted_text_is_never_markup(self):
        doc = example()
        doc["paper"]["title"] = "<script>alert(1)</script>"
        doc["claims"][2]["statement"] = 'Rises <img src=x onerror="alert(1)"> and [[D1:<b>term</b>]].'
        doc["definitions"][0]["definition"] = '"><script>bad()</script>'
        page = H.render_html(doc)
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<b>term</b>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_only_http_links_from_the_file(self):
        doc = example()
        doc["artefacts"][0]["uri"] = "javascript:alert(1)"
        page = H.render_html(doc)
        self.assertNotIn('href="javascript:', page)


class TestLights(unittest.TestCase):
    def setUp(self):
        self.doc = {"paper": {"title": "T"}, "claims": [
            claim("C1", kind="empirical_quant", verifiability="open"),
            claim("C2", kind="empirical_quant", verifiability="audit_only"),
            claim("C3", kind="argument", verifiability="open"),
            claim("C4", kind="unstated", verifiability="unverifiable"),
            {"id": "C5", "type": "descriptive", "role": "supporting", "statement": "Assumed.",
             "support": [{"kind": "assumption"}], "assumption_category": "statistical", "verifiability": "not_applicable"}]}

    def test_each_light(self):
        P = H._Paper(self.doc)
        self.assertEqual([P.light(c) for c in P.claims], ["green", "amber", "amber", "red", None])
        parts = H.render_parts(self.doc)
        self.assertEqual(parts["lights"], {"green": 1, "amber": 2, "red": 1})
        self.assertIn('aria-label="supported, not checkable"', parts["body"])


WORDS = ["Seasonal models reduce error on monthly retail series.", "The estimator is consistent under mixing.",
         "Damped trends forecast long horizons better than linear trends.", "Intervals are too narrow for short series.",
         "Combinations beat single methods on the tourism data.", "The smoothing parameter controls stationarity.",
         "Outliers inflate the mean scaled interval score.", "Selection by AICc picks seasonal models too often.",
         "Hourly data need multiple seasonal cycles."]


class TestBrief(unittest.TestCase):
    def doc(self, n, **paper):
        return {"paper": {"title": "T", "contributions": [f"C{i}" for i in range(1, n + 1)], **paper},
                "definitions": [{"id": "D1", "kind": "method", "term": "M", "definition": "A method."}],
                "claims": [claim(f"C{i}", typ=("formal" if i % 2 else "descriptive"), statement=WORDS[i - 1])
                           for i in range(1, n + 1)]}

    def test_highlights_first(self):
        ids, auto = H.brief(self.doc(8, highlights=["C3", "D1"]))
        self.assertEqual((ids, auto), (["C3", "D1"], False))
        body = H.render_parts(self.doc(8, highlights=["C3", "D1"]))["body"]
        self.assertIn("<strong>M</strong>: A method.", body)

    def test_five_or_fewer_all_shown(self):
        self.assertEqual(H.brief(self.doc(4)), (["C1", "C2", "C3", "C4"], False))

    def test_computed_choice(self):
        doc = self.doc(9)
        doc["claims"].append(claim("C10", role="supporting", depends_on=["C7"]))
        doc["claims"].append(claim("C11", role="supporting", depends_on=["C10"]))
        ids, auto = H.brief(doc)
        self.assertTrue(auto)
        self.assertEqual(len(ids), H.BRIEF_MAX)
        self.assertIn("C7", ids)                            # used, directly and through C10
        self.assertEqual(ids, sorted(ids, key=lambda x: int(x[1:])))
        self.assertIn("Selected automatically", H.render_parts(doc)["body"])

    def test_near_duplicates_skipped(self):
        doc = self.doc(7)
        doc["claims"][1]["statement"] = doc["claims"][0]["statement"]
        ids, _ = H.brief(doc)
        self.assertFalse({"C1", "C2"} <= set(ids))


class TestTermsReferencesMaths(unittest.TestCase):
    def test_terms_link_to_definitions(self):
        P = H._Paper({"paper": {}, "definitions": [{"id": "D1", "kind": "method", "term": "CES",
                                                     "definition": "Complex exponential smoothing. More."}]})
        self.assertEqual(P.text("[[D1:CES]] and [[D9:other]]"),
                         '<a class="term" href="#D1" title="CES: Complex exponential smoothing.">CES</a> and other')

    def test_author_year_labels(self):
        refs = [{"id": "B1", "id_type": "reference",
                 "target": "Hyndman, R. J., Koehler, A. B., Ord, J. K., & Snyder, R. D. (2008). Forecasting. Springer."},
                {"id": "B2", "id_type": "reference", "target": "Kolassa, S. (2011). Combining. IJF, 27(2)."},
                {"id": "B3", "id_type": "reference", "target": "Petropoulos, F., & Svetunkov, I. (2020). A simple combination."},
                {"id": "B4", "id_type": "reference", "target": "Kolassa, S. (2011). Another. IJF."},
                {"id": "B5", "id_type": "doi", "target": "10.1002/nav.22074"}]
        P = H._Paper({"paper": {}, "references": refs})
        self.assertEqual(P.labels, {"B1": "Hyndman et al. (2008)", "B2": "Kolassa (2011a)",
                                    "B3": "Petropoulos and Svetunkov (2020)", "B4": "Kolassa (2011b)",
                                    "B5": "doi:10.1002/nav.22074"})

    def test_references_link_back(self):
        doc = example()
        doc["references"] = [{"id": "B1", "target": "Smith, J. (2020). A paper.", "id_type": "reference"}]
        doc["definitions"][0]["source"] = "B1"
        body = H.render_parts(doc)["body"]
        self.assertIn('Source: <a class="ref" href="#B1">Smith (2020)</a>', body)
        self.assertIn('Used by: <a href="#D1">D1</a>', body)

    def test_maths_and_code(self):
        P = H._Paper({"paper": {}})
        out = P.text("when $\\alpha_1 < 1$ holds, `adam(y, model = \"ANN\")` fits $x")
        self.assertIn("<math><semantics><mrow><msub><mi>α</mi><mn>1</mn></msub><mo>&lt;</mo><mn>1</mn></mrow>", out)
        self.assertIn('<code class="cs-code">adam(y, model = &quot;ANN&quot;)</code>', out)
        self.assertNotIn("`", out)
        self.assertIn("fits $x", out)                            # not a formula: no closing $
        self.assertIn('<code class="math-tex">\\foo{x}</code>', P.text("$\\foo{x}$"))   # unread: shown as written
        self.assertIn('<math display="block">', P.text("$$x^2$$"))
        self.assertNotIn('display="block"', P.text("so $V_h = \\frac{T}{T-k} c_h$ holds"))  # $…$: in the sentence
        self.assertIn('<math display="block">', P.text("so $$V_h = \\frac{T}{T-k} c_h$$ holds"))
        self.assertIn("<math><semantics>", P.text("$\\epsilon_t \\sim N(0, \\sigma^2)$"))      # $…$: in the line
        self.assertIn('<math display="block">', P.text("$$y_t = w^\\top v_{t-1} + \\epsilon_t$$"))    # $$…$$: displayed
        self.assertIn("<math><semantics>", P.text("at $T$ of 100"))                       # short: in the line
        # the punctuation after a formula in a sentence stays with it: a formula does not break across lines
        self.assertIn('</math>.</span> Next', P.text("shrinks like $1/\\sigma$. Next"))
        self.assertIn('<span class="cs-nw"><math>', P.text("shrinks like $1/\\sigma$. Next"))
        self.assertNotIn("cs-nw", P.text("at $T$ of 100"))
        out = P.text("where $$\\epsilon_t \\sim N(0, \\sigma^2)$$, and so on")        # its comma goes with it
        self.assertIn("<mo>,</mo></mrow><annotation", out)
        self.assertTrue(out.endswith("</math></span> and so on"))      # in its box (below)
        self.assertIn('<span class="cs-eq"><math display="block">', out)
        self.assertNotIn("<math>", P.text("`$x$` is code"))           # maths is not read inside code

    def test_a_site_writes_out_doi_references(self):
        doc = {"paper": {}, "claims": [claim("C1", support=None)],
               "references": [{"id": "B1", "id_type": "doi", "target": "10.1/a"},
                              {"id": "B2", "id_type": "doi", "target": "10.1/b"},
                              {"id": "B3", "id_type": "doi", "target": "10.1/unknown"}]}
        doc["claims"][0]["support"] = [{"kind": "cited", "references": ["B1", "B2"]}]
        written = {"10.1/a": "Svetunkov, I., & Petropoulos, F. (2018). Old dog, new tricks. IJPR.",
                   "10.1/b": "Svetunkov, I., & Petropoulos, F. (2018). Another. IJF."}
        parts = H.render_parts(doc, ref_text=lambda b: written.get(b["target"]))
        P = H._Paper(doc, ref_text=lambda b: written.get(b["target"]))
        self.assertEqual(P.labels, {"B1": "Svetunkov and Petropoulos (2018a)", "B2": "Svetunkov and Petropoulos (2018b)",
                                    "B3": "doi:10.1/unknown"})
        self.assertIn("Old dog, new tricks. IJPR.", parts["body"])
        self.assertIn('href="https://doi.org/10.1/a"', parts["body"])


    def test_references_are_listed_by_author_and_a_cited_claimset_by_its_guarantor(self):
        doc = {"paper": {}, "claims": [claim("C1", support=None)],
               "references": [{"id": "B1", "id_type": "reference", "target": "Zhang, W. (2020). Last. Journal."},
                              {"id": "B2", "id_type": "claimset", "target": "entrylib:2026.000008@v2#C33"},
                              {"id": "B3", "id_type": "claimset", "target": "entrylib:2026.000009@v1#C5"},
                              {"id": "B4", "id_type": "claimset", "target": "entrylib:2026.000008@v2#C6"},
                              {"id": "B5", "id_type": "doi", "target": "10.1/unknown"},
                              {"id": "B6", "id_type": "reference", "target": "Armstrong, J. S. (1985). First. Wiley."},
                              {"id": "B7", "id_type": "claimset", "target": "entrylib:2026.000777#C1"}]}
        doc["claims"][0]["support"] = [{"kind": "cited", "references": ["B2", "B3"]}]
        written = {"entrylib:2026.000008@v2#C33": "Svetunkov, I. (2026). Evaluating forecasts. EntryLib.",
                   "entrylib:2026.000008@v2#C6": "Svetunkov, I. (2026). Evaluating forecasts. EntryLib.",
                   "entrylib:2026.000009@v1#C5": "Svetunkov, I. (2026). Which forecast. EntryLib."}

        def ref_text(b):
            return written.get(b["target"])
        P = H._Paper(doc, ref_text=ref_text)
        # one claimset, one label, each claim named after it; a second claimset of the same year takes the next letter
        self.assertEqual(P.labels["B2"], "Svetunkov (2026a), C33")
        self.assertEqual(P.labels["B4"], "Svetunkov (2026a), C6")
        self.assertEqual(P.labels["B3"], "Svetunkov (2026b), C5")
        self.assertEqual(P.labels["B7"], "entrylib:2026.000777#C1")           # not published here: as it was
        self.assertEqual([b["id"] for b in P.refs_in_order()], ["B6", "B4", "B2", "B3", "B1", "B5", "B7"])
        body = H.render_parts(doc, ref_text=ref_text)["body"]
        refs = body.split('<ol class="cs-refs">')[1].split("</ol>")[0]
        # a claimset published here is one entry, whatever the number of its claims cited: the work once, then the
        # claims, each a link; the entry answers to each reference's ID
        self.assertEqual(re.findall(r'<li id="(B\d)"', refs), ["B6", "B4", "B3", "B1", "B5", "B7"])
        self.assertEqual(refs.count("Evaluating forecasts"), 1)
        self.assertIn('<li id="B4"><span id="B2"></span>Svetunkov, I. (2026). Evaluating forecasts. EntryLib. '
                      '<a class="global-id" href="/p/2026.000008@v2">entrylib:2026.000008@v2</a> '
                      '<span class="cs-cited">Claims cited: <a href="/p/2026.000008@v2#C6">C6</a>, '
                      '<a href="/p/2026.000008@v2#C33">C33</a>.</span></li>', refs)
        self.assertIn('<span class="cs-cited">Claim cited: <a href="/p/2026.000009@v1#C5">C5</a>.</span>', refs)
        self.assertEqual(P.ref("B2"), '<a class="ref" href="#B2">Svetunkov (2026a), C33</a>')   # where it is cited
        # an entry is written as a classical list has it: no label before it, the year with the label's letter,
        # a DOI by its address
        self.assertIn('<li id="B5"><a href="https://doi.org/10.1/unknown">https://doi.org/10.1/unknown</a>', refs)
        self.assertNotIn('<span class="cs-id">', refs)
        classical = {"B1": "Hyndman, R.J., Koehler, A.B., 2006. Another look. IJF 22, 679–688.",
                     "B2": "Hyndman, R.J., Koehler, A.B., 2006. A second look. IJF 22, 700–710."}
        both = {"paper": {}, "claims": [], "references": [{"id": k, "id_type": "doi", "target": f"10.1/{k}"}
                                                          for k in classical]}
        listed = H._Paper(both, ref_text=lambda r: classical[r["id"]])
        self.assertEqual(listed.labels, {"B1": "Hyndman and Koehler (2006a)", "B2": "Hyndman and Koehler (2006b)"})
        shown = H.render_parts(both, ref_text=lambda r: classical[r["id"]])["body"]
        self.assertIn("Hyndman, R.J., Koehler, A.B., 2006a. Another look.", shown)
        self.assertIn("Koehler, A.B., 2006b. A second look. IJF 22, 700–710. "
                      '<a href="https://doi.org/10.1/B2">https://doi.org/10.1/B2</a>', shown)
        alone = H._Paper({"paper": {}, "claims": [], "references": doc["references"][1:2]}, ref_text=ref_text)
        self.assertEqual(alone.labels["B2"], "Svetunkov (2026), C33")          # no letter without a second work


class TestImages(unittest.TestCase):
    def doc(self, uri):
        doc = example()
        doc["artefacts"].append({"id": "A9", "kind": "figure", "function": "data_plot", "uri": uri,
                                 "description": "Errors by horizon", "shows": ["E1"]})
        return doc

    def test_a_packaged_figure_is_shown_in_its_evidence(self):
        body = H.render_parts(self.doc("figures/errors.png"))["body"]
        ev = body[body.index('id="evidence"'):body.index('id="limitations"')]
        self.assertIn('<img src="figures/errors.png" alt="Errors by horizon" loading="lazy">', ev)

    def test_figures_come_before_the_numbers(self):
        """Design §7.6: an evidence object shows its figures before its results and tables, full width; with more than
        three, two to a row."""
        doc = self.doc("figures/errors.png")
        e = doc["evidence"][0]
        e["tables"] = [{"id": "T1", "description": "Errors", "row_labels": ["method"], "columns": ["MAE"],
                        "rows": [{"id": "r1", "label": ["M"], "values": [1.5]}]}]
        body = H.render_parts(doc)["body"]
        ev = body[body.index(f'id="{e["id"]}"'):]
        self.assertLess(ev.index("<img"), ev.index("<table"))
        self.assertIn('<div class="cs-figures">', ev)
        for i in range(10, 14):
            doc["artefacts"].append(dict(doc["artefacts"][-1], id=f"A{i}"))
        self.assertIn('<div class="cs-figures cs-figures-many">', H.render_parts(doc)["body"])

    def test_a_long_table_folds_all_but_its_first_rows_and_the_cited_ones(self):
        """Design §7.1: past 12 rows, rows after the 8th are marked to fold, except those a claim cites."""
        doc = example()
        e, c = doc["evidence"][0], doc["claims"][0]
        e["tables"] = [{"id": "T1", "description": "Errors", "row_labels": ["case"], "columns": ["MAE"],
                        "rows": [{"id": f"r{i}", "label": [f"case {i}"], "values": [i]} for i in range(1, 21)]}]
        c["support"] = [{"kind": "empirical_quant", "evidence": e["id"], "results": [f'{e["id"]}.T1.r15']}]
        body = H.render_parts(doc)["body"]
        eid = e["id"]
        self.assertIn(f'<div class="cs-table cs-table-long" id="{eid}.T1">', body)
        self.assertIn(f'<tr id="{eid}.T1.r8">', body)
        self.assertIn(f'<tr id="{eid}.T1.r9" class="cs-more">', body)
        self.assertIn(f'<tr id="{eid}.T1.r15">', body)                       # cited: stays in view
        self.assertIn('data-all="Show all 20 rows"', body)
        e["tables"][0]["rows"] = e["tables"][0]["rows"][:12]
        self.assertNotIn("cs-more", H.render_parts(doc)["body"])

    def test_the_site_gives_the_address(self):
        body = H.render_parts(self.doc("figures/errors.png"), file_url=lambda a: f"/files/{a['id']}.png")["body"]
        self.assertIn('<img src="/files/A9.png"', body)
        doc = self.doc("https://entrylib.org/files/0a1b")          # published: no extension; the site knows the type
        body = H.render_parts(doc, file_url=lambda a: "/img/0a1b.png" if a["id"] == "A9" else None)["body"]
        self.assertIn('<img src="/img/0a1b.png"', body)
        self.assertEqual(body.count("<img"), 1)

    def test_images_elsewhere_are_linked_not_embedded(self):
        for uri in ("https://example.org/fig.png", "../outside.png", "/etc/x.png"):
            with self.subTest(uri):
                body = H.render_parts(self.doc(uri))["body"]
                self.assertNotIn("<img", body)
        self.assertIn('href="https://example.org/fig.png"', H.render_parts(self.doc("https://example.org/fig.png"))["body"])

    def test_observation_records(self):
        doc = self.doc("images/gel.jpg")
        del doc["artefacts"][-1]["shows"]
        doc["evidence"][0]["records"] = [{"kind": "image", "artefact": "A9", "description": "Gel"}]
        self.assertIn('<img src="images/gel.jpg"', H.render_parts(doc)["body"])


class TestPlannedEstimates(unittest.TestCase):
    def test_a_planned_estimate_is_shown_as_planned(self):
        doc = example()
        c = claim("C9", role="secondary", planning="planned_estimate", planned_at="2026-11-12T10:00:00Z",
                  estimate={"estimands": {"m": {"variable": "MASE"}, "u": {"variable": "coverage"}},
                            "lab_plan": "PL3", "not_obtained": ["u"], "flags": ["diagnostic_missing"]})
        doc["claims"].append(c)
        body = H.render_parts(doc)["body"]
        self.assertIn("planned estimate", body)
        self.assertIn("lab plan PL3, planned 12 November 2026", body)
        self.assertIn("Not obtained:</span> u", body)
        self.assertIn("a run left out a check the plan required", body)


class TestDigits(unittest.TestCase):
    def doc(self):
        doc = example()
        e = doc["evidence"][0]
        e["estimate"] = 0.123456789
        e["tables"] = [{"id": "T1", "description": "Errors", "columns": ["MCE"],
                        "rows": [{"id": "r1", "values": [0.000680612]}, {"id": "r2", "values": [300]},
                                 {"id": "r3", "values": [0.5]}]}]
        return doc

    def test_rounded_when_asked(self):
        body = H.render_parts(self.doc(), digits=4)["body"]
        self.assertIn("= 0.1235", body)
        self.assertIn('<td class="num" title="0.000680612">0.0006806</td>', body)
        self.assertIn('<td class="num">300</td>', body)
        self.assertIn('<td class="num">0.5</td>', body)

    def test_exact_by_default_and_after(self):
        doc = self.doc()
        H.render_parts(doc, digits=4)
        body = H.render_parts(doc)["body"]
        self.assertIn("0.123456789", body)
        self.assertIn('<td class="num">0.000680612</td>', body)

    def test_rounding(self):
        from claimset.render import _rounded
        for v, want in [(1.00193, "1.002"), (12345.67, "12346"), (1.23456e-9, "0.000000001235"), (-3.14159, "-3.142"),
                        (0.30000000000000004, "0.3")]:
            self.assertEqual(_rounded(v, 4), want)


    def test_the_site_writes_numbers(self):
        def four_places(v):
            return None if isinstance(v, int) or v.is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")
        body = H.render_parts(self.doc(), number=four_places)["body"]
        self.assertIn("= 0.1235", body)
        self.assertIn('<td class="num" title="0.000680612">0.0007</td>', body)
        self.assertIn('<td class="num">300</td>', body)
        self.assertIn('<td class="num">0.5</td>', body)

    def test_a_failing_formatter_falls_back(self):
        def broken(v):
            raise ValueError
        body = H.render_parts(self.doc(), number=broken)["body"]
        self.assertIn('<td class="num">0.000680612</td>', body)
        body = H.render_parts(self.doc(), number=lambda v: 7)["body"]       # not text: the default
        self.assertIn('<td class="num">300</td>', body)

    def test_sections(self):
        parts = H.render_parts(self.doc())
        ids = [sid for sid, _, _ in parts["sections"]]
        self.assertEqual(ids[:1], ["highlights"])
        self.assertIn(("evidence", "Evidence", len(self.doc()["evidence"])), parts["sections"])
        for sid in ids:
            self.assertIn(f'href="#{sid}"', parts["nav"])


class TestOriginAndHeader(unittest.TestCase):
    def test_origins(self):
        self.assertEqual(H.render_parts(example())["origin"], "native")
        self.assertEqual(H.render_parts(example("submission-from-lab.json"))["origin"], "lab")
        conv = copy.deepcopy(example())
        conv["paper"]["converted_from"] = {"source_id": "10.1/x", "source_authors": [{"name": "A. B", "orcid": None}]}
        parts = H.render_parts(conv)
        self.assertEqual(parts["origin"], "converted")
        self.assertEqual(H.origin(conv), "converted")
        self.assertIn('href="https://doi.org/10.1/x"', parts["header"])

    def test_guarantor_orcid_is_the_verified_one(self):
        header = H.render_parts(example())["header"]
        self.assertIn('class="orcid orcid-verified"', header)


if __name__ == "__main__":
    unittest.main()


class TestCorrections(unittest.TestCase):
    """Where a claimset departs from what it restates (claimset spec §3.1): each corrected item says so and the page
    lists the corrections with their reasons."""

    def doc(self, where="published"):
        d = example()
        cid, did = d["claims"][0]["id"], d["definitions"][0]["id"]
        entries = [{"kind": "correction", "field": f"{cid}.statement", "where": "Section 3.3",
                    "printed": "growth for $\\alpha_1 > 1$", "recorded": "growth for $\\alpha_1 > 1$ and $\\alpha_0 < 2$",
                    "reason": "At $\\alpha_0 = 2.2$ the dominant eigenvalue is negative.",
                    "found_by": d["contributors"][0]["id"]},
                   {"kind": "misprint", "field": f"{did}.definition", "where": "Equation (4)",
                    "printed": "a <b>sum</b>", "recorded": "a squared sum", "reason": "the sum is of squares"}]
        if where == "published":
            d["paper"]["published_as"] = {"id_type": "doi", "id": "10.1002/nav.22074", "corrections": entries}
        else:
            d["paper"]["origin"] = "converted"
            d["paper"]["converted_from"] = {"source_id": "10.1/x", "corrections": [
                {k: v for k, v in e.items() if k not in ("kind", "found_by")} for e in entries]}
        return d, cid, did

    def test_published_paper_corrections_are_shown(self):
        d, cid, did = self.doc()
        parts = H.render_parts(d)
        self.assertIn("This claimset corrects the published paper in 2 places", parts["header"])
        claim_html = parts["body"].split(f'id="{cid}"', 1)[1].split("</div>", 1)[0]
        self.assertIn("Corrected from the published paper", claim_html)
        self.assertIn("correction by the authors, Section 3.3", claim_html)
        self.assertIn("<math", claim_html)                                    # the printed formula is typeset
        self.assertIn("Corrected from the published paper", parts["body"].split(f'id="{did}"', 1)[1].split("</div>", 1)[0])
        section = parts["blocks"]["corrections"]
        self.assertIn("Corrections to published paper", section)
        self.assertIn("found by " + d["contributors"][0]["name"], section)
        self.assertIn("Why:", section)
        self.assertNotIn("<b>sum</b>", section)                               # the paper's text is never HTML
        self.assertIn(("corrections", "Corrections to published paper", 2), parts["sections"])

    def test_a_converted_source_s_corrections_are_shown_too(self):
        d, cid, _ = self.doc("converted")
        parts = H.render_parts(d)
        self.assertIn("corrects the source paper in 2 places", parts["header"])
        self.assertIn("Corrected from the source paper", parts["body"])

    def test_nothing_without_corrections(self):
        parts = H.render_parts(example())
        self.assertNotIn("corrections", parts["blocks"])
        self.assertNotIn("Corrected from", parts["body"] + parts["header"])
