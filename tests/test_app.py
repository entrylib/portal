import claimset
from fastapi.testclient import TestClient

from portal import __version__
from portal.app import create_app
from portal.config import Settings
from portal.db import make_pool


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"portal": __version__, "claimset": claimset.__version__, "spec": claimset.SPEC_VERSION,
                        "database": "ok"}


def test_healthz_reports_an_unreachable_database():
    url = "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1"
    pool = make_pool(url, min_size=0, max_size=1)
    pool.open()
    try:
        with TestClient(create_app(Settings.from_env({"DATABASE_URL": url}), pool=pool)) as c:
            r = c.get("/healthz")
        assert r.status_code == 503
        assert r.json()["database"].startswith("unavailable")
    finally:
        pool.close()


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "EntryLib" in r.text and "/llms.txt" in r.text


def test_api_docs(client):
    assert client.get("/api/openapi.json").status_code == 200


def test_the_version_is_set_once():
    # CLAUDE.md: every change to the application raises the version, in pyproject.toml and in __version__, kept equal.
    import tomllib
    from pathlib import Path

    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())["project"]
    assert project["version"] == __version__
