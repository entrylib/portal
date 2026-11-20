"""What a pending submission's pages show, made once (design §4.2): the file as it will be published (with the
platform's verifiability, which takes a full validation) and its preview scores (the rubric), kept on disk until the
submission's window ends.

A pending submission's file does not change: it is named by its checksum (the `sha256` the submission records), and
what is kept is made again only when the installed claimset package or rubric changes. Before, Your submissions, the
consent page and the preview validated and scored the file on every visit: 7.5 seconds for a simulation study.

Kept under <submissions>/views/: <sha256>.<what>.json. A stale entry (a package since updated, a submission since
closed) is never read and is removed by prune(), with the expiry of submissions.
"""

import datetime as dt
import json
import os
import time
from pathlib import Path

from . import scores, site

FOLDER = "views"
#: How long an entry is kept: a submission waits 48 hours.
KEEP = dt.timedelta(days=3)


def _stamp():
    return f"claimset {site.claimset_fingerprint()} rubric {scores.version()}"


def _path(submissions_dir, sha256, what):
    return Path(submissions_dir) / FOLDER / f"{sha256}.{what}.json"


def _read(path):
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return held if isinstance(held, dict) and held.get("stamp") == _stamp() and "value" in held else None


def _keep(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"stamp": _stamp(), "value": value}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def kept(submissions_dir, sha256, what, make):
    """The value `make()` gives for this submission's file, made once while the package and rubric stay the same.
    Without a checksum (an old row) it is made each time."""
    if not sha256:
        return make()
    path = _path(submissions_dir, sha256, what)
    held = _read(path)
    if held is not None:
        return held["value"]
    value = make()
    try:
        _keep(path, value)
    except (OSError, TypeError, ValueError):             # serving matters more than keeping
        pass
    return value


def preview_scores(conn, submissions_dir, ctx):
    """The scores of a pending submission's preview (scores.compute), kept."""
    if not ctx or not ctx.get("doc"):
        return None
    return kept(submissions_dir, ctx.get("sha256"), "scores", lambda: scores.compute(conn, ctx["doc"]))


def prune(submissions_dir, now=None):
    """Remove entries older than KEEP."""
    folder = Path(submissions_dir) / FOLDER
    if not folder.is_dir():
        return
    limit = (now or time.time()) - KEEP.total_seconds()
    for f in folder.iterdir():
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass
