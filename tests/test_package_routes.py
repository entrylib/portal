"""How a package reaches the portal from an agent that talks to it through MCP (design §4.4): never in the tool call.
An upload address (upload_url, then a PUT of the zip, then upload_id), or the package attached by the guarantor on the
consent page (package_with_consent). Base64 is not accepted."""

import datetime as dt
import json
import urllib.parse

import psycopg
from claimset.package import build
from test_consent import GUARANTOR, sign_in
from test_mcp import call, data
from test_submissions import with_packaged_file

from portal import ratelimit


def package_of(tmp_path):
    """(the claimset with a packaged file, the zip `claimset package` builds of it)."""
    path = with_packaged_file(tmp_path)
    zip_path = tmp_path / "paper.zip"
    build(str(path), str(zip_path))
    return json.loads(path.read_text()), zip_path


# ---------- upload addresses ----------

def test_a_package_by_upload_address(app_client, settings, tmp_path):
    doc, zip_path = package_of(tmp_path)
    up = data(app_client, "upload_url")
    assert up["method"] == "PUT" and up["url"].endswith(up["upload_id"]) and "curl" in up["how"]
    path = urllib.parse.urlparse(up["url"]).path
    err, text = call(app_client, "validate", upload_id=up["upload_id"])
    assert err and "nothing has been sent" in text
    r = app_client.put(path, content=zip_path.read_bytes())
    assert r.status_code == 200 and r.json()["received"] is True, r.text
    assert app_client.put(path, content=b"again").status_code == 404           # single use
    assert data(app_client, "validate", upload_id=up["upload_id"])["valid"] is True
    assert data(app_client, "validate", upload_id=up["upload_id"])["valid"] is True   # kept for another check
    out = data(app_client, "submit", upload_id=up["upload_id"])
    assert out["state"] == "pending" and out["consent"] and "waiting_for" not in out
    err, text = call(app_client, "submit", upload_id=up["upload_id"])          # used up by the submission
    assert err and "no such upload" in text
    assert not list((settings.submissions_dir / "uploads").glob("*"))


def test_an_upload_address_expires(app_client, settings):
    up = data(app_client, "upload_url")
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("UPDATE uploads SET expires = now() - interval '1 minute'")
    r = app_client.put(urllib.parse.urlparse(up["url"]).path, content=b"{}")
    assert r.status_code == 404 and "upload_url" in r.json()["error"]
    assert app_client.put("/api/uploads/up_unknown", content=b"{}").status_code == 404


def test_one_source_only_and_no_base64(app_client):
    err, text = call(app_client, "validate", claimset="{}", upload_id="up_x")
    assert err and "give one of" in text
    err, _ = call(app_client, "validate", claimset="{}", files=[{"path": "files/a.png", "base64": "AAAA"}])
    assert err                                                                  # a file has text, never base64


def test_upload_requests_count_against_their_own_limit():
    assert ratelimit.kind_of("PUT", "/api/uploads/up_x") == "upload"
    assert ratelimit.kind_of("POST", "/consent/tok/package") == "upload"
    assert ratelimit.kind_of("POST", "/confirm/package") == "upload"
    assert ratelimit.kind_of("GET", "/consent/tok") is None


# ---------- the package attached with consent ----------

def submit_waiting(c, doc):
    r = c.post("/api/submissions", params={"package_with_consent": "true"}, content=json.dumps(doc).encode(),
               headers={"Content-Type": "application/json"})
    assert r.status_code == 201, r.text
    out = r.json()
    return out, out["consent"][0]["consent_url"].rsplit("/", 1)[-1]


def test_the_guarantor_attaches_the_package_and_confirms(app_client, settings, tmp_path):
    doc, zip_path = package_of(tmp_path)
    r = app_client.post("/api/submissions", content=json.dumps(doc).encode(),
                        headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "70" in r.text                             # alone, without the flag: refused
    out, token = submit_waiting(app_client, doc)
    assert out["waiting_for"] == "package" and "files/results.csv" in out["package"]
    page = app_client.get(f"/consent/{token}").text
    assert "First, attach the package" in page and "files/results.csv" in page
    assert "Sign in with ORCID and confirm" not in page
    r = sign_in(app_client, token)                                             # confirming waits for the package
    assert "waits for its package" in r.text
    assert app_client.get(f"/api/submissions/{out['id']}").json()["state"] == "pending"

    def attach(content, name="paper.zip"):
        return app_client.post(f"/consent/{token}/package", files={"package": (name, content, "application/zip")})
    r = attach(json.dumps(doc).encode(), "paper.json")
    assert r.status_code == 400 and "the zip that" in r.text
    other = dict(doc, paper=dict(doc["paper"], title="Another paper altogether"))
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    (other_dir / "files").mkdir()
    (other_dir / "files" / "results.csv").write_text("lab_result,value\nRS1,0.5\n")
    (other_dir / "paper.claimset.json").write_text(json.dumps(other))
    build(str(other_dir / "paper.claimset.json"), str(other_dir / "other.zip"))
    r = attach((other_dir / "other.zip").read_bytes())
    assert r.status_code == 400 and "another claimset" in r.text
    r = attach(zip_path.read_bytes())
    assert r.status_code == 303 and r.headers["location"].endswith(f"/consent/{token}?attached=1")
    page = app_client.get(f"/consent/{token}?attached=1").text
    assert "The package is attached" in page and "Sign in with ORCID and confirm" in page
    s = app_client.get(f"/api/submissions/{out['id']}").json()
    assert "waiting_for" not in s
    assert [p.suffix for p in settings.submissions_dir.glob(f"{out['id']}.*")] == [".zip"]
    r = sign_in(app_client, token)
    assert r.status_code == 200 and "published as entrylib:" in r.text, r.text
    published = app_client.get(f"/api/submissions/{out['id']}").json()["published"]
    key = published.split(":", 1)[1].split("@")[0]
    files = list((settings.published_dir).rglob("results.csv"))
    assert files and (settings.published_dir / "p" / f"{key}.json").exists()   # published with its file


def test_attach_and_confirm_from_the_confirm_listing(app_client, tmp_path):
    doc, zip_path = package_of(tmp_path)
    out, _ = submit_waiting(app_client, doc)
    r = app_client.get("/confirm/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    page = app_client.get("/consent/callback", params={"state": state, "code": GUARANTOR}).text
    assert "Attach the package to confirm" in page and 'action="/confirm/package"' in page
    ticket = page.split('name="ticket" value="')[1].split('"')[0]
    r = app_client.post("/confirm/package", data={"ticket": ticket},
                        files={"package": ("paper.zip", zip_path.read_bytes(), "application/zip")})
    assert r.status_code == 200 and "The package is attached and you have confirmed" in r.text, r.text
    assert app_client.get(f"/api/submissions/{out['id']}").json()["state"] in ("confirmed", "publishing",
                                                                               "published")


def test_the_flag_changes_nothing_for_a_claimset_without_files(app_client):
    from publishing import example
    out, token = submit_waiting(app_client, example())
    assert "waiting_for" not in out and "package" not in out
    assert "Sign in with ORCID and confirm" in app_client.get(f"/consent/{token}").text


def test_an_expired_waiting_submission_is_deleted(app_client, settings, tmp_path):
    from portal import submissions
    doc, _ = package_of(tmp_path)
    out, _ = submit_waiting(app_client, doc)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        assert out["id"] in submissions.expire(conn, settings.submissions_dir,
                                               now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=49))
    assert not list(settings.submissions_dir.glob(f"{out['id']}.*"))
