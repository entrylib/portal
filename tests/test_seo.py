"""What search engines, Google Scholar and link previews read (design §7.8), area addresses, IndexNow."""

import json
import re

from publishing import BASE, example, write

from portal import indexnow, site
from portal.publish import publish

KEY = "2026.000001"


def doc_in(sub, title):
    d = example()
    d["paper"]["title"] = title
    d["paper"]["classification"] = {**(d["paper"].get("classification") or {}), "subfield": f"openalex:subfields/{sub}"}
    return d


def test_claimset_page_head(env):
    ctx, tmp = env
    doc = doc_in("1803", "Forecasting </script><b>study</b>")
    publish(write(tmp, doc), **ctx)
    page = (ctx["published_dir"] / "p" / f"{KEY}.html").read_text()
    head = page.split("</head>")[0]
    assert '<meta name="citation_title" content="Forecasting &lt;/script&gt;&lt;b&gt;study&lt;/b&gt;">' in head
    guarantor = next(c for c in doc["contributors"] if "guarantor" in c.get("positions", []))
    assert '<meta name="citation_publisher" content="EntryLib">' in head
    assert 'name="citation_publication_date"' in head
    assert f'name="citation_abstract_html_url" content="{BASE}/p/{KEY}"' in head
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', head, re.S)
    assert len(blocks) == 1 and "</" not in blocks[0]
    article = json.loads(blocks[0])
    assert article["@type"] == "ScholarlyArticle" and article["url"] == f"{BASE}/p/{KEY}"
    assert article["name"] == doc["paper"]["title"] and article["about"]["name"].startswith("Management Science")
    assert any(a["name"] == guarantor["name"] or a.get("sameAs", "").endswith(guarantor["orcid"])
               for a in article["author"]) or article["author"]
    assert f'<meta property="og:image" content="{BASE}/og-card.png">' in head
    assert '<meta name="twitter:card" content="summary_large_image">' in head


def test_home_and_fixed_files(env):
    ctx, tmp = env
    publish(write(tmp, doc_in("1803", "Forecasting study")), **ctx)
    home = (ctx["published_dir"] / "index.html").read_text()
    kinds = [json.loads(b)["@type"] for b in re.findall(r'type="application/ld\+json">(.*?)</script>', home, re.S)]
    assert kinds == ["Organization", "WebSite"] and 'property="og:title" content="EntryLib"' in home
    sitemap = (ctx["published_dir"] / "sitemap.xml").read_text()
    assert f"<loc>{BASE}/read/social-sciences/decision-sciences</loc>" in sitemap
    assert f"<loc>{BASE}/read/social-sciences/decision-sciences/management-science-and-operations-research</loc>" \
        in sitemap and "/read/life-sciences" not in sitemap


def test_area_addresses(app_client):
    r = app_client.get("/read/social-sciences/decision-sciences")
    assert r.status_code == 200 and "<title>Decision Sciences: claims and claimsets · EntryLib</title>" in r.text
    assert 'rel="canonical" href="https://entrylib.test/read/social-sciences/decision-sciences"' in r.text
    r = app_client.get("/read", params={"area": "18", "view": "claimsets"}, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/read/social-sciences/decision-sciences?view=claimsets"
    assert app_client.get("/read/nowhere/at-all").status_code == 404


def test_indexnow(monkeypatch, tmp_path):
    monkeypatch.delenv("PORTAL_INDEXNOW_KEY", raising=False)
    assert indexnow.notify(["https://e.org/p/1"], "https://e.org") is False
    monkeypatch.setenv("PORTAL_INDEXNOW_KEY", "a1b2c3d4e5f6a7b8")
    sent = []

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout):
        sent.append(json.loads(req.data))
        return Resp()
    assert indexnow.notify(indexnow.claimset_urls("entrylib:2026.000001", 2, "https://e.org"), "https://e.org",
                           opener=opener)
    assert sent[0]["key"] == "a1b2c3d4e5f6a7b8" and sent[0]["keyLocation"] == "https://e.org/indexnow.txt"
    assert "https://e.org/p/2026.000001@v2" in sent[0]["urlList"] and sent[0]["host"] == "e.org"
    site.write_fixed(tmp_path, "https://e.org")
    assert (tmp_path / "indexnow.txt").read_text().strip() == "a1b2c3d4e5f6a7b8"
    assert (tmp_path / "og-card.png").exists()
