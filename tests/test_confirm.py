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
    assert '<section class="cs-section" id="published"><h2>Published</h2>' in page
    assert 'href="/p/2026.000001"' in page and f'href="/people/{GUARANTOR}"' in page
    # in the order a guarantor acts on them, with a menu of them and how many each holds
    order = [page.index(f'<section class="cs-section" id="{s}">') for s in ("waiting", "published", "closed")]
    assert order == sorted(order)
    # the contents of every page, to the right of the text as on the paper view, with Top; the sections stay open
    assert '<div class="entry-rail"><nav class="cs-toc"' in page and 'data-view="paper"' in page
    assert '<article class="cs-body" data-open>' in page
    menu = page[page.index('<nav class="cs-toc"'):page.index("</nav>", page.index('class="cs-toc'))]
    assert "On this page" in menu and 'href="#top">\u2191 Top</a>' in menu
    assert '<a href="#closed">Closed in the last 14 days</a> <span class="count">1</span>' in menu
    # Waiting for you and Published open the list of their papers by name; the arrow leads to the section
    for sid, title in (("waiting", "Waiting for you"), ("published", "Published")):
        assert (f'<li class="pv-toc-sec"><details><summary>{title} <span class="count">1</span></summary>'
                '<ol class="pv-toc pub-toc">') in menu
        assert f'<a class="pv-toc-go" href="#{sid}"' in menu
    [waiting] = re.findall(r'<section class="pending" id="([^"]+)"><h2>([^<]*)</h2>', page)
    assert f'<a href="#{waiting[0]}">{waiting[1]}</a>' in menu
    assert '<li id="pub-2026.000001">' in page and '<a href="#pub-2026.000001">' in menu
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


def _without_bar(html_):
    """A preview page without its bar, and with the addresses of its two views made the same."""
    html_ = re.sub(r'<div class="preview-bar".*?</div>(</div>)?(?=<div class="cs-page)', "", html_, flags=re.S)
    return re.sub(r'href="/(consent/[^"?#]+|submissions/[^"/]+/preview)(\?view=record)?(#[^"]*)?"',
                  r'href="VIEW\2\3"', html_)


def test_the_preview_opens_with_the_session(app_client):
    """Open the preview, from Your submissions, is the consent link's page: the same in all but its bar, whose blue
    button confirms (the guarantor has signed in already) and whose white one leads back to Your submissions."""
    out, token = submit(app_client)
    url = f"/submissions/{out['id']}/preview"
    r = app_client.get(url, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/submissions"            # not signed in
    consent_page = app_client.get(f"/consent/{token}").text
    signed_in(app_client)
    r = app_client.get(url)
    assert r.status_code == 200 and "Preview, not published yet." in r.text and 'data-view="paper"' in r.text
    assert _without_bar(r.text) == _without_bar(consent_page)                       # the same page
    bar = r.text[r.text.index('<div class="preview-bar"'):r.text.index('<div class="cs-page')]
    assert '<form method="post" action="/confirm"><input type="hidden" name="ticket"' in bar
    assert '<button type="submit" name="action" value="confirm">Confirm and publish</button>' in bar
    assert f'<a class="button-quiet" href="/submissions#{out["id"]}">Back to submissions</a>' in bar
    assert "Confirm: sign in with ORCID" not in r.text
    ticket = re.search(r'name="ticket" value="([^"]+)"', bar).group(1)
    assert f'href="{url}?view=record"' in r.text
    assert 'id="principal"' in app_client.get(f"{url}?view=record").text            # the record
    assert "Published" in app_client.post("/confirm", data={"ticket": ticket, "action": "confirm"}).text
    assert app_client.get(url).status_code == 404                                    # confirmed: no longer waiting


def test_someone_else_gets_no_preview(app_client):
    out, _ = submit(app_client)
    signed_in(app_client, as_orcid="0000-0002-1825-0097")
    assert app_client.get(f"/submissions/{out['id']}/preview").status_code == 404


def test_your_submissions_may_run_the_sites_script(app_client):
    """page.js makes the contents a bar on a phone (design §4.2): the page's policy lets the site's own script run,
    and nothing else; signed in or not."""
    for r in (sign_in_at(app_client, "submissions"), signed_in(app_client), app_client.get("/submissions")):
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp, csp
        assert 'src="/page.js' in r.text


def test_a_preview_waiting_for_its_package_leads_to_its_form():
    import datetime as dt

    from publishing import example

    from portal import pages
    ctx = {"submission": "sub_x", "orcid": GUARANTOR, "name": "A. Researcher", "state": "pending", "kind": "new",
           "target": None, "expires": dt.datetime(2026, 11, 26, 12, 0), "doc": example(), "licence": "CC-BY-4.0",
           "ticket": "T1", "removals": [], "source": None, "waiting_package": True, "package_files": ["data.csv"]}
    html_ = pages.session_preview(ctx, base_url="https://entrylib.test")
    bar = html_[html_.index('<div class="preview-bar"'):html_.index('<div class="cs-page')]
    assert '<a class="button" href="#attach">First, attach the package</a>' in bar and "Back to submissions" in bar
    attach = html_[html_.index('<div id="attach">'):]
    assert 'action="/confirm/package"' in attach and 'name="ticket" value="T1"' in attach
