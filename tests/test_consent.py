import datetime as dt
import json
import re
import urllib.parse

import psycopg
from fastapi.testclient import TestClient
from publishing import example, fake_classifier

from portal import limits
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
    text = re.sub(r"<[^>]+>", "", r.text)                                    # the page shows terms by their words
    assert re.sub(r"\[\[D\d+:([^\]]*)\]\]", r"\1", first) in text and "Confirm: sign in with ORCID" in r.text


def test_the_consent_page_previews_the_paper(app_client):
    """Design §4.2: the claimset's page as it will be published, marked a preview, the Confirm button in a bar at
    the top, with no identifier or links of its own yet."""
    _, token = submit(app_client)
    page = app_client.get(f"/consent/{token}").text
    bar = page.index('class="preview-bar"')
    assert bar < page.index('class="cs-page entry preview"') and bar < page.index("Confirm: sign in with ORCID")
    assert "Preview, not published yet" in page[bar:bar + 300]
    assert 'data-view="paper"' in page and 'id="claims"' in page and 'class="panel"' in page   # the paper view
    assert "0000.000000" not in page                                          # the placeholder ID is never shown
    assert "By confirming, you state" in page and "responsible researcher" in page
    # the switch leads to the record of the same preview, on the consent page, and back
    assert f'<a href="/consent/{token}" aria-current="page"' in page and f'href="/consent/{token}?view=record"' in page
    assert 'href="/p/' not in page.split('class="cs-page')[1].split("</article>")[0].replace(
        'href="/p/2026.', "")                                                 # nothing links to a published page
    record = app_client.get(f"/consent/{token}", params={"view": "record"}).text
    assert 'id="principal"' in record and 'data-view="paper"' not in record   # the record's sections
    assert f'href="/consent/{token}?view=record" aria-current="page"' in record
    assert "Confirm: sign in with ORCID" in record and "By confirming, you state" in record


def test_the_preview_links_what_only_the_record_holds_to_its_record():
    """Design §4.2: in the paper view of a preview, a link to evidence or an artefact leads to the preview's record,
    as a published paper view's leads to /p/<id>/record."""
    from portal import site
    doc = example()
    html = site.preview_page(doc, base_url="", bar="", statement="", view="paper", paper_href="/consent/t",
                             record_href="/consent/t?view=record")
    assert 'href="/consent/t?view=record#E1"' in html and 'href="#E1"' not in html


def test_your_submissions_opens_after_a_sign_in(app_client):
    """Design §4.2: after an ORCID sign-in, Your submissions opens without signing in again, until signing out."""
    assert "Sign in with ORCID" in app_client.get("/submissions").text
    _, token = submit(app_client)
    r = app_client.get("/submissions/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    r = app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("entrylib_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    app_client.cookies.set("entrylib_session", cookie.split(";")[0].split("=", 1)[1])  # the test client is http
    page = app_client.get("/submissions").text
    assert "Signed in as" in page and "Waiting for you" in page and 'action="/signout"' in page
    assert app_client.get("/submissions").text.count('name="ticket"') >= 1      # new tickets on each visit
    app_client.post("/signout")
    assert "Signed in as" not in app_client.get("/submissions").text


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


def test_a_consent_signin_is_never_taken_for_another_kind(app_client, monkeypatch):
    """A random state that begins like a removal or listing state (n_, l_, m_) still confirms the claimset."""
    import portal.consent
    for start in ("n_", "l_", "m_"):
        out, token = submit(app_client, None if start == "n_" else _new_title(start))
        monkeypatch.setattr(portal.consent.secrets, "token_urlsafe", lambda n, s=start: s + "x" * 30)
        r = app_client.get(f"/consent/{token}/start")
        monkeypatch.undo()
        state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
        r = app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR})
        assert r.status_code == 200 and "published as entrylib:" in r.text, r.text


def _new_title(tag):
    doc = example()
    doc["paper"]["title"] += f" ({tag})"
    return doc


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


def test_weekly_limit_on_new_claimsets(app_client, monkeypatch):
    """At the limit, a new submission is refused when it is made, saying why and from when (design §8)."""
    monkeypatch.setattr(limits, "NEW_PER_WEEK", 2)
    for n in range(2):
        _, token = submit(app_client, titled(n))
        assert sign_in(app_client, token).status_code == 200
    r = app_client.post("/api/submissions", content=json.dumps(titled("over")).encode(),
                        headers={"Content-Type": "application/json"})
    assert r.status_code == 429
    text = r.json()["error"] if "error" in r.json() else json.dumps(r.json())
    assert "Not accepted: the limit is reached" in text and "up to 2 new claimsets in any seven days" in text
    assert "2 published in the last seven days and 0 waiting" in text and "You can submit again from" in text
    from portal import site
    assert "publish up to 2 new claimsets in any seven days" in site.fixed_page("agents", "https://e.org")


def test_waiting_submissions_count_and_confirmation_is_refused_over_the_limit(app_client, monkeypatch):
    monkeypatch.setattr(limits, "NEW_PER_WEEK", 2)
    _, first = submit(app_client, titled("a"))
    out, second = submit(app_client, titled("b"))
    r = app_client.post("/api/submissions", content=json.dumps(titled("c")).encode(),
                        headers={"Content-Type": "application/json"})
    assert r.status_code == 429 and "2 waiting for your confirmation" in json.dumps(r.json())
    assert sign_in(app_client, first).status_code == 200
    monkeypatch.setattr(limits, "NEW_PER_WEEK", 1)                 # the limit lowered meanwhile
    page = sign_in(app_client, second)
    assert page.status_code == 429 and "be confirmed yet: the limit is reached" in page.text
    assert "<p>Each person can" in page.text
    assert "Its link expires before then" in page.text
    assert app_client.get(f"/api/submissions/{out['id']}").json()["state"] == "pending"


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
