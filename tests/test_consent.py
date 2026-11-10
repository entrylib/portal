import datetime as dt
import json
import urllib.parse

import psycopg
from fastapi.testclient import TestClient
from publishing import example, fake_classifier

from portal import consent
from portal.app import create_app
from portal.db import make_pool, migrate
from portal.orcid import OrcidError
from portal.registry import Registry
from portal.storage import FileStore

GUARANTOR = "0000-0000-0000-0000"                    # the guarantor of the example claimset


class FakeOrcid:
    """Stands in for ORCID: the 'code' it receives is the ORCID iD to sign in as."""
    configured = True

    def authorize_url(self, state):
        return "https://sandbox.orcid.org/oauth/authorize?" + urllib.parse.urlencode({"state": state})

    def exchange(self, code):
        if code == "fail":
            raise OrcidError("ORCID sign-in could not be completed: test")
        return code, "Signed In"


def submit(c, doc=None):
    r = c.post("/api/submissions", content=json.dumps(doc or example()).encode(),
               headers={"Content-Type": "application/json"})
    assert r.status_code == 201, r.text
    out = r.json()
    return out, out["consent"][0]["consent_url"].rsplit("/", 1)[-1]


def sign_in(c, token, as_orcid=GUARANTOR):
    """Open the consent link, start sign-in, and come back from ORCID as `as_orcid`."""
    r = c.get(f"/consent/{token}/start")
    assert r.status_code == 303, r.text
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    return c.get("/consent/callback", params={"state": state, "code": as_orcid})


def test_consent_page_shows_the_claims(app_client):
    _, token = submit(app_client)
    r = app_client.get(f"/consent/{token}")
    assert r.status_code == 200
    doc = example()
    assert doc["paper"]["title"] in r.text and GUARANTOR in r.text
    first = next(c["statement"] for c in doc["claims"] if c["id"] == doc["paper"]["contributions"][0])
    assert first in r.text and "Sign in with ORCID and confirm" in r.text


def test_submitted_text_is_escaped(app_client):
    doc = example()
    doc["paper"]["title"] = "Seasonality <script>alert(1)</script> in retail sales"
    _, token = submit(app_client, doc)
    r = app_client.get(f"/consent/{token}")
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_the_guarantor_confirms_and_the_claimset_is_published(app_client, settings):
    out, token = submit(app_client)
    r = sign_in(app_client, token)
    assert r.status_code == 200 and "published as entrylib:" in r.text, r.text
    s = app_client.get(f"/api/submissions/{out['id']}").json()
    assert s["state"] == "published" and s["published"].endswith("@v1")
    assert s["guarantors"] == [{"orcid": GUARANTOR, "confirmed": True}]
    assert not list(settings.submissions_dir.glob(f"{out['id']}.*"))          # the upload is gone once published
    key = s["published"].split(":", 1)[1].split("@")[0]
    assert (settings.published_dir / "p" / f"{key}.json").exists()
    assert "published as" in app_client.get(f"/consent/{token}").text


def test_someone_else_cannot_confirm(app_client):
    out, token = submit(app_client)
    r = sign_in(app_client, token, as_orcid="0000-0002-1825-0097")
    assert r.status_code == 403 and "only the guarantor" in r.text
    assert app_client.get(f"/api/submissions/{out['id']}").json()["state"] == "pending"
    assert sign_in(app_client, token).status_code == 200                   # the guarantor still can


def test_a_signin_state_is_used_once(app_client):
    _, token = submit(app_client)
    r = app_client.get(f"/consent/{token}/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    assert app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR}).status_code == 200
    assert app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR}).status_code == 400


def test_unknown_link_and_failed_signin(app_client):
    assert app_client.get("/consent/not-a-token").status_code == 404
    _, token = submit(app_client)
    r = app_client.get(f"/consent/{token}/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    assert app_client.get("/consent/callback", params={"state": state, "code": "fail"}).status_code == 502
    assert app_client.get("/consent/callback", params={"error": "access_denied"}).status_code == 400


def test_expired_submission_cannot_be_confirmed(app_client, settings):
    from portal import submissions
    out, token = submit(app_client)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        submissions.expire(conn, settings.submissions_dir, now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=49))
    assert "expired" in app_client.get(f"/consent/{token}").text
    r = app_client.get(f"/consent/{token}/start")
    assert r.status_code == 303 and r.headers["location"].endswith(f"/consent/{token}")      # back to the page


def titled(n):
    doc = example()
    doc["paper"]["title"] = f"{doc['paper']['title']} {n}"
    return doc


