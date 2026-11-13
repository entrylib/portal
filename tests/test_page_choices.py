"""What the page view shows and what the site decides through it (portal/page.py, moved from claimset.html): an
agent's label, people drawn the site's way, markers, claim pages, bylines, blocks, the summary first, small fixes."""

import copy
import json
import re
import unittest
from importlib import resources

from portal import page as html

EXAMPLES = resources.files("claimset") / "data" / "examples"
NATIVE = json.loads((EXAMPLES / "submission-native.json").read_text("utf-8"))
LAB = json.loads((EXAMPLES / "submission-from-lab.json").read_text("utf-8"))
TEXT = "Method M forecasts UK retail sales better than the seasonal naive benchmark, with error $e_t$ lower by a tenth."


def with_people(**changes):
    """The native example with its agent (P1) and person (P2) changed."""
    d = copy.deepcopy(NATIVE)
    for c in d["contributors"]:
        c.update(changes.get(c["id"], {}))
    return d


def doc(**paper):
    d = copy.deepcopy(NATIVE)
    d["paper"].update(paper)
    return d


class TestPeople(unittest.TestCase):
    def test_the_page_view_gives_the_label(self):
        header = html.render_parts(with_people(P1={"name": "Claude Code", "label": "drafting"}))["header"]
        authors = re.search(r'<p class="cs-authors">.*?</p>', header, re.S).group(0)
        self.assertIn('Claude Code <span class="cs-label">· drafting</span> (AI agent)', authors)
        plain = html.render_parts(with_people(P1={"name": "Claude Code"}))["header"]
        self.assertNotIn("cs-label", plain)

    def test_a_site_shows_people_its_own_way(self):
        """render_parts(person=…): the site draws each person and agent in the header; None keeps the default."""
        seen = []

        def person(c, where):
            seen.append((c.get("id"), where))
            return f'<b class="who">{html.esc(c.get("name"))}</b>' if c.get("type") == "agent" else None
        header = html.render_parts(with_people(P1={"name": "Claude <x>"}), person=person)["header"]
        self.assertIn('Authors: <b class="who">Claude &lt;x&gt;</b>', header)
        self.assertIn('orcid-verified', header)                               # the guarantor: the default
        self.assertEqual(sorted(seen), [("P1", "author"), ("P2", "guarantor")])


class TestSiteChoices(unittest.TestCase):
    """What a site decides through render_parts: what marks a claim, a claim's own page, how sections are arranged."""

    def test_marker_and_claim_url(self):
        parts = html.render_parts(LAB, marker=lambda c, where: ("<b>S</b>", " · after") if where == "claim" else "<i>s</i>",
                                  claim_url=lambda cid: f"/p/x/{cid}" if cid == "C2" else "javascript:x")
        c2 = re.search(r'<div class="cs-item cs-claim[^"]*" id="C2"><p class="cs-claim-meta">(.*?)</p>', parts["body"])
        self.assertTrue(c2.group(1).startswith('<b>S</b><a class="cs-claim-page" href="/p/x/C2">C2</a>'))
        self.assertTrue(c2.group(1).endswith(" · after"))
        self.assertNotIn("javascript:", parts["body"])                       # only safe addresses are linked
        self.assertNotIn('class="light light-', re.search(r'<ul class="cs-brief">.*?</ul>', parts["body"], re.S).group(0))
        default = html.render_parts(LAB)["body"]
        self.assertIn('class="light light-', default)                        # without a marker: the lights

    def test_byline(self):
        seen = []

        def byline(role, people):
            seen.append((role, [c["id"] for c in people]))
            return "Responsible: X" if role == "guarantor" else None

        header = html.render_parts(NATIVE, byline=byline)["header"]
        self.assertIn('<p class="cs-guarantor">Responsible: X</p>', header)
        self.assertIn('<p class="cs-authors">Authors: ', header)              # None: the package's words
        self.assertEqual([r for r, _ in seen], ["guarantor", "authors"])
        self.assertEqual(html.render_parts(NATIVE)["header"],
                         html.render_parts(NATIVE, byline=lambda role, people: None)["header"])
        self.assertEqual(html.render_parts(NATIVE)["header"], html.render_parts(NATIVE, byline="x")["header"])

    def test_blocks(self):
        parts = html.render_parts(LAB)
        self.assertEqual(list(parts["blocks"]), [sid for sid, _, _ in parts["sections"]])
        self.assertEqual("\n".join(parts["blocks"].values()), parts["body"])

    def test_vocabularies_in_words(self):
        body = html.render_parts(LAB)["body"]
        self.assertNotRegex(body, r"\bdata_type:|Verdict:|code_changed_after_plan|planned \d{4}-\d\d-\d\dT")
        self.assertIn("Outcome:</span> computed from the recorded results", body)
        self.assertEqual(html._date("2026-11-05T11:37:01Z"), "5 November 2026")
        self.assertEqual(html._date("soon"), "soon")


class TestSummary(unittest.TestCase):
    def test_page_view_puts_it_first_then_the_highlights(self):
        parts = html.render_parts(doc(summary=TEXT))
        page = parts["body"]
        self.assertIn('<p class="cs-summary">', page)
        self.assertIn("<math", page.split('<p class="cs-summary">')[1].split("</p>")[0])
        self.assertEqual([s[0] for s in parts["sections"]][:2], ["summary", "highlights"])
        self.assertLess(page.index('id="summary"'), page.index('id="highlights"'))
        self.assertIn('class="cs-brief"', page.split('id="highlights"')[1].split("</section>")[0])
        plain = html.render_parts(NATIVE)
        self.assertNotIn('id="summary"', plain["body"])                    # no summary: it starts with Highlights
        self.assertEqual(plain["sections"][0][:2], ("highlights", "Highlights"))
        self.assertNotIn("<b>", html.render_parts(doc(summary="<b>x</b>"))["body"].split('cs-summary">')[1][:20])


class TestSmallFixes(unittest.TestCase):
    def test_a_highlighted_definition_is_tagged(self):
        brief = html.render_parts(NATIVE)["blocks"]["highlights"]          # highlights C2 and the definition D2
        self.assertIn('<li class="cs-brief-term"><span class="kind-tag">Definition</span>', brief)
        self.assertEqual(brief.count("kind-tag"), 1)                        # only the definition

    def test_a_tooltip_shows_maths_as_characters(self):
        tip = html._first_sentence("The error $\\epsilon_t \\sim N(0, \\sigma^2)$ of [[D2:the model]]. More.")
        self.assertEqual(tip, "The error ϵt∼N(0,σ2) of the model.")

    def test_an_artefact_links_its_file_not_its_description(self):
        d = copy.deepcopy(NATIVE)
        d["artefacts"] = [{"id": "A9", "kind": "code", "description": "The code that runs every forecast",
                           "uri": "https://github.com/x/y/blob/main/model.R"}]
        body = html.render_parts(d)["body"]
        self.assertIn('The code that runs every forecast <a class="cs-open" '
                      'href="https://github.com/x/y/blob/main/model.R">model.R</a>', body)
        self.assertEqual(html._link_name("https://zenodo.org/"), "zenodo.org")
