"""Confirming without the consent link (/confirm): sign in with ORCID, see the submissions naming you, confirm one."""

import re
import urllib.parse

from test_consent import GUARANTOR, submit


def sign_in_at_confirm(c, as_orcid=GUARANTOR):
    r = c.get("/confirm/start")
    assert r.status_code == 303, r.text
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    return c.get("/consent/callback", params={"state": state, "code": as_orcid})


def tickets(page):
    return re.findall(r'name="ticket" value="([^"]+)"', page)


def confirm(c, ticket):
    return c.post("/confirm", content=urllib.parse.urlencode({"ticket": ticket}),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})


def test_the_page(app_client):
    r = app_client.get("/confirm")
    assert r.status_code == 200 and 'href="/confirm/start"' in r.text and "Sign in with ORCID" in r.text


def test_the_guarantor_confirms_without_the_link(app_client):
    out, _ = submit(app_client)
    assert app_client.get(f"/api/submissions/{out['id']}").json()["confirm_url"].endswith("/confirm")
    r = sign_in_at_confirm(app_client)
    assert r.status_code == 200 and "1 submission names you" in r.text and "Confirm and publish" in r.text
    [ticket] = tickets(r.text)
    r = confirm(app_client, ticket)
    assert r.status_code == 200 and "published as entrylib:" in r.text, r.text
    s = app_client.get(f"/api/submissions/{out['id']}").json()
    assert s["state"] == "published" and "confirm_url" not in s
    assert confirm(app_client, ticket).status_code == 400                          # used once
    assert "No submission is waiting" in sign_in_at_confirm(app_client).text


def test_someone_else_sees_nothing(app_client):
    submit(app_client)
    r = sign_in_at_confirm(app_client, as_orcid="0000-0002-1825-0097")
    assert r.status_code == 200 and "No submission is waiting" in r.text and not tickets(r.text)
    assert confirm(app_client, "made-up").status_code == 400


def test_a_listing_sign_in_is_used_once(app_client):
    submit(app_client)
    r = app_client.get("/confirm/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    assert app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR}).status_code == 200
    assert app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR}).status_code == 400


def test_submitted_text_is_escaped(app_client):
    from publishing import example
    doc = example()
    doc["paper"]["title"] = "Seasonality <script>alert(1)</script> in retail"
    submit(app_client, doc)
    r = sign_in_at_confirm(app_client)
    assert "<script>alert(1)" not in r.text and "&lt;script&gt;" in r.text