def test_weekly_limit_on_new_claimsets(app_client, settings, monkeypatch):
    """Over the limit, a confirmation is kept and the claimset published when the limit allows (design §8)."""
    monkeypatch.setattr(consent, "MAX_NEW_PER_WEEK", 2)
    for n in range(2):
        _, token = submit(app_client, titled(n))
        assert sign_in(app_client, token).status_code == 200
    out, token = submit(app_client, titled("over"))
    r = sign_in(app_client, token)
    assert r.status_code == 200 and "It will be published on" in r.text
    assert "Each person can publish up to 2 new claimsets a week" in r.text and "<p>Why not straight away?" in r.text
    st = app_client.get(f"/api/submissions/{out['id']}").json()
    assert st["state"] == "confirmed" and "publish_after" in st and "published" not in st
    when = dt.datetime.fromisoformat(st["publish_after"])
    assert dt.timedelta(days=6) < when - dt.datetime.now(dt.UTC) <= dt.timedelta(days=7)
    from portal import worker
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        assert out["id"] not in [r[0] for r in worker._confirmed(conn)]          # waits
        conn.execute("UPDATE submissions SET publish_after = now() - interval '1 minute' WHERE id = %s",
                     (out["id"],))
        assert out["id"] in [r[0] for r in worker._confirmed(conn)]              # then is published
    _, token = submit(app_client, titled("later"))                               # the next waits longer still
    assert "It will be published on" in sign_in(app_client, token).text


def test_correction_by_the_guarantor(app_client):
    out, token = submit(app_client)
    sign_in(app_client, token)
    concept = app_client.get(f"/api/submissions/{out['id']}").json()["published"].split("@")[0]
    doc = example()
    doc["paper"]["id"] = concept
    doc["paper"]["correction_reason"] = "The first claim's statement omitted that it held in every run."
    doc["claims"][0]["statement"] = doc["claims"][0]["statement"].rstrip(".") + " in every run."
    out2, token2 = submit(app_client, doc)
    assert out2["kind"] == "correction"
    assert sign_in(app_client, token2).status_code == 200
    assert app_client.get(f"/api/submissions/{out2['id']}").json()["published"] == f"{concept}@v2"


def test_correction_by_someone_else_is_refused(app_client):
    out, token = submit(app_client)
    sign_in(app_client, token)
    concept = app_client.get(f"/api/submissions/{out['id']}").json()["published"].split("@")[0]
    doc = example()
    doc["paper"]["id"] = concept
    doc["paper"]["correction_reason"] = "A correction by another person."
    g = next(c for c in doc["contributors"] if "guarantor" in c["positions"])
    g["orcid"] = "0000-0002-1825-0097"
    r = app_client.post("/api/submissions", content=json.dumps(doc).encode(),
                        headers={"Content-Type": "application/json"})
    assert r.status_code == 403 and "guarantor of the current version" in r.json()["error"]


def test_signin_is_unavailable_without_orcid_credentials(settings):
    migrate(settings.database_url)
    pool = make_pool(settings.database_url, min_size=1, max_size=2)
    pool.open()
    try:
        with TestClient(create_app(settings, pool=pool, run_expiry=False), follow_redirects=False) as c:
            _, token = submit(c)
            assert c.get(f"/consent/{token}/start").status_code == 503
    finally:
        pool.close()


def test_the_worker_waits_quietly_for_the_classifier(settings, caplog):
    import logging

    from portal import worker
    from portal.classify import ClassifierError
    migrate(settings.database_url)
    pool = make_pool(settings.database_url, min_size=1, max_size=3)
    pool.open()

    def down(doc):
        raise ClassifierError("classifier unavailable: connection refused")
    publisher = {"registry": Registry(settings.registry_dir).init(),
                 "store": FileStore(settings.published_dir, settings.base_url), "classifier": down}
    try:
        with TestClient(create_app(settings, pool=pool, run_expiry=False, orcid=FakeOrcid(), publisher=publisher),
                        follow_redirects=False) as c:
            out, token = submit(c)
            with caplog.at_level(logging.WARNING, logger="portal"):
                assert "published shortly" in sign_in(c, token).text
            assert c.get(f"/api/submissions/{out['id']}").json()["state"] == "confirmed"
            waits = [r for r in caplog.records if "waits for the classifier" in r.getMessage()]
            assert waits and all(r.exc_info is None for r in waits)
            with pool.connection() as conn:
                assert worker.publish_confirmed(conn, settings=settings, **{**publisher,
                                                "classifier": fake_classifier})[0][1].startswith("entrylib:2026.000001")
    finally:
        pool.close()
