"""The website (design §7.4): pages written at publication and at start, citations, images, search, escaping."""

import json
import re

from publishing import BASE, example, write

from portal import indexer, site
from portal.publish import publish

KEY = "2026.000001"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def published(env, doc=None):
    ctx, tmp = env
    concept, _ = publish(write(tmp, doc or example()), **ctx)
    return ctx, concept


def test_claimset_page(env):
    ctx, concept = published(env)
    out = ctx["published_dir"]
    page = (out / "p" / f"{KEY}.html").read_text()
    assert page == (out / "p" / f"{KEY}@v1.html").read_text()
    assert page.count("<script src=") == 1 and page.count("<script") == 2          # the script, and JSON-LD data
    assert 'src="/page.js?v=' in page and 'class="cs-page entry"' in page
    assert 'href="/site.css?v=' in page and 'href="/claimset.css?v=' in page
    for part in ("Written directly as a claimset.", f"{concept}@v1", 'id="versions"',
                 '<a href="#versions">Versions</a>', f'href="/p/{KEY}@v1.bib"', f'href="/p/{KEY}@v1.ris"',
                 f'href="/p/{KEY}@v1.txt"', 'type="application/json"', "Support"):
        assert part in page, part
    bib = (out / "p" / f"{KEY}.bib").read_text()
    assert bib.startswith("@misc{entrylib2026.000001v1,") and f"{BASE}/p/{KEY}@v1" in bib
    ris = (out / "p" / f"{KEY}@v1.ris").read_bytes()
    assert ris.startswith(b"TY  - GEN\r\n") and ris.endswith(b"ER  - \r\n")


def test_listings_and_feed(env):
    ctx, concept = published(env)
    out = ctx["published_dir"]
    home = (out / "index.html").read_text()
    assert "Research papers you can check claim by claim" in home and f'href="/p/{KEY}"' in home
    assert "an open library of research papers written for people and AI" in home
    assert 'action="/read"' in home and "Recently published" in home
    assert f'href="/p/{KEY}"' in (out / "all.html").read_text()
    sitemap = (out / "sitemap.xml").read_text()
    assert sitemap.startswith("<?xml") and f"<loc>{BASE}/p/{KEY}</loc>" in sitemap
    assert f"<loc>{BASE}/read</loc>" in sitemap
    feed = (out / "feed.xml").read_text()
    assert feed.startswith('<?xml') and f"<id>{BASE}/p/{KEY}@v1</id>" in feed


def test_fixed_pages_and_assets_at_start(env):
    ctx, _ = env
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.40.1")
    for name in ("lab", "about", "agents", "privacy"):
        page = (out / f"{name}.html").read_text()
        assert page.startswith("<!doctype html>") and "{base}" not in page, name
        assert ("<script" in page) == (name in ("agents", "lab")), name       # their copy buttons
    assert "This website was created by Claude Opus 5.5." in (out / "about.html").read_text()
    assert f"{BASE}/mcp" in (out / "agents.html").read_text()
    assert (out / "site.css").exists() and ".cs-toc" in (out / "claimset.css").read_text()
    assert (out / "fonts" / "fonts.css").exists() and (out / "img" / "orcid.svg").exists()
    assert (out / "spec" / "claimset.md").exists() and "Specifications" in (out / "spec" / "index.html").read_text()
    assert (out / "index.html").exists()                    # the home page, before anything is published
    for icon in ("favicon.ico", "favicon.svg", "apple-touch-icon.png", "icon-192.png", "icon-512.png",
                 "site.webmanifest"):
        assert (out / icon).exists(), icon
    about = (out / "about.html").read_text()
    assert 'class="logo-mark"' in about and 'rel="icon" href="/favicon.svg"' in about and 'rel="manifest"' in about
    security = (out / ".well-known" / "security.txt").read_text()
    assert "Contact: mailto:mail@entrylib.org" in security and "Expires: " in security
    assert f"Sitemap: {BASE}/sitemap.xml" in (out / "robots.txt").read_text()


