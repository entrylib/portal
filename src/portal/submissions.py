"""Receiving submissions (design §4.2 steps 1–3, 8).

    check(path)                     -> Check: the synchronous checks, nothing kept
    receive(conn, upload, ...)      -> the stored pending submission, with a consent link per guarantor
    duplicate(conn, key, orcids)    -> a claimset the same guarantor already has, or is publishing, with this title
    status(conn, id)                -> what an agent may know about its submission
    expire(conn, ...)               -> delete submissions whose guarantors did not all confirm in time

The checks are those of the `claimset` package (rules of every file, submission rules, rules 70 and 77) and the
deterministic screening (screening.py). A submission that fails them is refused and nothing is kept.
"""

import datetime as dt
import hashlib
import json
import secrets
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from claimset.validate import validate_path

from .indexer import title_key
from .publish import load_submission
from .screening import SCREENING_VERSION, screen

CONSENT_WINDOW = dt.timedelta(hours=48)
#: Pending submissions one address may hold at once (design §8).
MAX_PENDING_PER_IP = 5
#: The largest upload accepted: the package limit (claimset rule 77, 200 MB of payload) and room for the bag.
MAX_UPLOAD_BYTES = 210 * 1024 * 1024
#: How long the record of a closed submission (expired, refused) is kept for status queries.
KEEP_CLOSED = dt.timedelta(days=14)


class SubmissionError(Exception):
    def __init__(self, message, status=422, errors=(), warnings=()):
        super().__init__(message)
        self.status = status
        self.errors = list(errors)
        self.warnings = list(warnings)


@dataclass
class Check:
    errors: list
    warnings: list
    computed: dict = field(default_factory=dict)
    doc: dict | None = None

    @property
    def ok(self):
        return not self.errors

    def as_json(self):
        return {"valid": self.ok, "errors": self.errors, "warnings": self.warnings,
                "verifiability": self.computed, "screening": SCREENING_VERSION}


def _items(rows):
    return [{"rule": e["rule"], "where": e["where"], "message": e["message"]} for e in rows]


def check(path):
    """The synchronous checks of a submission at `path` (a package zip or folder, or a claimset file)."""
    try:
        rep = validate_path(str(path))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return Check([{"rule": "read", "where": "", "message": f"cannot read the submission: {exc}"}], [])
    if rep is None:
        return Check([{"rule": "read", "where": "", "message": "cannot read the submission: not a claimset file "
                                                               "(JSON) or a package (BagIt zip)"}], [])
    errors, warnings = _items(rep.errors), _items(rep.warnings)
    doc = None
    if not errors:
        with tempfile.TemporaryDirectory() as tmp:
            doc, _ = load_submission(path, tmp)
        errors += screen(doc)
    return Check(errors, warnings, dict(rep.computed or {}), doc)


def guarantors(doc):
    """[(orcid, name)] of the person who must confirm: the guarantor, the main author, who submits (claimset spec
    v0.36). The validator has checked that it is one person with an ORCID iD (rules 14, 16)."""
    return sorted({(c["orcid"], c.get("name")) for c in doc.get("contributors") or []
                   if isinstance(c, dict) and "guarantor" in (c.get("positions") or [])})


def duplicate(conn, key, orcids, exclude=None):
    """What a new claimset may duplicate (design §4.5): a published claimset, or a confirmed submission on its way to
    publication, with the same guarantor and the same title key (indexer.title_key). A submission still waiting for
    consent does not count: a fixed file may be submitted again before confirming, and the first one expires. Returns
    a sentence naming it, or None."""
    if not key or not orcids:
        return None
    row = conn.execute("SELECT concept_id FROM papers WHERE title_key = %s AND guarantors && %s::text[]"
                       " ORDER BY concept_id LIMIT 1", (key, list(orcids))).fetchone()
    if row:
        return (f"{row[0]} has the same title and guarantor. To publish a new version of it, set paper.id to "
                f"\"{row[0]}\" and give paper.correction_reason")
    row = conn.execute("SELECT s.id, s.target FROM submissions s JOIN submission_guarantors g ON g.submission_id = s.id"
                       " WHERE s.title_key = %s AND g.orcid = ANY(%s) AND s.state IN ('confirmed', 'publishing')"
                       " AND s.id IS DISTINCT FROM %s ORDER BY s.received LIMIT 1",
                       (key, list(orcids), exclude)).fetchone()
    if row:
        return (f"submission {row[0]}, with the same title and guarantor, is confirmed and being published; once "
                f"it is, a new version of it sets paper.id to its identifier (GET /api/submissions/{row[0]})")
    return None


