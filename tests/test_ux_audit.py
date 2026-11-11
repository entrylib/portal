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
    assert any(f'<span class="score-band">{w}</span>' in page for w in score_html.BANDS.values())
    assert 'class="dot-legend small">Dots, in order:' in page
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


def test_skip_link_and_copy_the_whole_paper(env):
    _, page = page_of(env)
    assert '<a class="skip-link" href="#content">Skip to content</a>' in page and '<main id="content">' in page
    assert f'data-copy-url="/p/{KEY}@v1.txt"' in page and "Copy the whole paper instead" in page
    assert re.search(r'<a class="button-quiet" href="/p/2026\.000001@v1\.txt"', page)    # works without the script


def test_read_is_newest_first_and_search_counts():
    q = read.Query.parse({})
    assert q.sort == "newest" and "sort=" not in q.url()
    assert read.Query.parse({"sort": "reliability"}).url().endswith("sort=reliability")
    found = site.search_page("x", "claims", {"results": [{"paper": "entrylib:2026.000001", "claim": "C1",
                                                         "statement": "$a$", "version": 1}]})
    assert "1 claim</p>" in found and "<math" in found
    assert 'href="/all">browse all claimsets</a>' in site.search_page("x", "papers", {"results": []})


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
    assert page.index("Submit a claimset</h1>") < page.index("Waiting for your confirmation")
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
