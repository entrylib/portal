"""The first round of fixes from the UX audit of 11 November 2026 (design §7.4, §7.6)."""

import re
from pathlib import Path

from publishing import BASE, example, write

from portal import read, score_html, site, text
from portal.publish import publish

KEY = "2026.000001"


def page_of(env, doc=None):
    ctx, tmp = env
    publish(write(tmp, doc or example()), **ctx)
    return ctx["published_dir"], (ctx["published_dir"] / "p" / f"{KEY}.html").read_text()


def test_the_score_says_what_it_measures(env):
    out, page = page_of(env)
    assert f"<h2>{score_html.NAME}</h2>" in page and score_html.CAPTION in page
    assert '<ul class="dot-list small">' in page and "dot-key" not in page        # named dots; no colour key
    panel = page.split('<aside class="panel"')[1].split("</aside>")[0]
    assert re.search(r'<p class="small score-why"><a href="#score" data-popup="score-paper">Why \d+\?</a></p>', panel)
    assert "Conflicts of interest</h2>" in panel and "principal claim" not in panel.split("score-why")[0]
    assert not any(f">{w}<" in page.split('<aside class="panel"')[1][:3000] for w in score_html.BANDS.values())
    assert "Issues as text, for an agent" in page.split('<h2>For models</h2>')[1]   # agent links in their row
    assert "no close match on EntryLib" not in page                     # says nothing while the library is small
    home = (out / "index.html").read_text()
    assert "Checks the record, not the science" not in home or "not peer review" in home
    assert "<h3>Read it yourself</h3>" in home and "<h3>Ask your AI</h3>" in home and "publish →" not in home


def test_maths_outside_the_page_view_is_rendered():
    assert "<math" in text.html("the error $\\epsilon_t$ is normal")
    assert text.readable("the error $\\epsilon_t$ is normal") == "the error ϵt is normal"
    box = site._notice_box("corrected", "2026-11-10", None, "correction", "The bound $x_t$ was wrong.")
    assert "<math" in box and "$x_t$" not in box
    retracted = site._notice_box("retracted", "2026-11-10", "EntryLib", "other", "Words $x$ of a requester.")
    assert "$x$" in retracted and "<math" not in retracted              # a request's words stay text only


def test_status_and_counts(env):
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    doc["warrants"] = [{"id": "W1", "text": "An argument.", "premises": []}]
    assert "1 piece of evidence and 1 argument" in site.card(doc) or "pieces of evidence and 1 argument" in \
        site.card(doc)
    assert site.STATUS_LABELS["corrected"] == "updated" and site.STATUS_CLASS["corrected"] == "neutral"


def test_skip_link_and_no_copy_of_the_whole_paper(env):
    """A paper can be too long to paste into an assistant: the page offers only the message with its link (UX
    re-check, 12 November 2026); the reading view stays linked under For models."""
    _, page = page_of(env)
    assert '<a class="skip-link" href="#content">Skip to content</a>' in page and '<main id="content">' in page
    assert "data-copy-url" not in page and "Copy the whole" not in page
    assert f'href="/p/{KEY}@v1.txt"' in page


def test_read_is_newest_first_and_search_counts():
    q = read.Query.parse({})
    assert q.sort == "newest" and "sort=" not in q.url()
    assert read.Query.parse({"sort": "reliability"}).url().endswith("sort=reliability")
    found = site.search_page("x", "claims", {"results": [{"paper": "entrylib:2026.000001", "claim": "C1",
                                                         "statement": "$a$", "version": 1}]})
    assert "1 claim</p>" in found and "<math" in found
    assert 'href="/all">browse all papers</a>' in site.search_page("x", "papers", {"results": []})


def test_not_found_is_a_page_for_people_and_json_for_programs(app_client):
    r = app_client.get("/no/such/page", headers={"Accept": "text/html"})
    assert r.status_code == 404 and "We could not find that page" in r.text and 'action="/read"' in r.text
    r = app_client.get("/api/no-such", headers={"Accept": "text/html"})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    r = app_client.get("/no/such/page", headers={"Accept": "application/json"})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_labels_and_the_submit_page(app_client):
    assert "Confirm a submission" in app_client.get("/confirm").text
    page = app_client.get("/submit").text
    assert page.index("Publish a paper</h1>") < page.index("Waiting for your confirmation")
    assert '<p id="new_paper_row" hidden>' in page
    agents = app_client.get("/agents").text if app_client.get("/agents").status_code == 200 else ""
    assert not agents or 'data-copy="mcp-url"' in agents


