"""Confirming without the consent link (/confirm): sign in with ORCID, see the submissions naming you, confirm one."""

import re
import urllib.parse

from test_consent import GUARANTOR, submit, titled


def sign_in_at_confirm(c, as_orcid=GUARANTOR):
    r = c.get("/confirm/start")
    assert r.status_code == 303, r.text
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    return c.get("/consent/callback", params={"state": state, "code": as_orcid})


def tickets(page):
    """The tickets of a listing, once each (a submission's Confirm and Cancel forms carry the same one)."""
    return list(dict.fromkeys(re.findall(r'name="ticket" value="([^"]+)"', page)))


def confirm(c, ticket, action="confirm"):
    return c.post("/confirm", content=urllib.parse.urlencode({"ticket": ticket, "action": action}),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})


def sign_in_at(c, page, as_orcid=GUARANTOR):
    r = c.get(f"/{page}/start")
    assert r.status_code == 303, r.text
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    return c.get("/consent/callback", params={"state": state, "code": as_orcid})


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


def test_the_guarantor_cancels_a_submission(app_client, settings):
    """Design §4.2 step 5: a submission no longer wanted is cancelled; nothing is kept and nothing published."""
    out, _ = submit(app_client)
    page = sign_in_at_confirm(app_client).text
    assert "Cancel this submission" in page and 'name="action" value="cancel"' in page
    [ticket] = tickets(page)
    r = confirm(app_client, ticket, "cancel")
    assert r.status_code == 200 and "cancelled" in r.text
    s = app_client.get(f"/api/submissions/{out['id']}").json()
    assert s["state"] == "refused" and "cancelled by its guarantor" in str(s)
    assert not list(settings.submissions_dir.glob(f"{out['id']}.*"))         # the file is deleted
    assert confirm(app_client, ticket, "cancel").status_code == 400          # the ticket is used
    assert "No submission is waiting" in sign_in_at_confirm(app_client).text


def test_your_submissions(app_client):
    """/submissions (design §4.2): what waits for you, what closed recently, and what you guarantee."""
    assert 'href="/submissions/start"' in app_client.get("/submissions").text
    cancelled, _ = submit(app_client)
    [ticket] = tickets(sign_in_at_confirm(app_client).text)
    confirm(app_client, ticket, "cancel")
    published, _ = submit(app_client)
    [ticket] = tickets(sign_in_at_confirm(app_client).text)
    assert "published as entrylib:" in confirm(app_client, ticket).text
    submit(app_client, titled("Another study of seasonality"))
    page = sign_in_at(app_client, "submissions").text
    assert "Your submissions" in page and "Only you see this page" in page
    assert len(tickets(page)) == 1 and "Confirm and publish" in page            # what waits for you
    assert "Closed in the last 14 days" in page and "cancelled by you" in page
    assert "<h2>Published</h2>" in page and 'href="/p/2026.000001"' in page and f'href="/people/{GUARANTOR}"' in page
    other = sign_in_at(app_client, "submissions", as_orcid="0000-0002-1825-0097").text
    assert "Nothing waits for your confirmation" in other and "No claimset names you" in other


def test_a_guarantors_page(app_client):
    """/people/<ORCID iD> (design §7.4): the published claimsets a person guarantees; their name links to it."""
    submit(app_client)
    [ticket] = tickets(sign_in_at_confirm(app_client).text)
    confirm(app_client, ticket)
    r = app_client.get(f"/people/{GUARANTOR}")
    assert r.status_code == 200 and "guarantor of 1 claimset on EntryLib" in r.text
    assert 'href="/p/2026.000001"' in r.text
    assert app_client.get("/people/0000-0002-1825-0097").status_code == 404
    assert app_client.get("/people/not-an-id").status_code == 404
