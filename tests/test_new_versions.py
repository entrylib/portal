"""A new version is made from the current version (design §4.3, *New versions*; portal issue #179): one that names an
older version in paper.based_on is refused, and what a new version removes is listed for the submitter and the
guarantor, so that a correction made from an older version is not published, unseen, as an undo of a later one."""

import json

from publishing import example
from test_consent import sign_in, submit
from test_notices import publish_one

JSON = {"Content-Type": "application/json"}


def new_version(concept, based_on=None, change="in every run", drop_scope=False):
    doc = example()
    doc["paper"]["id"] = concept
    doc["paper"]["correction_reason"] = f"The statement of the first claim now says it held {change}."
    doc["claims"][0]["statement"] = doc["claims"][0]["statement"].rstrip(".") + f" {change}."
    if based_on:
        doc["paper"]["based_on"] = based_on
    if drop_scope:
        next(c for c in doc["claims"] if c["id"] == "C2").pop("scope")
    return doc


def post(c, doc):
    return c.post("/api/submissions", content=json.dumps(doc).encode(), headers=JSON)


def test_a_new_version_made_from_an_older_one_is_refused(app_client):
    c = app_client
    concept = publish_one(c)
    out, token = submit(c, new_version(concept, based_on=f"{concept}@v1"))
    assert sign_in(c, token).status_code == 200
    assert c.get(f"/api/submissions/{out['id']}").json()["published"] == f"{concept}@v2"

    r = post(c, new_version(concept, based_on=f"{concept}@v1", change="in every run and every season"))
    assert r.status_code == 409, r.text
    assert f"{concept}@v1" in r.json()["error"] and "v2" in r.json()["error"]
    r = post(c, new_version(concept, based_on=f"{concept}@v2", change="in every run and every season"))
    assert r.status_code == 201, r.text


def test_what_a_new_version_removes_is_listed(app_client):
    c = app_client
    concept = publish_one(c)
    out, token = submit(c, new_version(concept, drop_scope=True))
    assert out["removals"] == ["scope: C2"]
    assert "does not say which version it was made from" in out["removals_note"]
    page = c.get(f"/consent/{token}").text
    assert "This new version removes" in page and "scope: C2" in page

    out, token = submit(c, new_version(concept, based_on=f"{concept}@v1", change="in every season", drop_scope=True))
    assert "does not say which version" not in out["removals_note"]
    assert f"It was made from {concept}@v1." in c.get(f"/consent/{token}").text


def test_a_new_version_that_removes_nothing_lists_nothing(app_client):
    c = app_client
    concept = publish_one(c)
    out, token = submit(c, new_version(concept, based_on=f"{concept}@v1"))
    assert "removals" not in out
    assert "This new version removes" not in c.get(f"/consent/{token}").text