def test_pages_are_rebuilt_when_the_site_changes(env, monkeypatch):
    ctx, _ = published(env)
    out = ctx["published_dir"]
    args = (ctx["conn"], ctx["registry"], out, BASE, "0.40.1")
    assert indexer.refresh_if_claimset_changed(*args)
    assert not indexer.refresh_if_claimset_changed(*args)
    monkeypatch.setattr(site, "fingerprint", lambda: "changed")
    assert indexer.refresh_if_claimset_changed(*args)


def test_submitted_text_is_escaped(env):
    doc = example()
    doc["paper"]["title"] = 'M <img src=x onerror="alert(1)"> & co'
    ctx, _ = published(env, doc)
    out = ctx["published_dir"]
    for f in (out / "p" / f"{KEY}.html", out / "index.html", out / "all.html"):
        text = f.read_text()
        assert "<img src=x" not in text and "&lt;img src=x" in text, f.name
    assert "<img src=x" not in (out / "feed.xml").read_text()


def test_packaged_images_are_shown(env):
    ctx, tmp = env
    doc = example()
    doc["artefacts"].append({"id": "A9", "kind": "figure", "function": "data_plot", "uri": "figures/errors.png",
                             "description": "Errors by horizon", "licence": "CC-BY-4.0",
                             "availability": {"level": "public"}})
    for c in doc["claims"]:
        for s in c.get("support") or []:
            if s.get("evidence") == "E1":
                s["artefacts"] = s.get("artefacts", []) + ["A9"]
    folder = tmp / "pkg"
    (folder / "figures").mkdir(parents=True)
    (folder / "figures" / "errors.png").write_bytes(PNG)
    (folder / "paper.claimset.json").write_text(json.dumps(doc))
    from claimset.package import build
    build(str(folder / "paper.claimset.json"), str(tmp / "bag"))
    publish(tmp / "bag", **ctx)
    out = ctx["published_dir"]
    page = (out / "p" / f"{KEY}.html").read_text()
    assert f'<img src="/p/{KEY}/v1/files/figures/errors.png"' in page
    assert (out / "p" / KEY / "v1" / "files" / "figures" / "errors.png").read_bytes() == PNG
    assert not (out / "img").exists() or not list((out / "img").glob("*.png"))


def test_a_new_version_links_unchanged_files(env):
    ctx, tmp = env
    from portal.storage import FileStore
    store = FileStore(tmp / "pub", BASE)
    f = tmp / "a.png"
    f.write_bytes(PNG)
    _, url1 = store.put(f, KEY, 1, "figures/a.png")
    _, url2 = store.put(f, KEY, 2, "figures/a.png")
    assert url2 == f"{BASE}/p/{KEY}/v2/files/figures/a.png"
    assert store.path(KEY, 1, "figures/a.png").stat().st_ino == store.path(KEY, 2, "figures/a.png").stat().st_ino
    import pytest

    from portal.storage import StorageError
    for bad in ("../x.png", "/etc/passwd", "a/../../b", ""):
        with pytest.raises(StorageError):
            store.put(f, KEY, 1, bad)


