"""Tests that need PostgreSQL (with pgvector) read TEST_DATABASE_URL; without it they are skipped."""

import os

import psycopg
import pytest

from portal.config import Settings
from portal.db import make_pool, migrate

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def database_url():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:       # start each test from an empty schema
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    return TEST_DATABASE_URL


@pytest.fixture
def settings(database_url, tmp_path):
    return Settings.from_env({"DATABASE_URL": database_url, "PORTAL_PUBLISHED_DIR": str(tmp_path / "published"),
                              "PORTAL_SUBMISSIONS_DIR": str(tmp_path / "submissions"),
                              "PORTAL_REGISTRY_DIR": str(tmp_path / "registry"),
                              "PORTAL_BASE_URL": "https://entrylib.test"})


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from portal.app import create_app
    migrate(settings.database_url)
    pool = make_pool(settings.database_url, min_size=1, max_size=2)
    pool.open()
    try:
        with TestClient(create_app(settings, pool=pool, run_expiry=False)) as c:
            yield c
    finally:
        pool.close()


@pytest.fixture
def env(database_url, tmp_path):
    """A migrated database (an autocommit connection), a registry and a published directory, for publishing."""
    from publishing import BASE, TODAY, fake_classifier

    from portal.registry import Registry
    from portal.storage import FileStore
    migrate(database_url)
    conn = psycopg.connect(database_url, autocommit=True)
    published = tmp_path / "published"
    ctx = {"conn": conn, "registry": Registry(tmp_path / "registry").init(), "store": FileStore(published, BASE),
           "classifier": fake_classifier, "published_dir": published, "base_url": BASE, "today": TODAY}
    yield ctx, tmp_path
    conn.close()