def test_static_not_found_page(env):
    ctx, _ = env
    site.write_fixed(ctx["published_dir"], BASE)
    assert "We could not find that page" in (ctx["published_dir"] / "404.html").read_text()
    caddy = (Path(__file__).parent.parent / "deploy" / "Caddyfile").read_text()
    assert "handle_errors 404 {" in caddy and "rewrite * /404.html" in caddy


# Round 2 (design §7.4, §7.7)

def test_the_paper_page_says_what_it_is(env):
    out, page = page_of(env)
    assert site.INTRO_STRIP in page and 'href="/about#reading"' in page
    assert 'id="reading"' in (Path(site.__file__).parent / "static" / "pages" / "about.html").read_text()
    assert 'getElementById("intro-strip")' in (Path(site.__file__).parent / "static" / "page.js").read_text()
    top = page.split('<p class="entry-top">')[1].split("</p>")[0]
    assert re.fullmatch(r"Version 1 · \d{1,2} [A-Z][a-z]+ \d{4}( · .+)?", top), top          # words, not codes
    assert '<span class="badge-word">Support</span> ' in page


def test_the_byline_tells_people_from_tools():
    doc = example()
    people = doc["contributors"]
    line = site.byline("authors", people)
    agents = [c for c in people if c.get("type") == "agent"]
    humans = [c for c in people if c.get("type") != "agent"]
    assert ("Written with: " in line) == bool(agents) and ("Authors: " in line) == bool(humans)
    if agents and humans:
        assert line.index("Authors: ") < line.index("Written with: ")
    g = {"name": "A <b>Researcher</b>", "orcid": "0000-0002-1825-0097", "type": "human"}
    shown = site.byline("guarantor", [g])
    assert shown.startswith("Responsible researcher: ") and "<b>" not in shown and "ORCID verified" in shown
    assert site.byline("source_authors", [g]) is None                   # the package's line for a source paper
    doc["paper"]["id"] = "entrylib:2026.000001"
    header = site.render(doc)["header"]
    assert "Responsible researcher: " in header and "Guarantor: " not in header


# Round 3

def test_how_to_read_is_written_once():
    assert site.HOW_TO_READ in site.INTRO_STRIP and 'data-help="how-to-read"' in site.INTRO_STRIP
    assert site.HOW_TO_READ in site.fixed_page("about", BASE) and "{how_to_read}" not in site.fixed_page("about", BASE)
    assert 'a[data-help]' in (Path(site.__file__).parent / "static" / "page.js").read_text()


def test_cards_say_how_an_entry_was_made_in_words():
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    top = site.card(doc).split('<p class="card-top">')[1].split("</p>")[0] if 'class="card-top"' in site.card(doc) \
        else site.card(doc)
    assert any(f'<span class="origin">{w}</span>' in top for w in site.ORIGIN_WORDS.values())
    assert "10 November 2026" in top and "entrylib:2026.000001 ·" not in top


def test_about_names_the_guarantor_and_who_runs_it():
    about = site.fixed_page("about", BASE)
    assert "responsible researcher" in about and '"Guarantor" is the format' in about
    assert 'id="governance"' in about and "runs it personally" in about


def test_the_two_new_pages():
    caddy = (Path(__file__).parent.parent / "deploy" / "Caddyfile").read_text()
    for name in ("how-to-judge", "before-you-submit"):
        page = site.fixed_page(name, BASE)
        assert "{" not in page.split("<main")[1].split("</main>")[0].replace("{ ", "")  # every placeholder filled
        assert f"/{name}" in site.SITEMAP_PAGES and f" /{name} " in caddy
    assert "nothing on EntryLib is peer review" in site.fixed_page("how-to-judge", BASE)
    assert "within 48 hours" in site.fixed_page("before-you-submit", BASE)