def test_image_type_and_file_url(tmp_path):
    files = tmp_path / "p" / KEY / "v1" / "files"
    files.mkdir(parents=True)
    (files / "fig.svg").write_bytes(b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>")
    (files / "data.csv").write_bytes(b"col1,col2\n1,2\n")
    (files / "fake.png").write_bytes(b"col1,col2\n")
    url = site.file_url_for(tmp_path, BASE, legacy={"a" * 64: f"/p/{KEY}/v1/files/fig.svg"})
    assert url({"uri": f"{BASE}/p/{KEY}/v1/files/fig.svg"}) == f"/p/{KEY}/v1/files/fig.svg"
    assert url({"uri": f"{BASE}/files/{'a' * 64}"}) == f"/p/{KEY}/v1/files/fig.svg"      # an old address, moved
    assert url({"uri": f"{BASE}/p/{KEY}/v1/files/data.csv"}) is None                 # not an image
    assert url({"uri": f"{BASE}/p/{KEY}/v1/files/fake.png"}) is None                 # named an image, is not one
    assert url({"uri": "https://example.org/x.png"}) is None                         # not ours: linked, not shown
    assert url({"uri": f"{BASE}/p/{KEY}/v1/files/../../../../etc/passwd.png"}) is None


def test_legacy_files_move_into_their_claimset(env):
    """Files stored by checksum before (files/<sha256>) move to /p/<key>/v<n>/files/<id>.<ext>; the old address
    redirects."""
    ctx, tmp = env
    import hashlib

    from portal.indexer import reindex
    published = ctx["published_dir"]
    sha = hashlib.sha256(PNG).hexdigest()
    (published / "files").mkdir(parents=True)
    (published / "files" / sha).write_bytes(PNG)
    (published / "img").mkdir()
    (published / "img" / f"{sha}.png").write_bytes(PNG)
    doc = example()
    doc["artefacts"].append({"id": "A9", "kind": "figure", "function": "data_plot", "uri": "https://x/fig.png",
                             "description": "Errors", "licence": "CC-BY-4.0", "availability": {"level": "public"}})
    for c in doc["claims"]:
        for s in c.get("support") or []:
            if s.get("evidence") == "E1":
                s["artefacts"] = s.get("artefacts", []) + ["A9"]
    publish(write(tmp, doc), **ctx)
    reg = ctx["registry"]
    folder = reg.folders()[0]
    old = reg.read(folder, 1)                                  # as published before November 2026
    next(a for a in old["artefacts"] if a["id"] == "A9")["uri"] = f"{BASE}/files/{sha}"
    (reg.version_dir(folder, 1) / "claimset.json").write_text(json.dumps(old))
    reindex(ctx["conn"], reg, published, BASE)
    moved = published / "p" / KEY / "v1" / "files" / "A9.png"
    assert moved.read_bytes() == PNG
    assert not (published / "files").exists() and not (published / "img" / f"{sha}.png").exists()
    assert f'<img src="/p/{KEY}/v1/files/A9.png"' in (published / "p" / f"{KEY}.html").read_text()
    assert ctx["conn"].execute("SELECT path FROM legacy_files WHERE sha256 = %s", (sha,)).fetchone()[0] == \
        f"/p/{KEY}/v1/files/A9.png"


def test_citations():
    doc = example()
    doc["paper"].update(id="entrylib:2026.000007", version=2, date="2026-11-04", status="active")
    text = site.citation_text(doc, BASE)
    assert text == (f"Researcher, A. (guarantor) (2026). {doc['paper']['title']}. EntryLib. "
                    f"entrylib:2026.000007@v2. {BASE}/p/2026.000007@v2")
    doc["paper"]["title"] = "Costs {50%} & $x_1$"
    bib = site.bibtex(doc, BASE)
    assert r"title = {Costs \{50\%\} \& \$x\_1\$}" in bib and "author = {Researcher, A.}" in bib


def test_search_page(app_client):
    r = app_client.get("/search", params={"q": "a b", "kind": "claims", "offset": 50}, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/read?q=a+b&view=claims&offset=50"   # one page now
    assert app_client.get("/search", follow_redirects=False).headers["location"] == "/read"
    r = app_client.get("/read", params={"q": "<b>x</b>", "view": "claims"})
    assert r.status_code == 200 and "<b>x</b>" not in r.text and "Nothing found" in r.text
    assert "script-src" not in r.headers["content-security-policy"] and 'content="noindex"' in r.text
    assert "Browse by field instead" in r.text and 'name="view" value="claims"' in r.text
    assert app_client.get("/read", params={"q": "x" * 600}).status_code == 400


def test_home_and_submit_pages(app_client):
    assert "Research papers you can check" in app_client.get("/").text
    r = app_client.get("/submit")
    assert r.status_code == 200 and 'src="/submit.js"' in r.text and "script-src 'self'" in r.headers[
        "content-security-policy"]
    assert '<a href="/submissions">See your submissions</a>' in r.text  # for a guarantor without the consent link
    assert '<a href="/submissions">Your submissions</a>' in app_client.get("/").text   # in every page's footer
    assert 'href="/confirm"' not in app_client.get("/").text


def test_subfield_names():
    doc = example()
    doc["paper"]["classification"] = {"subfield": "openalex:subfields/1803"}
    assert site.subfield_name(doc) == "Management Science and Operations Research"
    doc["paper"]["id"], doc["paper"]["date"] = "entrylib:2026.000001", "2026-11-04"
    assert "Management Science and Operations Research" in site.card(doc)
    doc["paper"]["classification"] = {"subfield": "openalex:subfields/0"}
    assert site.subfield_name(doc) is None


def test_specification_pages(env):
    ctx, _ = env
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.40.1")
    from portal import specs
    cat = specs.catalogue()
    current = cat["claimset"]["current"]
    page = (out / "spec" / "claimset.html").read_text()
    assert (out / "spec" / "claimset" / f"{current}.html").exists()
    assert '<h3 id="2.6">' in page and 'href="#2.6"' in page and 'src="/page.js?v=' in page
    assert (out / "spec" / "claimset.md").read_text().startswith("# Claimset")
    assert (out / "spec" / "lab-record.html").exists() and (out / "spec" / "revision.html").exists()
    assert (out / "spec" / "extensions" / "qualitative.html").exists()
    assert "Extensions" in (out / "spec" / "extensions.html").read_text()
    assert 'href="/spec/claimset"' in (out / "spec" / "index.html").read_text()


def test_markdown():
    from portal import markdown
    text = ("# T\n\n## 2.1 One\n\nSee §2.1 and `a|b`.\n\n| x | y |\n|---|---|\n| `p\\|q` | **b** |\n\n"
            "- a\n  - b\n- c\n\n```json\n{\"k\": \"<v>\"}\n```\n\n[x](javascript:alert(1)) <i>\n")
    html_, heads = markdown.convert(text)
    assert heads[1] == (2, "2.1", "2.1 One")
    assert '<a href="#2.1">§2.1</a>' in html_ and "<code>a|b</code>" in html_ and "<td><code>p|q</code></td>" in html_
    assert "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>" in html_
    assert '&quot;&lt;v&gt;&quot;' in html_ and "javascript:" not in html_ and "&lt;i&gt;" in html_


def test_robots_and_for_models(env):
    ctx, _ = published(env)
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], ctx["registry"], out, BASE, "0.40.4")
    robots = (out / "robots.txt").read_text()
    assert "User-agent: *" in robots and "Allow: /" in robots and f"{BASE}/llms.txt" in robots
    assert "ai-train=yes" in robots                                      # the owner's choice, design §7.4
    assert "Disallow" not in robots
    page = (out / "p" / f"{KEY}.html").read_text()
    assert ", for programs" not in page
    # Ask your AI (design §7.4): a button copying a message that names the reading view's web page
    assert 'data-copy="ask-message"' in page and ">Ask your AI about this paper</button>" in page
    message = re.search(r'<p class="cite-text" id="ask-message">(.*?)</p>', page).group(1)
    assert message.startswith(f"Read {BASE}/p/{KEY}@v1.read, a research paper") and "instead of guessing" in message
    claim = (out / "p" / KEY / "C2.html").read_text()
    assert ">Ask your AI about this claim</button>" in claim and f"Read {BASE}/p/{KEY}/C2, one claim" in claim