def new_id():
    return "sub_" + secrets.token_urlsafe(16)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def receive(conn, upload, *, submissions_dir, base_url, client_ip=None, now=None, new_paper=False):
    """Check an uploaded file and keep it as a pending submission. Returns the submission's description, with the
    consent links (each shown once: only their hashes are stored). Raises SubmissionError if it is refused.

    A new claimset that looks like one its guarantor already has (duplicate) is refused unless `new_paper` says it
    is a different paper with the same title."""
    now = now or dt.datetime.now(dt.UTC)
    upload = Path(upload)
    if client_ip is not None:
        n = conn.execute("SELECT count(*) FROM submissions WHERE client_ip = %s AND state = 'pending'",
                         (client_ip,)).fetchone()[0]
        if n >= MAX_PENDING_PER_IP:
            raise SubmissionError(f"this address already has {n} submissions waiting for consent; wait until they "
                                  f"are confirmed or expire", status=429)
    result = check(upload)
    if not result.ok:
        raise SubmissionError(f"the submission is not valid: {len(result.errors)} error(s)", errors=result.errors,
                              warnings=result.warnings)
    doc = result.doc
    paper = doc["paper"]
    if paper.get("origin") == "converted":
        raise SubmissionError("converted claimsets are published by EntryLib's conversion service, which answers for "
                              "them as conversion guarantor; this API takes native claimsets, submitted by their "
                              "guarantor")
    people = guarantors(doc)
    kind, target = "new", None
    if "id" in paper:
        kind, target = "correction", paper["id"]
        row = conn.execute("SELECT v.file FROM papers p JOIN versions v ON v.concept_id = p.concept_id"
                           " AND v.version = p.current_version WHERE p.concept_id = %s", (target,)).fetchone()
        if row is None:
            raise SubmissionError(f"the correction names {target}, which is not published on EntryLib")
        current = guarantors(row[0])
        if current and [o for o, _ in people] != [o for o, _ in current]:
            raise SubmissionError(f"a correction is submitted by the guarantor of the current version of {target} "
                                  f"({current[0][0]}); this one names {people[0][0]}", status=403)
    elif not new_paper:
        same = duplicate(conn, title_key(paper.get("title")), [o for o, _ in people])
        if same:
            raise SubmissionError(f"this looks like a claimset already on EntryLib: {same}. If it is a different "
                                  f"paper with the same title, submit it again with new_paper=true", status=409,
                                  warnings=result.warnings)

    sub_id = new_id()
    suffix = ".zip" if zipfile.is_zipfile(upload) else ".json"
    stored = Path(submissions_dir) / f"{sub_id}{suffix}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(upload, stored)
    expires = now + CONSENT_WINDOW
    links = []
    with conn.transaction():
        conn.execute(
            "INSERT INTO submissions (id, received, expires, state, kind, target, title, title_key, new_paper,"
            " file_name, sha256, size, report, client_ip)"
            " VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (sub_id, now, expires, kind, target, paper.get("title"), title_key(paper.get("title")),
             bool(new_paper), stored.name, _sha256(stored), stored.stat().st_size, json.dumps(result.as_json()),
             client_ip))
        for orcid, name in people:
            token = secrets.token_urlsafe(24)
            conn.execute("INSERT INTO submission_guarantors (submission_id, orcid, name, token_hash)"
                         " VALUES (%s, %s, %s, %s)", (sub_id, orcid, name, token_hash(token)))
            links.append({"orcid": orcid, "name": name, "consent_url": f"{base_url}/consent/{token}"})
    return {**status(conn, sub_id, base_url), "consent": links, "report": result.as_json()}


def status(conn, sub_id, base_url, registry_repo=None):
    """What may be told about a submission to whoever holds its ID: its state, never its content. While it is
    `publishing`, the registry pull request where its checks run (public)."""
    row = conn.execute("SELECT id, received, expires, state, kind, target, published_id, detail, registry_pr"
                       " FROM submissions WHERE id = %s", (sub_id,)).fetchone()
    if row is None:
        return None
    sid, received, expires, state, kind, target, published, detail, pr = row
    people = conn.execute("SELECT orcid, confirmed IS NOT NULL FROM submission_guarantors WHERE submission_id = %s"
                          " ORDER BY orcid", (sid,)).fetchall()
    out = {"id": sid, "state": state, "kind": kind, "received": received.isoformat(), "expires": expires.isoformat(),
           "status_url": f"{base_url}/api/submissions/{sid}",
           "guarantors": [{"orcid": o, "confirmed": c} for o, c in people]}
    if target:
        out["corrects"] = target
    if published:
        out["published"] = published
    if detail:
        out["detail"] = detail
    if pr and registry_repo:
        out["registry_pull_request"] = f"https://github.com/{registry_repo}/pull/{pr}"
    return out


def expire(conn, submissions_dir, now=None):
    """Delete the content of pending submissions past their window, and forget closed ones after KEEP_CLOSED.
    Returns the IDs expired."""
    now = now or dt.datetime.now(dt.UTC)
    rows = conn.execute("UPDATE submissions SET state = 'expired', file_name = NULL, title = NULL,"
                        " title_key = NULL,"
                        " detail = 'not every guarantor confirmed within 48 hours'"
                        " WHERE state = 'pending' AND expires <= %s RETURNING id", (now,)).fetchall()
    expired = [r[0] for r in rows]
    for sid in expired:
        for f in Path(submissions_dir).glob(f"{sid}.*"):
            f.unlink(missing_ok=True)
    conn.execute("DELETE FROM submissions WHERE state IN ('expired', 'refused') AND expires <= %s",
                 (now - KEEP_CLOSED,))
    return expired
