"""`portal`: run the portal and its maintenance commands.

    portal migrate                 apply database migrations
    portal serve [--port 8000]     run the web app (after migrating)
    portal publish SUBMISSION      publish a validated submission (package or claimset file) directly,
                                            without consent: for administration and tests, never for authors
    portal reindex                 rebuild the database index and static files from the registry
    portal check [--registry DIR] [--base REF]
                                            the registry's checks on a pull request checked out at DIR (no database);
                                            exit 1 if they fail
"""

import argparse
import json
import os
import sys

from .config import Settings
from .db import migrate


def _context(settings):
    from .classify import HttpClassifier
    from .registry import Registry
    from .storage import FileStore
    registry = Registry(settings.registry_dir, settings.git_name, settings.git_email)
    if not settings.registry_dir.exists():
        registry.init()
    return registry, FileStore(settings.published_dir, settings.base_url), HttpClassifier(settings.classifier_url)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="portal")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    serve = sub.add_parser("serve", help="apply migrations, then run the web app")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    pub = sub.add_parser("publish", help="publish a submission directly, without consent (administration, tests)")
    pub.add_argument("submission", help="a submission package (BagIt zip or folder) or a claimset file")
    sub.add_parser("reindex", help="rebuild the database index and static files from the registry")
    sub.add_parser("requests", help="retraction and removal requests waiting for review")
    dec = sub.add_parser("decide", help="decide a retraction or removal request under review")
    dec.add_argument("request", help="the request's id (rq_...)")
    dec.add_argument("decision", choices=["apply", "decline"])
    dec.add_argument("--note", help="why (kept with the request; for a decline, the answer to the requester)")
    chk = sub.add_parser("check", help="the registry's checks on a pull request (no database)")
    chk.add_argument("--registry", default=".", help="the registry checkout, at the pull request's head")
    chk.add_argument("--base", default="origin/main", help="what the pull request is merged into")
    args = parser.parse_args(argv)
    import claimset

    from . import MIN_CLAIMSET, claimset_ok
    if not claimset_ok(claimset.__version__):
        print(f"portal: claimset {claimset.__version__} is older than {MIN_CLAIMSET}, the oldest the portal works "
              f"with; update it: pip install --upgrade claimset",
              file=sys.stderr)
        return 2
    if args.command == "check":
        return _check(args)
    settings = Settings.from_env()

    applied = migrate(settings.database_url)
    for name in applied:
        print(f"applied {name}")
    if args.command == "migrate":
        if not applied:
            print("database is up to date")
        return 0

    if args.command in ("requests", "decide"):
        return _requests(settings, args)

    if args.command in ("publish", "reindex"):
        import psycopg

        from .indexer import reindex
        from .publish import PublishError, publish
        registry, store, classifier = _context(settings)
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            if args.command == "reindex":
                registry = _rebuild_registry(settings) or registry
                folders = reindex(conn, registry, settings.published_dir, settings.base_url)
                print(f"reindexed {len(folders)} claimset(s)")
                return 0
            try:
                concept, version = publish(args.submission, conn=conn, registry=registry, store=store,
                                           classifier=classifier, published_dir=settings.published_dir,
                                           base_url=settings.base_url)
            except PublishError as exc:
                print(f"NOT PUBLISHED: {exc}", file=sys.stderr)
                for e in exc.errors:
                    print("  " + json.dumps(e, ensure_ascii=False), file=sys.stderr)
                return 1
            print(f"published {concept}@v{version}")
            return 0

    _refresh(settings, claimset.__version__)

    import uvicorn

    from .app import create_app
    # No access log: it would keep every reader's IP address (the privacy page says addresses are used in memory only).
    uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=True,
                forwarded_allow_ips="*", access_log=False)
    return 0


def _requests(settings, args):
    """List or decide the requests under review. An approved request is applied by the app's next round."""
    import psycopg

    from . import notices
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        if args.command == "requests":
            rows = conn.execute("SELECT id, received, concept_id, action, reason_code, statement, contact, grounds"
                                " FROM notice_requests WHERE state = 'review' ORDER BY received").fetchall()
            for rid, received, concept, action, reason, statement, contact, grounds in rows:
                print(f"{rid}  {received:%Y-%m-%d %H:%M}  {action} {concept}  ({notices.reason_label(reason)})")
                print(f"  from: {contact}")
                print(f"  statement (shown in the notice): {statement or '-'}")
                print("  grounds: " + (grounds or "-").replace("\n", "\n          "))
            if not rows:
                print("no requests waiting for review")
            return 0
        try:
            state = notices.decide(conn, args.request, args.decision == "apply", args.note)
        except notices.NoticeError as exc:
            print(f"portal: {exc}", file=sys.stderr)
            return 1
        print(f"{args.request}: {state}" + ("; the app applies it within ten minutes" if state == "confirmed" else ""))
        return 0


def _rebuild_registry(settings):
    """The registry a rebuild of the index reads. In github mode, the clone, first brought to the registry's main on
    GitHub, so that the index is never rebuilt from a copy behind the record (a failure to update raises, and nothing
    is rebuilt); otherwise the local registry, or None when nothing was published yet."""
    from .registry import Registry
    if settings.registry_mode == "github":
        from .github import ensure_clone, update_clone
        registry = ensure_clone(settings.registry_dir, settings.github_registry,
                                lambda path: Registry(path, settings.git_name, settings.git_email))
        update_clone(registry)
        return registry
    if (settings.registry_dir / ".git").exists():                 # nothing published before the registry exists
        return Registry(settings.registry_dir, settings.git_name, settings.git_email)
    return None


def _refresh(settings, version):
    """At start: rebuild the reading views if claimset changed since they were written. A failure is reported and
    the app starts anyway; the next start tries again."""
    import psycopg

    from .indexer import refresh_if_claimset_changed
    try:
        registry = _rebuild_registry(settings)
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            if refresh_if_claimset_changed(conn, registry, settings.published_dir, settings.base_url, version):
                print(f"reading views rebuilt with claimset {version}")
    except Exception as exc:  # noqa: BLE001 - serving matters more; the next start retries
        print(f"portal: could not rebuild the reading views: {type(exc).__name__}: {exc}", file=sys.stderr)


def _check(args):
    from .check import check
    result = check(args.registry, args.base)
    text = result.markdown()
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