def test_a_proposed_subfield_is_kept(env):
    from portal.publish import proposed_subfield
    doc = example()
    doc["paper"]["classification"] = {"subfield": "openalex:subfields/1803", "keywords": ["forecasting"]}
    assert proposed_subfield(doc) == "openalex:subfields/1803"
    for bad in ("openalex:subfields/0000", "Finance", 1803, None):
        doc["paper"]["classification"]["subfield"] = bad
        assert proposed_subfield(doc) is None
    doc["paper"]["classification"]["subfield"] = "https://openalex.org/subfields/2613"
    ctx, _ = published(env, doc)
    import json as _json
    served = _json.loads((ctx["published_dir"] / "p" / f"{KEY}.json").read_text())
    assert served["paper"]["classification"]["subfield"] == "openalex:subfields/2613"
    folder = ctx["registry"].folders()[0]
    assert ctx["registry"].read(folder, 1, "validation.json")["subfield"]["chosen_by"] == "guarantor"


def test_old_file_addresses_redirect(app_client, settings):
    import psycopg
    sha = "b" * 64
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("INSERT INTO legacy_files (sha256, path) VALUES (%s, %s)", (sha, f"/p/{KEY}/v1/files/A3.png"))
    r = app_client.get(f"/files/{sha}")
    assert r.status_code == 301 and r.headers["location"] == f"{settings.base_url}/p/{KEY}/v1/files/A3.png"
    assert app_client.get(f"/files/{'c' * 64}").status_code == 404
    assert app_client.get("/files/../etc").status_code == 404