# Summaries and the convert page

def test_a_summary_leads_the_card_and_the_description():
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active",
                         "summary": "Method  M forecasts\nbetter, with error $e_t$ lower."})
    card = site.card(doc)
    assert 'class="card-claim card-summary"' in card and "<math" in card
    assert site._lead_text(doc) == "Method M forecasts better, with error et lower."
    del doc["paper"]["summary"]
    assert "card-summary" not in site.card(doc)


def test_the_convert_page():
    page = site.fixed_page("convert", BASE)
    assert 'id="convert-prompt"' in page and 'data-copy="convert-prompt"' in page and "page.js" in page
    assert "claimset-from-paper" in page and "Only the paper's authors" in page
    caddy = (Path(__file__).parent.parent / "deploy" / "Caddyfile").read_text()
    assert "/convert" in site.SITEMAP_PAGES and " /convert " in caddy
    assert 'href="/convert"' in (Path(site.__file__).parent / "static" / "pages" / "home.html").read_text()


# Round 5: vocabulary, headline, the rest of the audit

def test_one_word_for_what_readers_see():
    pages = Path(site.__file__).parent / "static" / "pages"
    for name in ("about.html", "home.html", "how-to-judge.html", "removal.html", "privacy.html"):
        text = (pages / name).read_text().replace("machine-readable entries", "")
        words = re.findall(r"\b(?:entry|entries|study|studies)\b", text, flags=re.I)
        assert not words, (name, words)                  # "entries" lives on only in the library's name
    assert 'for v, label in (("claimsets", "Papers")' in Path(read.__file__).read_text()
    home = (pages / "home.html").read_text()
    assert "<h1>Research papers you can check claim by claim</h1>" in home and 'class="home-score"' not in home


def test_the_contents_count_evidence_and_arguments_apart():
    doc = example()
    doc["warrants"] = [{"id": "W1"}]
    nav = site.contents([("evidence", "Evidence", 3), ("claims", "Claims", 4)], doc=doc)
    assert '<span class="count">2 · 1 argument</span>' in nav and '<span class="count">4</span>' in nav
    assert '<span class="count">3</span>' in site.contents([("evidence", "Evidence", 3)])


def test_about_has_a_glossary_preservation_and_the_early_stage():
    about = site.fixed_page("about", BASE)
    assert 'id="glossary"' in about and "<dt>Argument (W1, W2…)</dt>" in about
    assert "would not be lost" in about and "EntryLib is new." in about
    assert "<strong>Funding.</strong> EntryLib has no funding yet" in about        # who pays, and what if it closes
    assert "Only the address entrylib.org would stop working" in about
    assert 'href="/about#glossary"' in site.INTRO_STRIP
    assert "examples/submission-native.json" in site.fixed_page("before-you-submit", BASE)


def test_summary_and_highlights_stay_open():
    js = (Path(site.__file__).parent / "static" / "page.js").read_text()
    assert "summary: true, highlights: true, brief: true" in js           # brief: older claimset releases
    assert "<strong>Summary</strong>" in site.HOW_TO_READ and "<strong>Highlights</strong>" in site.HOW_TO_READ


# The paper page from the package's blocks: order and names are the site's

def _parts(**blocks):
    sections = [(sid, title, 0) for sid, (title, _) in blocks.items()]
    return {"blocks": {sid: f'<section class="cs-section" id="{sid}"><h2>{t}</h2>{body}</section>'
                       for sid, (t, body) in blocks.items()}, "sections": sections, "body": "unused"}


def test_the_page_takes_its_order_and_names_from_the_site():
    doc = example()
    parts = _parts(evidence=("Evidence", "E"), highlights=("Highlights", "H"), summary=("Summary", "S"),
                   brandnew=("Something new", "N"))
    body, shown = site.page_sections(parts, doc)
    assert [s[0] for s in shown] == ["summary", "highlights", "evidence", "brandnew"]
    assert body.index('id="summary"') < body.index('id="highlights"') < body.index('id="evidence"')
    assert "<h2>Something new</h2>" in body                              # the package's title when the site has none


