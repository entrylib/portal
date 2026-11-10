"""Publication through registry pull requests (github mode), with GitHub played by a fake backed by a bare repo."""

import json
import subprocess
import tempfile
import urllib.parse

import psycopg
import pytest
from fastapi.testclient import TestClient
from publishing import example, fake_classifier
from test_consent import GUARANTOR, FakeOrcid, titled

from portal import archive, worker
from portal.app import create_app
from portal.config import Settings
from portal.db import make_pool, migrate
from portal.github import GitHubApp, RemoteRegistry
from portal.registry import Registry
from portal.storage import FileStore


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


class FakeGitHub:
    """Pull requests on a bare repository; check runs are set by the test."""

    def __init__(self, bare):
        self.bare = bare
        self.pulls = {}
        self.runs = {}                       # branch -> [check run]
        self.comments = []

    def git_env(self):
        return {}

    def create_pull(self, head, title, body, base="main"):
        n = len(self.pulls) + 1
        self.pulls[n] = {"head": head, "title": title, "state": "open", "merged": False, "merge_sha": None}
        return n

    def find_pull(self, head):
        return next((n for n, p in self.pulls.items() if p["head"] == head and p["state"] == "open"), None)

    def pull(self, n):
        p = self.pulls[n]
        head_sha = git(self.bare, "rev-parse", f"refs/heads/{p['head']}") if not p["merged"] else p["merge_sha"]
        return {"state": p["state"], "merged": p["merged"], "head_sha": head_sha, "merge_sha": p["merge_sha"],
                "url": f"https://github.com/entrylib/registry/pull/{n}"}

    def checks(self, sha):
        branch = next(p["head"] for p in self.pulls.values() if p["state"] == "open")
        return self.runs.get(branch, [])

    def merge(self, n, sha, title):
        p = self.pulls[n]
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "clone", "-q", str(self.bare), tmp], check=True)
            git(tmp, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--squash", f"origin/{p['head']}")
            git(tmp, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", title)
            git(tmp, "push", "-q", "origin", "main")
            sha = git(tmp, "rev-parse", "HEAD")
        p.update(state="closed", merged=True, merge_sha=sha)
        return sha

    def close(self, n, comment=None):
        self.comments.append(comment)
        self.pulls[n]["state"] = "closed"

    def delete_branch(self, branch):
        subprocess.run(["git", "-C", str(self.bare), "update-ref", "-d", f"refs/heads/{branch}"], check=True)

    def tag(self, name, sha):
        subprocess.run(["git", "-C", str(self.bare), "tag", name, sha], check=True)

    def set_checks(self, conclusion, summary=""):
        branch = next(p["head"] for p in self.pulls.values() if p["state"] == "open")
        self.runs[branch] = [{"name": "check", "status": "completed", "conclusion": conclusion, "summary": summary,
                              "url": None}]


@pytest.fixture
def world(database_url, tmp_path):
    bare = tmp_path / "registry.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("The EntryLib registry\n")
    git(seed, "add", "README.md")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    git(seed, "push", "-q", "origin", "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True)

    settings = Settings.from_env({
        "DATABASE_URL": database_url, "PORTAL_PUBLISHED_DIR": str(tmp_path / "published"),
        "PORTAL_SUBMISSIONS_DIR": str(tmp_path / "submissions"), "PORTAL_REGISTRY_DIR": str(clone),
        "PORTAL_BASE_URL": "https://entrylib.test", "PORTAL_REGISTRY_MODE": "github"})
    migrate(database_url)
    gh = FakeGitHub(bare)
    registry = Registry(clone)
    archived = []
    publisher = {"registry": registry, "store": FileStore(settings.published_dir, settings.base_url),
                 "classifier": fake_classifier, "remote": RemoteRegistry(registry, gh),
                 "archive": lambda doc: archived.append(doc["paper"]["id"])}
    pool = make_pool(database_url, min_size=1, max_size=3)
    pool.open()
    app = create_app(settings, pool=pool, run_expiry=False, orcid=FakeOrcid(), publisher=publisher)
    with TestClient(app, follow_redirects=False) as client:
        yield {"client": client, "gh": gh, "bare": bare, "settings": settings, "publisher": publisher,
               "archived": archived, "pool": pool}
    pool.close()


def submit_and_confirm(c, doc=None):
    r = c.post("/api/submissions", content=json.dumps(doc or example()).encode(),
               headers={"Content-Type": "application/json"})
    assert r.status_code == 201, r.text
    out = r.json()
    token = out["consent"][0]["consent_url"].rsplit("/", 1)[-1]
    r = c.get(f"/consent/{token}/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    page = c.get("/consent/callback", params={"state": state, "code": GUARANTOR})
    assert page.status_code == 200, page.text
    return out["id"]


def round_(w):
    with w["pool"].connection() as conn:
        return worker.publish_confirmed(conn, settings=w["settings"], **w["publisher"])


def status(w, sid):
    return w["client"].get(f"/api/submissions/{sid}").json()


def test_a_version_is_published_through_a_pull_request(world):
    w = world
    sid = submit_and_confirm(w["client"])
    s = status(w, sid)
    assert s["state"] == "publishing"
    assert s["registry_pull_request"] == "https://github.com/entrylib/registry/pull/1"
    assert "publish/entrylib_2026.000001-v1" in git(w["bare"], "branch")
    assert "2026" not in git(w["bare"], "ls-tree", "--name-only", "main")      # main is untouched

    assert round_(w) == []                                       # no checks yet: waiting
    w["gh"].set_checks("success")
    assert round_(w) == [(sid, "entrylib:2026.000001@v1")]
    s = status(w, sid)
    assert s["state"] == "published" and s["published"] == "entrylib:2026.000001@v1"
    assert "2026/000/entrylib_2026.000001/v1/claimset.json" in git(w["bare"], "ls-tree", "-r", "--name-only", "main")
    assert git(w["bare"], "tag") == "entrylib_2026.000001-v1"
    assert git(w["bare"], "log", "-1", "--format=%s", "main") == "Publish entrylib:2026.000001@v1"
    assert "publish/" not in git(w["bare"], "branch")                                      # branch deleted
    assert (w["settings"].published_dir / "p" / "2026.000001.json").exists()
    assert w["archived"] == ["entrylib:2026.000001"]


def test_failed_checks_refuse_and_the_number_is_not_given_again(world):
    w = world
    sid = submit_and_confirm(w["client"])
    w["gh"].set_checks("failure", "validator rule 2: claims:C1.support: at least one support entry")
    round_(w)
    s = status(w, sid)
    assert s["state"] == "refused" and "registry checks failed" in s["detail"] and "rule 2" in s["detail"]
    assert w["gh"].pulls[1]["state"] == "closed" and "Not published" in w["gh"].comments[0]
    assert "publish/" not in git(w["bare"], "branch")
    sid2 = submit_and_confirm(w["client"])
    assert status(w, sid2)["registry_pull_request"].endswith("/pull/2")
    assert "publish/entrylib_2026.000002-v1" in git(w["bare"], "branch")


def test_a_retried_round_keeps_its_number(world, monkeypatch):
    w = world
    remote = w["publisher"]["remote"]
    real_open = remote.open
    calls = []

    def flaky(prep, body):
        calls.append(prep.concept)
        if len(calls) == 1:
            raise OSError("GitHub unreachable")
        return real_open(prep, body)
    monkeypatch.setattr(remote, "open", flaky)
    sid = submit_and_confirm(w["client"])
    assert status(w, sid)["state"] == "confirmed"
    round_(w)
    assert calls == ["entrylib:2026.000001", "entrylib:2026.000001"]
    assert status(w, sid)["state"] == "publishing"
    with psycopg.connect(w["settings"].database_url) as conn:
        assert conn.execute("SELECT last FROM id_counters").fetchone()[0] == 1


def test_a_correction_waits_for_the_version_in_flight(world):
    w = world
    sid = submit_and_confirm(w["client"])
    w["gh"].set_checks("success")
    round_(w)
    concept = status(w, sid)["published"].split("@")[0]

    def correction(text):
        doc = example()
        doc["paper"]["id"] = concept
        doc["paper"]["correction_reason"] = text
        doc["claims"][0]["statement"] = doc["claims"][0]["statement"].rstrip(".") + f" ({text})."
        return doc
    first = submit_and_confirm(w["client"], correction("first fix"))
    second = submit_and_confirm(w["client"], correction("second fix"))
    assert status(w, first)["state"] == "publishing" and status(w, second)["state"] == "confirmed"
    w["gh"].set_checks("success")
    round_(w)
    assert status(w, first)["published"] == f"{concept}@v2"
    assert status(w, second)["state"] == "publishing"
    w["gh"].set_checks("success")
    round_(w)
    assert status(w, second)["published"] == f"{concept}@v3"


def test_app_token_and_git_auth():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    gh = GitHubApp("12345", key, "entrylib/registry")
    calls = []

    def fake_call(method, path, body=None, auth=None):
        calls.append((method, path, auth.split()[0] if auth else None))
        return {"id": 99} if path.endswith("/installation") else {"token": "ghs_abc"}
    gh._call = fake_call
    assert gh.token() == "ghs_abc" and gh.token() == "ghs_abc"           # cached
    assert [c[:2] for c in calls] == [("GET", "/repos/entrylib/registry/installation"),
                                      ("POST", "/app/installations/99/access_tokens")]
    env = gh.git_env()
    assert "ghs_abc" not in json.dumps(env) and env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    import jwt
    claims = jwt.decode(gh._jwt(), options={"verify_signature": False})
    assert claims["iss"] == "12345" and claims["exp"] - claims["iat"] <= 600


def test_archive_repositories_and_failure():
    doc = example("published-native.json")
    doc["artefacts"] = [{"uri": "https://github.com/someone/study/tree/abc123/lab"},
                        {"uri": "https://gitlab.com/group/project.git"},
                        {"uri": "https://entrylib.org/files/abc"}]
    assert archive.repositories(doc) == ["https://github.com/someone/study", "https://gitlab.com/group/project"]

    def down(req, timeout):
        raise OSError("unreachable")
    assert archive.save("https://github.com/entrylib/registry", opener=down) is None
    seen = []
    archive.archive_version(doc, "https://github.com/entrylib/registry", save_fn=lambda u: seen.append(u))
    assert seen[0] == "https://github.com/entrylib/registry" and len(seen) == 3


def test_open_pull_requests_count_towards_the_weekly_limit(world, monkeypatch):
    from portal import limits
    monkeypatch.setattr(limits, "NEW_PER_WEEK", 2)
    w = world
    for n in range(2):
        assert status(w, submit_and_confirm(w["client"], titled(n)))["state"] == "publishing"
    r = w["client"].post("/api/submissions", content=json.dumps(titled("over")).encode(),
                         headers={"Content-Type": "application/json"})
    assert r.status_code == 429 and "the limit is reached" in json.dumps(r.json())