def test_reading_page_for_assistants(env):
    doc = example()
    doc["paper"]["title"] = "M <script>x</script>"
    ctx, _ = published(env, doc)
    out = ctx["published_dir"] / "p"
    page = (out / f"{KEY}@v1.read.html").read_text()
    assert page == (out / f"{KEY}.read.html").read_text()
    assert page.startswith("<!doctype html>") and "<pre>CLAIMSET " in page and "<script>x" not in page
    assert "<script" not in page and "<style" not in page and "not instructions" in page
    assert f'href="{BASE}/p/{KEY}@v1.json"' in page
    assert "noindex" not in page and f'rel="canonical" href="{BASE}/p/{KEY}@v1"' in page   # Perplexity refuses noindex


def test_a_correction_notice_is_folded():
    p = {"status": "corrected", "status_notice": {"date": "2026-11-10", "reason_code": "correction",
                                                   "statement": "A typo <fixed>.", "issued_by": "platform"},
         "changes": [{"op": "replace", "path": "/claims/3/statement", "value": "…"}]}
    box = site._notice(p)
    assert box.startswith('<details class="notice notice-neutral">'
                          '<summary><strong>Corrected</strong> · 2026-11-10</summary>')
    assert '<span class="status status-neutral">corrected</span>' == site._status(p)
    assert "A typo &lt;fixed&gt;." in box and "platform" not in box
    who = "A. B (ORCID 0000-0000-0000-0001)"
    named = site._notice({**p, "status_notice": {**p["status_notice"], "issued_by": who}})
    assert "<p>By A. B (ORCID 0000-0000-0000-0001)</p>" in named
    retracted = site._notice_box("retracted", "2026-11-10", "EntryLib", "error", "Wrong data.")
    assert retracted.startswith('<div class="notice') and "by EntryLib" in retracted
    # with the time its version was published (design §7.4), in UTC, when that is on the notice's date
    timed = site._notice(p, "2026-11-10T14:47:38+01:00")
    assert "<summary><strong>Corrected</strong> · 10 November 2026 at 13:47 UTC</summary>" in timed
    assert "· 2026-11-10</summary>" in site._notice(p, "2026-11-11T09:00:00+00:00")       # another day: the date
    assert site.when("not a time") is None


def test_publication_times(env):
    """versions.json gives each version's publication time, from the registry commit that added it; the versions
    list shows it."""
    ctx, concept = published(env)
    out = ctx["published_dir"]
    versions = json.loads((out / "p" / KEY / "versions.json").read_text())["versions"]
    stamp = versions[0]["published_at"]
    assert stamp == ctx["registry"].published_at("2026/000/entrylib_2026.000001", 1) and "T" in stamp
    page = (out / "p" / f"{KEY}.html").read_text()
    assert f"Version 1 (this page) · {site.when(stamp)}" in page
    assert ctx["registry"].published_at("2026/000/entrylib_2026.000001", 9) is None