def test_an_older_package_gets_the_same_page():
    doc = example()
    doc["paper"]["summary"] = "In plain words, with $x_t$."
    old = _parts(brief=("In brief", '<ul class="cs-brief"><li>C1</li></ul>'), context=("Context", "X"))
    body, shown = site.page_sections(old, doc)                           # claimset 0.41.9: In brief, no summary
    assert [s[:2] for s in shown] == [("summary", "Summary"), ("brief", "Highlights"), ("context", "Context")]
    assert "<h2>Highlights</h2>" in body and "<h2>In brief</h2>" not in body and "<math" in body
    replaced = _parts(brief=("In brief", '<p class="cs-summary">S</p>'))  # claimset 0.41.10-11: summary In brief
    body, shown = site.page_sections(replaced, doc)
    assert [s[0] for s in shown] == ["summary"] and body.count("cs-summary") == 1
    del doc["paper"]["summary"]
    body, shown = site.page_sections(_parts(brief=("In brief", "<ul></ul>")), doc)
    assert [s[:2] for s in shown] == [("brief", "Highlights")] and 'id="summary"' not in body


def test_a_real_page_starts_with_its_summary_or_its_highlights(env):
    doc = example()
    doc["paper"]["summary"] = "In plain words."
    _, page = page_of(env, doc)
    body = page.split('<article class="cs-body">')[1]
    assert body.startswith('<section class="cs-section" id="summary">') and "In brief" not in body
    if "<h2>Highlights</h2>" in body:                   # claimset 0.41.10-11 put the summary in their place
        assert body.index('id="summary"') < body.index("<h2>Highlights</h2>")


def test_a_page_without_a_summary_starts_with_its_highlights(env):
    _, page = page_of(env, example())
    assert page.split('<article class="cs-body">')[1].startswith('<section class="cs-section" id="')
    assert 'id="summary"' not in page and "<h2>Highlights</h2>" in page


def test_novelty_opens_its_explanation(env):
    _, page = page_of(env)
    panel = page.split('<aside class="panel"')[1].split("</aside>")[0]
    assert 'data-help="novelty-help" data-title="Novelty">What is this?</a>' in panel
    tpl = panel.split('<template id="novelty-help">')[1].split("</template>")[0]
    assert "It is their own account." in tpl and '<ul class="novelty-list"><li><strong>' in tpl
    assert 'href="#C' in tpl and "<h2>Novelty</h2>" in tpl
    assert 'a.getAttribute("data-title")' in (Path(site.__file__).parent / "static" / "page.js").read_text()


# Pages agree with each other (12 November 2026)

def test_a_paper_its_authors_prepared_says_so():
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    assert "Written as a claimset" in site.card(doc) or "Made with the lab" in site.card(doc)
    doc["artefacts"] = list(doc.get("artefacts") or []) + [
        {"id": "AR99", "kind": "manuscript", "uri": "https://doi.org/10.1/x", "description": "The article, 2025"}]
    if site.pageview.origin(doc) == "native":
        assert "Converted by its authors" in site.card(doc)
        line = site._origin_line(doc, "native", None)
        assert ('Converted by its authors from their paper: <a href="https://doi.org/10.1/x">The article, 2025</a>'
                in line)
    assert site.own_paper({"artefacts": [{"kind": "manuscript", "uri": "doi:10.1/y"}]})[0] == "https://doi.org/10.1/y"


def test_the_pages_agree():
    pages = Path(site.__file__).parent / "static" / "pages"
    lab, about = (pages / "lab.html").read_text(), (pages / "about.html").read_text()
    assert '<span class="origin">lab</span>' not in lab and "Made with the lab" in lab
    assert "mean of its principal claims" in about and "scores as its\nlowest" not in about
    judge = (pages / "how-to-judge.html").read_text()
    assert "Converted by its authors" in about and "Converted by its authors" in judge
    assert "conversion guarantor" not in (pages / "how-to-judge.html").read_text()
    assert "conversion guarantor" not in site._origin_line({"paper": {}, "artefacts": []}, "converted", None)
