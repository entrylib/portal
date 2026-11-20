"""Reading a published lab record (design §5.2, *Reading a lab record*).

A lab record's log is for checking; people and models read its reading view and the trail of each claim, which the
claimset package makes from the log alone (lab record v0.23 §11). The portal makes them when it writes a version's
static files, from the registry's copy of the log, or else from the author's log at its commit-pinned URL, fetched
once. Fetching asks only github.com's raw file host, for a URL pinned to a full commit hash, and is turned off with
PORTAL_LAB_FETCH=0 (tests, offline use). Nothing here raises: a record that cannot be had or read gives no view.
"""

import json
import logging
import os
import re
import urllib.request

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"EntryLib/{__version__} (https://entrylib.org; mailto:mail@entrylib.org)"
TIMEOUT = 30
#: The largest log fetched, in bytes (as a package's largest file, claimset spec §2.5).
MAX_BYTES = 50 * 1024 * 1024
#: github.com/<owner>/<repo>/blob/<40-hex commit>/<path>: a log fixed at a commit.
GITHUB_BLOB = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/blob/([0-9a-f]{40})/(\S+)$")


def enabled():
    return os.environ.get("PORTAL_LAB_FETCH", "1") != "0"


def where(uri):
    """`entrylib/study-planning, commit 1dffa04` for a commit-pinned log on GitHub, else None."""
    m = GITHUB_BLOB.match(str(uri or ""))
    return f"{m.group(1)}/{m.group(2)}, commit {m.group(3)[:7]}" if m else None


def raw_url(uri):
    """The raw file address of a commit-pinned log on GitHub, or None: only a log fixed at a commit is fetched, so
    its view never changes under the version it belongs to."""
    m = GITHUB_BLOB.match(str(uri or ""))
    if not m:
        return None
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"


def fetch(uri, opener=urllib.request.urlopen):
    """The text of the log at `uri`, or None."""
    url = raw_url(uri)
    if url is None or not enabled():
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=TIMEOUT) as res:
            data = res.read(MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        log.warning("lab record %s could not be fetched (%s); its page links the log only", uri, exc)
        return None
    if len(data) > MAX_BYTES:
        log.warning("lab record %s is larger than %d bytes; not read", uri, MAX_BYTES)
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def events(text):
    """The events of a log's text, or None if it is not JSON Lines."""
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except ValueError:
        return None


def views(text, doc):
    """(the reading view, {claim ID: its trail}) of a log's text, for the claimset `doc` exported from it; None when
    the installed claimset package makes no views (before 0.44.7) or the log cannot be read."""
    try:
        from claimset.lab import view as lab_view
    except ImportError:
        return None
    evs = events(text)
    if not evs:
        return None
    try:
        reading = lab_view.render(evs, title=(doc.get("paper") or {}).get("title"))
    except Exception as exc:                        # a log the package cannot read: no view, the log stays linked
        log.warning("lab record view failed (%s)", exc)
        return None
    trails = {}
    for c in doc.get("claims") or []:
        cid = c.get("id") if isinstance(c, dict) else None
        if not (isinstance(cid, str) and re.fullmatch(r"C\d+", cid)):
            continue
        try:
            t = lab_view.claim_trail(evs, doc, cid)
        except Exception:                           # a hypothesis the log does not hold
            t = None
        if t:
            trails[cid] = t
    return reading, trails


def package_version():
    try:
        import claimset
        return getattr(claimset, "__version__", None)
    except ImportError:
        return None