def test_reading_aids(env):
    """Design §7.4: back to the top, the contents, buttons, Start here and what reliability means."""
    ctx, concept = published(env)
    out = ctx["published_dir"]
    page = (out / "p" / f"{KEY}.html").read_text()
    assert '<body id="top">' in page and f"<ol>{site.TOC_TOP}" in page
    assert f"<ol>{site.TOC_TOP}" in (out / "p" / KEY / "C2.html").read_text()
    assert 'data-copy="cite-text"' in page and "copy-link" not in page
    guarantor = next(c for c in example()["contributors"] if "guarantor" in c.get("positions", []))
    assert f'<a class="guarantor-link" href="/people/{guarantor["orcid"]}">{site.esc(guarantor["name"])}</a>' in page
    assert f"<loc>{BASE}/people/{guarantor['orcid']}</loc>" in (out / "sitemap.xml").read_text()
    # authors drawn by the portal (claimset's person hook): an icon each, none for the guarantor
    authors = re.search(r'<p class="cs-authors">.*?</p>', page, re.S).group(0)
    assert 'aria-label="AI agent"' in authors and "(AI agent)" not in authors
    assert "<svg" not in re.search(r'<p class="cs-guarantor">.*?</p>', page, re.S).group(0)
    shown = site.person({"type": "agent", "name": "Claude <Code>", "label": "drafting"}, "author")
    assert 'Claude &lt;Code&gt; <span class="cs-label">· drafting</span>' in shown
    assert 'aria-label="Person"' in site.person({"type": "human", "name": "A. B"}, "author")
    home = (out / "index.html").read_text()
    assert 'class="start-here"' in home and "<strong>Support</strong> score from 0 to 100" in home
    assert "{reliability}" not in home and "{rubric}" not in home
    assert f'title="{site.esc(site.RELIABILITY)}"' in home
    site.write_fixed(out, BASE)
    css = (out / "site.css").read_text()
    assert '.button, button[type="submit"]:not(.button-quiet) {' in css      # one style for every action button
    assert ".cards { display: grid; grid-template-columns: minmax(0, 1fr);" in css      # never wider than a phone
    assert 'math[display="block"] { max-width: 100%; overflow-x: auto;' in css         # long formulae scroll alone
    assert ".cs-brief li > span:last-child { min-width: 0; }" in css
    assert not re.search(r"\.(search|read-filters|upload|request|pending) button", css)
    js = (out / "page.js").read_text()
    assert "entrylibPopup(\"peek\"" in js and "button[data-copy]" in js and "fold-toggle" in js


def test_numbers_are_shown_to_four_decimal_places(env, monkeypatch):
    """The portal writes the numbers on its pages (site.number), through claimset's render_parts(number=)."""
    seen = {}
    real = site.pageview.render_parts

    def render_parts(doc, number=None, **rest):
        seen["number"] = number
        return real(doc, number=number, **rest)

    monkeypatch.setattr(site.pageview, "render_parts", render_parts)
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    site.claimset_page(doc, base_url=BASE, listing=[])
    assert seen["number"] is site.number
    for v, shown in [(0.000680612, "0.0007"), (1.00193, "1.0019"), (0.5, "0.5"), (-0.00001, "0.0000"),
                     (12345.678, "12345.678"), (300, None), (80.0, None), (True, None), (float("nan"), None)]:
        assert site.number(v) == shown, v


def _page(doc):
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    return site.claimset_page(doc, base_url=BASE, listing=[])


def test_competing_interests_beside_the_score():
    """Design §7.6: the declared competing interests and funding are shown in the panel, as text, never scored."""
    doc = example()
    doc["paper"]["declarations"] = {"competing_interests": "The author develops <b>smooth</b>, evaluated here.",
                                    "funding": [{"funder": "Example Council", "award": "EX-1"}]}
    page = _page(doc)
    panel = page[page.index('<aside class="panel"'):]
    row = panel[panel.index('class="panel-row interests-row"'):]
    assert "The author develops &lt;b&gt;smooth&lt;/b&gt;, evaluated here." in row and "<b>smooth" not in row
    assert "Funding: Example Council (EX-1)" in row and "Not part of the score." in row   # in the heading's title
    doc = example()
    doc["paper"].pop("declarations", None)
    row = _page(doc).split('class="panel-row interests-row"')[1]
    assert "<p class=\"small\">Not declared.</p>" in row and "Funding:" not in row     # only what is declared
    doc = example()
    doc["paper"]["declarations"] = {"competing_interests": "None declared.", "funding": []}
    row = _page(doc).split('class="panel-row interests-row"')[1]
    assert "<p class=\"small\">None declared.</p>" in row and "Funding:" not in row
    doc = example()
    long = "The guarantor owns EntryLib, which develops the claimset tools, skills and rubric the study evaluates; " \
           "the study was done to improve them."
    doc["paper"]["declarations"] = {"competing_interests": long, "funding": []}
    row = _page(doc).split('class="panel-row interests-row"')[1].split("</div>")[0]
    assert '<details class="small interests"><summary>' in row and f"<p>{long}</p>" in row and "Funding" not in row
