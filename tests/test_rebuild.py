"""The rebuild of the pages after an update runs behind the app's back (design §10): the app answers at once, the
publisher waits for the rebuild, and what was confirmed meanwhile is published when it ends."""

import threading
import time

import psycopg
from fastapi.testclient import TestClient
from publishing import BASE, example, write

from portal import cli, indexer, worker
from portal.app import create_app
from portal.db import make_pool, migrate
from portal.publish import publish


def test_a_rebuild_is_due_when_the_claimset_or_the_site_changed(env):
    ctx, tmp = env
    out = ctx["published_dir"]
    assert indexer.rebuild_due(out, "0.44.5")                              # written by none
    assert indexer.refresh_if_claimset_changed(ctx["conn"], ctx["registry"], out, BASE, "0.44.5")
    assert not indexer.rebuild_due(out, "0.44.5")
    assert indexer.rebuild_due(out, "0.44.6")                              # another claimset
    (out / indexer.RENDERED_BY).write_text("0.44.5 site other\n")
    assert indexer.rebuild_due(out, "0.44.5")                              # another state of the site's code


def test_the_fixed_pages_do_not_wait_for_the_rebuild(env):
    ctx, tmp = env
    out = ctx["published_dir"]
    indexer.write_site(ctx["conn"], out, BASE)
    assert (out / "site.css").exists() and (out / "llms.txt").exists() and (out / "index.jsonl").exists()
    assert indexer.rebuild_due(out, "0.44.5")                              # and the rebuild is still to do


def test_the_publisher_waits_for_a_rebuild(env, database_url):
    ctx, tmp = env
    other = psycopg.connect(database_url, autocommit=True)
    try:
        def free():
            got = other.execute("SELECT pg_try_advisory_lock(%s)", (indexer.PUBLISH_LOCK,)).fetchone()[0]
            if got:
                other.execute("SELECT pg_advisory_unlock(%s)", (indexer.PUBLISH_LOCK,))
            return got
        assert worker.PUBLISH_LOCK == indexer.PUBLISH_LOCK                 # one lock for both
        with indexer.publishing(ctx["conn"]):
            assert not free()
            # a round of the publisher that starts meanwhile publishes nothing and leaves it to the next
            assert worker.publish_confirmed(other, settings=None, registry=None, store=None, classifier=None) == []
        assert free()

        # and a rebuild waits for a round that is running
        other.execute("SELECT pg_advisory_lock(%s)", (indexer.PUBLISH_LOCK,))
        entered = threading.Event()

        def rebuild():
            with indexer.publishing(ctx["conn"]):
                entered.set()
        thread = threading.Thread(target=rebuild)
        thread.start()
        assert not entered.wait(0.4)
        other.execute("SELECT pg_advisory_unlock(%s)", (indexer.PUBLISH_LOCK,))
        thread.join(5)
        assert entered.is_set()
    finally:
        other.close()


def test_the_app_answers_while_it_rebuilds_and_publishes_after(settings, monkeypatch):
    migrate(settings.database_url)
    pool = make_pool(settings.database_url, min_size=1, max_size=3)
    pool.open()
    started, release, published = threading.Event(), threading.Event(), []

    def after_start():
        started.set()
        assert release.wait(10)

    def round_of_the_publisher(conn, **parts):
        published.append(indexer.REBUILDING.is_set())
        return []
    monkeypatch.setattr(worker, "publish_confirmed", round_of_the_publisher)
    parts = {"registry": None, "store": None, "classifier": None}
    try:
        app = create_app(settings, pool=pool, run_expiry=False, after_start=after_start, publisher=parts)
        with TestClient(app) as client:
            assert started.wait(5)
            answer = client.get("/healthz")                                # the app answers while the work runs
            assert answer.status_code == 200 and answer.json()["rebuilding"] is True
            assert published == []
            release.set()
            for _ in range(100):
                if published:
                    break
                time.sleep(0.05)
            assert published == [False]                                    # a round of the publisher, once it ended
            assert "rebuilding" not in client.get("/healthz").json()
        plain = create_app(settings, pool=pool, run_expiry=False)
        with TestClient(plain) as client:
            assert "rebuilding" not in client.get("/healthz").json()       # nothing to rebuild: nothing said
    finally:
        indexer.REBUILDING.clear()
        pool.close()


def test_the_start_prepares_and_leaves_the_rebuild_for_later(settings, capsys, tmp_path):
    migrate(settings.database_url)
    assert cli._prepare(settings, "0.44.5") is True                        # nothing rendered yet
    assert (settings.published_dir / "llms.txt").exists()
    assert not (settings.published_dir / indexer.RENDERED_BY).exists()     # the rebuild itself has not run
    cli._refresh(settings, "0.44.5", locked=True)
    out = capsys.readouterr().out
    assert "portal: registry ready in" in out and "reading views rebuilt with claimset 0.44.5 in" in out
    assert cli._prepare(settings, "0.44.5") is False
    assert "portal: pages up to date" in capsys.readouterr().out
    with psycopg.connect(settings.database_url, autocommit=True) as conn:  # and the lock is free again
        assert conn.execute("SELECT pg_try_advisory_lock(%s)", (indexer.PUBLISH_LOCK,)).fetchone()[0]


def test_a_rebuild_behind_the_app_gives_the_same_pages(env):
    ctx, tmp = env
    publish(write(tmp, example()), **ctx)
    out = ctx["published_dir"]
    before = (out / "p" / "2026.000001.html").read_bytes()
    with indexer.publishing(ctx["conn"]):                                  # the lock is held by the rebuild's own
        indexer.reindex(ctx["conn"], ctx["registry"], out, BASE)           # connection
    assert (out / "p" / "2026.000001.html").read_bytes() == before
