"""Publishing confirmed submissions (design §4.2 steps 6–7, §5).

Runs after each confirmation and on the app's periodic loop, so a submission confirmed while the portal restarted
is still published. Two modes:

- **local** (no `remote` given): the version is committed to the local registry and indexed at once.
- **github** (`remote` is a RemoteRegistry): the version is proposed as a registry pull request (state
  `publishing`); later rounds merge it once the registry's checks pass, index it and ask Software Heritage to
  archive it, or mark the submission refused when the checks fail.
"""

import logging
from pathlib import Path

from . import notices
from .archive import archive_version
from .classify import ClassifierError
from .indexer import index_version
from .publish import PublishError, prepare, publish
from .registry import tag_name

log = logging.getLogger("portal")

#: One publisher at a time across the app's threads and processes (a PostgreSQL advisory lock).
PUBLISH_LOCK = 4_242_001


def publish_confirmed(conn, *, settings, registry, store, classifier, remote=None, archive=None):
    """Publish what can be published, and apply confirmed retractions and removals. Returns [(submission ID,
    published ID or None)] for the submissions published or refused in this round, and [(request ID, state)] for
    the notices; [] at once if another publisher is running, which then does it."""
    if not conn.execute("SELECT pg_try_advisory_lock(%s)", (PUBLISH_LOCK,)).fetchone()[0]:
        return []
    try:
        if remote is None:
            done = _publish_local(conn, settings=settings, registry=registry, store=store, classifier=classifier)
        else:
            done = _settle_open(conn, settings=settings, remote=remote, archive=archive)
            done += _open_new(conn, settings=settings, remote=remote, store=store, classifier=classifier)
        try:                                        # retractions and removals (notices.py), in the same round
            done += notices.apply_confirmed(conn, registry=registry, published_dir=settings.published_dir,
                                            base_url=settings.base_url, remote=remote)
        except Exception:
            log.exception("applying retractions and removals failed; will retry")
        return done
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (PUBLISH_LOCK,))


def _confirmed(conn):
    return conn.execute("SELECT id, file_name, kind, target, pending_id FROM submissions WHERE state = 'confirmed'"
                        " AND file_name IS NOT NULL ORDER BY received").fetchall()


def _refuse(conn, sid, path, exc_or_text):
    if isinstance(exc_or_text, PublishError):
        detail = str(exc_or_text) + "".join(f"; {e['rule']} {e['where']}: {e['message']}"
                                            for e in exc_or_text.errors[:5])
    else:
        detail = exc_or_text
    conn.execute("UPDATE submissions SET state = 'refused', detail = %s, file_name = NULL, client_ip = NULL"
                 " WHERE id = %s",
                 (detail, sid))
    if path:
        path.unlink(missing_ok=True)


def _published(conn, sid, path, published_id):
    conn.execute("UPDATE submissions SET state = 'published', published_id = %s, file_name = NULL, client_ip = NULL"
                 " WHERE id = %s",
                 (published_id, sid))
    if path:
        path.unlink(missing_ok=True)
    log.info("published %s as %s", sid, published_id)


def _publish_local(conn, *, settings, registry, store, classifier):
    done = []
    for sid, file_name, _, _, _ in _confirmed(conn):
        path = Path(settings.submissions_dir) / file_name
        try:
            concept, version = publish(path, conn=conn, registry=registry, store=store, classifier=classifier,
                                       published_dir=settings.published_dir, base_url=settings.base_url)
        except PublishError as exc:
            _refuse(conn, sid, path, exc)
            done.append((sid, None))
            continue
        except ClassifierError as exc:
            # Expected while the classifier is down or starting: one line, no traceback; the next round retries.
            log.warning("publishing %s waits for the classifier (%s); will retry", sid, exc)
            continue
        except Exception:
            # Anything else (the registry, the file store) is unexpected: log it in full; the next round retries.
            log.exception("publishing %s failed; will retry", sid)
            continue
        _published(conn, sid, path, f"{concept}@v{version}")
        done.append((sid, f"{concept}@v{version}"))
    return done


def _open_new(conn, *, settings, remote, store, classifier):
    """Propose every confirmed submission as a registry pull request."""
    done = []
    busy = {r[0] for r in conn.execute("SELECT target FROM submissions WHERE state = 'publishing'"
                                       " AND target IS NOT NULL")}
    try:
        remote.sync()
    except Exception:
        log.exception("cannot bring the registry clone up to date; will retry")
        return done
    for sid, file_name, kind, target, pending_id in _confirmed(conn):
        if kind == "correction" and target in busy:
            continue                                # one version of a claimset in flight at a time
        path = Path(settings.submissions_dir) / file_name
        try:
            prep = prepare(path, conn=conn, registry=remote.registry, store=store, classifier=classifier,
                           concept=pending_id)
        except PublishError as exc:
            _refuse(conn, sid, path, exc)
            done.append((sid, None))
            continue
        except ClassifierError as exc:
            log.warning("publishing %s waits for the classifier (%s); will retry", sid, exc)
            continue
        if kind == "new" and pending_id is None:
            conn.execute("UPDATE submissions SET pending_id = %s WHERE id = %s", (prep.concept, sid))
        body = (f"Publication of `{prep.published_id}`, confirmed by its guarantor on EntryLib.\n\n"
                f"Opened by the EntryLib portal; merged by it when the registry checks pass.")
        try:
            opened = remote.open(prep, body)
        except Exception:
            log.exception("opening the registry pull request for %s failed; will retry", sid)
            continue
        conn.execute("UPDATE submissions SET state = 'publishing', registry_pr = %s, registry_branch = %s,"
                     " registry_version = %s, pending_id = %s WHERE id = %s",
                     (opened.number, opened.branch, prep.version, prep.concept, sid))
        if kind == "correction":
            busy.add(target)
        log.info("proposed %s as %s in registry pull request #%d", sid, prep.published_id, opened.number)
    return done


def _settle_open(conn, *, settings, remote, archive):
    """Merge, or close, the registry pull requests whose checks have finished."""
    done = []
    rows = conn.execute("SELECT id, file_name, pending_id, registry_pr, registry_branch, registry_version"
                        " FROM submissions WHERE state = 'publishing' ORDER BY received").fetchall()
    for sid, file_name, concept, number, branch, version in rows:
        from .ids import folder as folder_of
        folder = folder_of(concept)
        published_id = f"{concept}@v{version}"
        path = Path(settings.submissions_dir) / file_name if file_name else None
        try:
            outcome, reason = remote.settle(number, branch, f"Publish {published_id}",
                                           tag_name(folder, version))
        except Exception:
            log.exception("checking registry pull request #%s for %s failed; will retry", number, sid)
            continue
        if outcome == "waiting":
            continue
        if outcome == "failed":
            _refuse(conn, sid, path, f"not published: {reason}")
            log.warning("registry pull request #%s for %s failed: %s", number, sid, reason)
            done.append((sid, None))
            continue
        index_version(conn, remote.registry, folder, version, settings.published_dir, settings.base_url)
        _published(conn, sid, path, published_id)
        done.append((sid, published_id))
        if archive is not None:
            try:
                archive(remote.registry.read(folder, version))
            except Exception:  # noqa: BLE001 - archiving is best effort
                log.exception("Software Heritage requests for %s failed", published_id)
    return done


def default_archive(settings):
    """Software Heritage requests for the registry on GitHub and the repositories a version links to."""
    url = f"https://github.com/{settings.github_registry}"
    return lambda doc: archive_version(doc, url)
