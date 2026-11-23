"""Confirming without the consent link (Your submissions, once /confirm): sign in with ORCID, see the submissions
naming you, confirm or cancel one."""

import re
import urllib.parse

from test_consent import GUARANTOR, submit, titled


def sign_in_at_confirm(c, as_orcid=GUARANTOR):
    return sign_in_at(c, "confirm", as_orcid)          # the old address leads to the same page


def tickets(page):
    """The tickets of a listing, once each (a submission's Confirm and Cancel forms carry the same one)."""
    return list(dict.fromkeys(re.findall(r'name="ticket" value="([^"]+)"', page)))


def confirm(c, ticket, action="confirm"):
    return c.post("/confirm", content=urllib.parse.urlencode({"ticket": ticket, "action": action}),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})


def sign_in_at(c, page, as_orcid=GUARANTOR):
    r = c.get(f"/{page}/start", follow_redirects=False)
    if r.status_code == 301:                              # /confirm/start -> /submissions/start
        r = c.get(r.headers["location"], follow_redirects=False)
    assert r.status_code == 303, r.text
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    return c.get("/consent/callback", params={"state": state, "code": as_orcid})


def test_the_page(app_client):
    r = app_client.get("/confirm", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/submissions"   # one page: Your submissions
    r = app_client.get("/confirm", follow_redirects=True)
    assert r.status_code == 200 and "Your submissions</h1>" in r.text and 'href="/submissions/start"' in r.text
    assert "confirm or cancel each" in r.text


def test_the_guarantor_confirms_without_the_link(app_client):
    out, _ = submit(app_client)
    assert app_client.get(f"/api/submissions/{out['id']}").json()["confirm_url"].endswith("/submissions")
    r = sign_in_at_confirm(app_client)
    assert r.status_code == 200 and "Waiting for you" in r.text and "Confirm and publish" in r.text
    assert "Cancel" in r.text and "Published</h2>" in r.text                      # the same page as /submissions
    [ticket] = tickets(r.text)
    r = confirm(app_client, ticket)
    assert r.status_code == 200 and "published as entrylib:" in r.text, r.text
    s = app_client.get(f"/api/submissions/{out['id']}").json()
    assert s["state"] == "published" and "confirm_url" not in s
    assert confirm(app_client, ticket).status_code == 400                          # used once
    assert "Nothing waits for your confirmation" in sign_in_at_confirm(app_client).text


def test_someone_else_sees_nothing(app_client):
    submit(app_client)
    r = sign_in_at_confirm(app_client, as_orcid="0000-0002-1825-0097")
    assert r.status_code == 200 and "Nothing waits for your confirmation" in r.text and not tickets(r.text)
    assert confirm(app_client, "made-up").status_code == 400


def test_a_listing_sign_in_is_used_once(app_client):
    submit(app_client)
    r = app_client.get("/submissions/start")
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
    assert "Nothing waits for your confirmation" in sign_in_at_confirm(app_client).text


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
    # in the order a guarantor acts on them, with a menu of them and how many each holds
    order = [page.index(f'<section id="{s}">') for s in ("waiting", "published", "closed")]
    assert order == sorted(order)
    menu = page[page.index('<nav class="cs-toc spec-toc"'):page.index("</nav>", page.index('class="cs-toc'))]
    for sid, title in (("waiting", "Waiting for you"), ("published", "Published"),
                       ("closed", "Closed in the last 14 days")):
        assert f'<a href="#{sid}">{title}</a> <span class="count">1</span>' in menu
    assert 'src="/page.js' in page
    # a published paper: identifier, version, date, claims, and its links
    row = page[page.index('<ul class="pub-list">'):page.index("</ul>", page.index('<ul class="pub-list">'))]
    for part in ("entrylib:2026.000001", "version 1", "version 1 · published", "1 claim, 1 principal", "Support ",
                 'href="/p/2026.000001/record">Record', 'href="/p/2026.000001.txt">Text for AI'):
        assert part in row, part
    other = sign_in_at(app_client, "submissions", as_orcid="0000-0002-1825-0097").text
    assert "Nothing waits for your confirmation" in other and "No paper names you" in other


def test_a_guarantors_page(app_client):
    """/people/<ORCID iD> (design §7.4): the published claimsets a person guarantees; their name links to it."""
    submit(app_client)
    [ticket] = tickets(sign_in_at_confirm(app_client).text)
    confirm(app_client, ticket)
    r = app_client.get(f"/people/{GUARANTOR}")
    assert r.status_code == 200 and "responsible researcher for 1 paper on EntryLib" in r.text
    assert 'href="/p/2026.000001"' in r.text
    assert app_client.get("/people/0000-0002-1825-0097").status_code == 404
    assert app_client.get("/people/not-an-id").status_code == 404


def signed_in(c, as_orcid=GUARANTOR):
    """Sign in at Your submissions and keep the session (the test client is http, so the cookie is set by hand)."""
    r = sign_in_at(c, "submissions", as_orcid)
    c.cookies.set("entrylib_session", r.headers["set-cookie"].split(";")[0].split("=", 1)[1])
    return r


def test_a_waiting_submission_reads_as_a_paper(app_client):
    """Design §4.2: its authors, size, summary and claims by name, then Open the preview before Confirm and publish."""
    from publishing import example
    doc = example()
    doc["paper"]["summary"] = "Retail sales are seasonal, and method M forecasts them better than N."
    doc["claims"][2]["name"] = "Method M improves accuracy"
    out, _ = submit(app_client, doc)
    page = signed_in(app_client).text
    card = page[page.index('<section class="pending"'):page.index("</section>")]
    for part in ("A. Researcher · with Example model 1.0<", "3 claims, 1 principal",
                 "<h3>Summary</h3>",
                 "Retail sales are seasonal", "<h3>Claims</h3>", "Method M improves accuracy",
                 "· principal", "Monthly retail sales series exhibit"):
        assert part in card, part
    assert "Principal claims:" not in card and "as models will read it" not in card
    assert card.index("Open the preview") < card.index("Confirm and publish")
    assert f'href="/submissions/{out["id"]}/preview"' in card and f'id="{out["id"]}"' in card


def test_the_preview_opens_with_the_session(app_client):
    out, _ = submit(app_client)
    url = f"/submissions/{out['id']}/preview"
    r = app_client.get(url, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/submissions"            # not signed in
    signed_in(app_client)
    r = app_client.get(url)
    assert r.status_code == 200 and "Preview, not published yet." in r.text and 'data-view="paper"' in r.text
    assert f'href="/submissions#{out["id"]}">Back to Your submissions' in r.text
    assert "Confirm: sign in with ORCID" not in r.text                               # confirming is on the list
    assert f'href="{url}?view=record"' in r.text
    assert 'id="principal"' in app_client.get(f"{url}?view=record").text            # the record
    app_client.post("/signout")
    signed_in(app_client, as_orcid="0000-0002-1825-0097")                            # someone else
    assert app_client.get(url).status_code == 404
