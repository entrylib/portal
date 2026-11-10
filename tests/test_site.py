"""The website (design §7.4): pages written at publication and at start, citations, images, search, escaping."""

import json

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
    assert page.count("<script") == 1 and 'src="/page.js?v=' in page and 'class="cs-page"' in page
    assert 'href="/site.css?v=' in page and 'href="/claimset.css?v=' in page
    for part in ('<span class="origin">native</span>', "status-ok", f"{concept}@v1", 'id="versions"',
                 '<a href="#versions">Versions</a>', f'href="/p/{KEY}@v1.bib"', f'href="/p/{KEY}@v1.ris"',
                 f'href="/p/{KEY}@v1.txt"', 'type="application/json"', "How it is computed", "light-green"):
        assert part in page, part
    bib = (out / "p" / f"{KEY}.bib").read_text()
    assert bib.startswith("@misc{entrylib2026.000001v1,") and f"{BASE}/p/{KEY}@v1" in bib
    ris = (out / "p" / f"{KEY}@v1.ris").read_bytes()
    assert ris.startswith(b"TY  - GEN\r\n") and ris.endswith(b"ER  - \r\n")


def test_listings_and_feed(env):
    ctx, concept = published(env)
    out = ctx["published_dir"]
    home = (out / "index.html").read_text()
    assert "The open library of machine-readable entries" in home and f'href="/p/{KEY}"' in home
    assert 'action="/search"' in home and "Recently published" in home
    assert f'href="/p/{KEY}"' in (out / "all.html").read_text()
    feed = (out / "feed.xml").read_text()
    assert feed.startswith('<?xml') and f"<id>{BASE}/p/{KEY}@v1</id>" in feed


def test_fixed_pages_and_assets_at_start(env):
    ctx, _ = env
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.40.1")
    for name in ("lab", "about", "agents", "privacy"):
        page = (out / f"{name}.html").read_text()
        assert page.startswith("<!doctype html>") and "<script" not in page and "{base}" not in page, name
    assert "This website was created by Claude Opus 5.5." in (out / "about.html").read_text()
    assert f"{BASE}/mcp" in (out / "agents.html").read_text()
    assert (out / "site.css").exists() and ".cs-toc" in (out / "claimset.css").read_text()
    assert (out / "fonts" / "fonts.css").exists() and (out / "img" / "orcid.svg").exists()
    assert (out / "spec" / "claimset.md").exists() and "Specifications" in (out / "spec" / "index.html").read_text()
    assert (out / "index.html").exists()                    # the home page, before anything is published


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
    r = app_client.get("/search")
    assert r.status_code == 200 and "Search the claims" in r.text and "script-src" not in r.headers[
        "content-security-policy"]
    r = app_client.get("/search", params={"q": "<b>x</b>", "kind": "claims"})
    assert r.status_code == 200 and "<b>x</b>" not in r.text and "Nothing found" in r.text
    assert app_client.get("/search", params={"q": "x" * 600}).status_code == 400


def test_home_and_submit_pages(app_client):
    assert "The open library" in app_client.get("/").text
    r = app_client.get("/submit")
    assert r.status_code == 200 and 'src="/submit.js"' in r.text and "script-src 'self'" in r.headers[
        "content-security-policy"]


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
    assert "Disallow" not in robots
    page = (out / "p" / f"{KEY}.html").read_text()
    assert f'<a class="copy-link" href="{BASE}/p/{KEY}@v1.read">Copy the link for your AI assistant</a>' in page
    assert ", for programs" not in page


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


def test_a_correction_notice_is_folded():
    p = {"status": "corrected", "status_notice": {"date": "2026-11-10", "reason_code": "correction",
                                                   "statement": "A typo <fixed>.", "issued_by": "platform"}}
    box = site._notice(p)
    assert box.startswith('<details class="notice notice-warn">'
                          '<summary><strong>Corrected</strong> · 2026-11-10</summary>')
    assert "A typo &lt;fixed&gt;." in box and "platform" not in box
    who = "A. B (ORCID 0000-0000-0000-0001)"
    named = site._notice({**p, "status_notice": {**p["status_notice"], "issued_by": who}})
    assert "<p>By A. B (ORCID 0000-0000-0000-0001)</p>" in named
    retracted = site._notice_box("retracted", "2026-11-10", "EntryLib", "error", "Wrong data.")
    assert retracted.startswith('<div class="notice') and "by EntryLib" in retracted


def test_numbers_are_shown_to_four_digits(env, monkeypatch):
    """The page asks the package for four significant digits when the package can round (claimset 0.40.7)."""
    seen = {}
    real = site.cshtml.render_parts

    def render_parts(doc, file_url=None, ref_text=None, digits=None):
        seen["digits"] = digits
        return real(doc, file_url=file_url)

    monkeypatch.setattr(site.cshtml, "render_parts", render_parts)
    doc = example()
    doc["paper"].update({"id": "entrylib:2026.000001", "version": 1, "date": "2026-11-10", "status": "active"})
    site.claimset_page(doc, base_url=BASE, listing=[])
    assert seen["digits"] == 4
