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
    assert page.count("<script") == 1 and 'src="/toc.js"' in page and 'class="cs-page"' in page
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
    doc["artefacts"].append({"id": "A9", "kind": "figure", "function": "data_plot", "uri": "errors.png",
                             "description": "Errors by horizon", "licence": "CC-BY-4.0",
                             "availability": {"level": "public"}})
    for c in doc["claims"]:
        for s in c.get("support") or []:
            if s.get("evidence") == "E1":
                s["artefacts"] = s.get("artefacts", []) + ["A9"]
    folder = tmp / "pkg"
    folder.mkdir()
    (folder / "errors.png").write_bytes(PNG)
    (folder / "paper.claimset.json").write_text(json.dumps(doc))
    from claimset.package import build
    build(str(folder / "paper.claimset.json"), str(tmp / "bag"))
    publish(tmp / "bag", **ctx)
    out = ctx["published_dir"]
    page = (out / "p" / f"{KEY}.html").read_text()
    shown = list((out / "img").glob("*.png"))
    assert len(shown) == 1 and f'<img src="/img/{shown[0].name}"' in page
    assert shown[0].read_bytes() == PNG


def test_image_type_and_file_url(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    digest = "a" * 64
    (files / digest).write_bytes(b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>")
    (files / ("b" * 64)).write_bytes(b"col1,col2\n1,2\n")
    url = site.file_url_for(tmp_path, BASE)
    assert url({"uri": f"{BASE}/files/{digest}"}) == f"/img/{digest}.svg"
    assert url({"uri": f"{BASE}/files/{'b' * 64}"}) is None                  # not an image
    assert url({"uri": "https://example.org/x.png"}) is None                 # not ours: linked, not shown
    assert url({"uri": f"{BASE}/files/../../etc/passwd"}) is None


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
    assert '<h3 id="2.6">' in page and 'href="#2.6"' in page and 'src="/toc.js"' in page
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
