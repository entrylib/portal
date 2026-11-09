"""Submission routes (design §4.4), new versions and duplicates (§4.5), and the guarantor filter (§7.2)."""

import json

import pytest
from publishing import BASE, example, write
from test_consent import GUARANTOR, sign_in, submit

from portal import fetch, search
from portal.indexer import title_key
from portal.publish import publish


def post(c, doc, **params):
    return c.post("/api/submissions", params=params, content=json.dumps(doc).encode(),
                  headers={"Content-Type": "application/json"})


def published_id(c, sub_id):
    return c.get(f"/api/submissions/{sub_id}").json()["published"].split("@")[0]


def test_title_key():
    assert title_key("Method M: a  Seasonal-Naive  test!") == title_key("method m — a seasonal naive TEST")
    assert title_key("Méthode ﬁ") == "méthodefi" and title_key("") == "" and title_key(None) == ""


class TestDuplicates:
    def test_a_published_claimset_is_named(self, app_client):
        out, token = submit(app_client)
        sign_in(app_client, token)
        concept = published_id(app_client, out["id"])
        doc = example()
        doc["paper"]["title"] = doc["paper"]["title"].upper() + "."
        r = post(app_client, doc)
        assert r.status_code == 409 and concept in r.json()["error"] and "paper.id" in r.json()["error"]
        assert post(app_client, doc, new_paper="true").status_code == 201

    def test_a_pending_one_does_not_block_and_consent_checks_again(self, app_client):
        first, token1 = submit(app_client)
        second, token2 = submit(app_client)                 # a fixed file, before confirming the first
        assert sign_in(app_client, token2).status_code == 200
        r = sign_in(app_client, token1)
        assert r.status_code == 409 and "already confirmed" in r.text
        assert app_client.get(f"/api/submissions/{first['id']}").json()["state"] == "pending"

    def test_new_paper_skips_the_check_at_consent(self, app_client):
        _, token1 = submit(app_client)
        r = post(app_client, example(), new_paper="true")
        token2 = r.json()["consent"][0]["consent_url"].rsplit("/", 1)[-1]
        assert sign_in(app_client, token1).status_code == 200
        assert sign_in(app_client, token2).status_code == 200

    def test_another_guarantor_or_a_new_version_is_not_a_duplicate(self, app_client):
        out, token = submit(app_client)
        sign_in(app_client, token)
        concept = published_id(app_client, out["id"])
        doc = example()
        for c in doc["contributors"]:
            if c.get("orcid") == GUARANTOR:
                c["orcid"] = "0000-0002-1825-0097"
        assert post(app_client, doc).status_code == 201
        doc = example()
        doc["paper"]["id"] = concept
        doc["paper"]["correction_reason"] = "Clearer wording."
        doc["claims"][0]["statement"] += " "
        assert post(app_client, doc).json()["kind"] == "correction"


def test_json_with_artefacts_elsewhere_keeps_their_links(app_client, settings):
    doc = example()
    linked = [a["uri"] for a in doc["artefacts"] if a["uri"].startswith("https://")]
    assert linked
    out, token = submit(app_client, doc)
    sign_in(app_client, token)
    key = published_id(app_client, out["id"]).split(":")[1]
    published = json.loads((settings.published_dir / "p" / f"{key}.json").read_text())
    assert [a["uri"] for a in published["artefacts"] if a["uri"].startswith("https://")] == linked


class TestFromUrl:
    def test_fetched_and_checked_as_an_upload(self, app_client, monkeypatch):
        def fake(url, directory, **_):
            assert url == "https://zenodo.org/records/1/files/paper.claimset.json"
            directory.mkdir(parents=True, exist_ok=True)
            return write(directory, example(), "fetched.json")
        monkeypatch.setattr(fetch, "download", fake)
        r = app_client.post("/api/submissions/from-url", json={"url": "https://zenodo.org/records/1/files/"
                                                                     "paper.claimset.json"})
        assert r.status_code == 201 and r.json()["consent"]

    def test_refused_urls(self, app_client):
        r = app_client.post("/api/submissions/from-url", json={"url": "https://127.0.0.1/p.zip"})
        assert r.status_code == 422 and "public address" in r.json()["error"]
        assert app_client.post("/api/submissions/from-url", json={"url": "http://e.org/p.zip"}).status_code == 422
        assert app_client.post("/api/submissions/from-url", json={}).status_code == 422


def test_upload_page(app_client):
    r = app_client.get("/submit")
    csp = r.headers["content-security-policy"]
    assert r.status_code == 200 and '<script src="/submit.js">' in r.text and "<script>" not in r.text
    assert "script-src 'self'" in csp and "default-src 'none'" in csp and "connect-src 'self'" in csp
    js = app_client.get("/submit.js")
    assert js.headers["content-type"].startswith("text/javascript") and "/api/submissions" in js.text
    assert "innerHTML" not in js.text and "textContent" in js.text


class TestGuarantorFilter:
    def test_search(self, env):
        ctx, tmp = env
        publish(write(tmp, example()), **ctx)
        conn = ctx["conn"]
        assert search.search_claims(conn, BASE, "seasonality", guarantor=GUARANTOR)["results"]
        assert search.search_claims(conn, BASE, "seasonality", guarantor=f"https://orcid.org/{GUARANTOR}")["results"]
        assert search.search_claims(conn, BASE, "seasonality", guarantor="0000-0002-1825-0097")["results"] == []
        listed = search.search_papers(conn, BASE, "", guarantor=GUARANTOR)["results"]
        assert len(listed) == 1 and "rank" not in listed[0]
        assert search.search_papers(conn, BASE, "retail", guarantor=GUARANTOR)["results"][0]["rank"] > 0
        for bad in ("someone", "0000-0000-0000-000"):
            with pytest.raises(search.SearchError, match="ORCID"):
                search.search_papers(conn, BASE, "", guarantor=bad)
        with pytest.raises(search.SearchError):
            search.search_papers(conn, BASE, "")             # neither words nor a guarantor

    def test_over_http(self, client):
        r = client.get("/api/search/papers", params={"guarantor": GUARANTOR})
        assert r.status_code == 200 and r.json()["results"] == []
        assert client.get("/api/search/claims", params={"q": "x", "guarantor": "x"}).status_code == 400
