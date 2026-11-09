"""Consent (design §4.2 steps 4–6, PLT-15, PLT-16): the guarantor confirms with ORCID.

    page_context(conn, token, dir)  -> what the consent page shows, or None for an unknown link
    start(conn, token)              -> an OAuth state for ORCID sign-in
    complete(conn, state, orcid)    -> Outcome: confirmed, or why not

A submission is confirmed when the person who signs in with ORCID is its guarantor, the submission is still
pending, and the guarantor is within the limits of design §8. Confirmed submissions are published by the worker.
"""

import datetime as dt
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from claimset.render import render

from .publish import load_submission
from .submissions import duplicate, token_hash

#: New claimsets one guarantor may publish in seven days, and versions of one claimset in a day (design §8).
MAX_NEW_PER_WEEK = 2
MAX_VERSIONS_PER_DAY = 3
#: How long a sign-in started from a consent page may take.
SIGNIN_WINDOW = dt.timedelta(minutes=30)


@dataclass
class Outcome:
    result: str            # confirmed | wrong_person | not_pending | limit | unknown
    message: str
    submission: str | None = None


def _guarantor(conn, token):
    return conn.execute(
        "SELECT g.submission_id, g.orcid, g.name, g.confirmed, s.state, s.kind, s.target, s.expires, s.file_name,"
        " s.published_id, s.detail FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
        " WHERE g.token_hash = %s", (token_hash(token),)).fetchone()


def page_context(conn, token, submissions_dir):
    """What the consent page shows: the submission's state and, while pending, the claims the guarantor answers
    for, as the reading view (plain text, made mechanically from the file)."""
    row = _guarantor(conn, token)
    if row is None:
        return None
    sid, orcid, name, confirmed, state, kind, target, expires, file_name, published, detail = row
    ctx = {"submission": sid, "orcid": orcid, "name": name, "confirmed": confirmed is not None, "state": state,
           "kind": kind, "target": target, "expires": expires, "published": published, "detail": detail}
    if state == "pending" and file_name:
        with tempfile.TemporaryDirectory() as tmp:
            doc, _ = load_submission(Path(submissions_dir) / file_name, tmp)
        paper = doc.get("paper") or {}
        claims = {c.get("id"): c for c in doc.get("claims") or [] if isinstance(c, dict)}
        ctx.update(title=paper.get("title", ""), licence=paper.get("licence", ""),
                   principal=[claims[c].get("statement", "") for c in paper.get("contributions") or [] if c in claims],
                   n_claims=len(claims), reading_view=render(doc),
                   correction_reason=paper.get("correction_reason"))
    return ctx


def start(conn, token):
    """An OAuth state for a sign-in from this consent link, or None if the link is unknown or not pending."""
    row = _guarantor(conn, token)
    if row is None or row[4] != "pending":
        return None
    state = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO consent_signins (state, token_hash) VALUES (%s, %s)", (state, token_hash(token)))
    return state


def _over_limit(conn, orcid, kind, target, now):
    if kind == "new":
        n = conn.execute(
            "SELECT count(*) FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
            " WHERE g.orcid = %s AND s.kind = 'new' AND s.state IN ('confirmed', 'publishing', 'published')"
            " AND g.confirmed > %s", (orcid, now - dt.timedelta(days=7))).fetchone()[0]
        if n >= MAX_NEW_PER_WEEK:
            return f"you have confirmed {n} new claimsets in the last seven days, the most allowed; this one can be " \
                   f"confirmed later, before its link expires"
    else:
        n = conn.execute(
            "SELECT count(*) FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
            " WHERE s.target = %s AND s.state IN ('confirmed', 'publishing', 'published') AND g.confirmed > %s",
            (target, now - dt.timedelta(days=1))).fetchone()[0]
        if n >= MAX_VERSIONS_PER_DAY:
            return f"{target} already has {n} new versions confirmed in the last day, the most allowed"
    return None


def complete(conn, state, orcid, now=None):
    """Finish a sign-in: confirm the submission if `orcid` is its guarantor's. Each state is used once."""
    now = now or dt.datetime.now(dt.UTC)
    with conn.transaction():
        row = conn.execute(
            "UPDATE consent_signins SET used = %s WHERE state = %s AND used IS NULL AND started > %s"
            " RETURNING token_hash", (now, state, now - SIGNIN_WINDOW)).fetchone()
        if row is None:
            return Outcome("unknown", "this sign-in has expired or was already used; open the consent link again")
        g = conn.execute(
            "SELECT g.submission_id, g.orcid, s.state, s.kind, s.target, s.title_key, s.new_paper"
            " FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
            " WHERE g.token_hash = %s FOR UPDATE OF s", (row[0],)).fetchone()
        sid, expected, sub_state, kind, target, key, new_paper = g
        if orcid != expected:
            return Outcome("wrong_person", f"you signed in as {orcid}, but this claimset names {expected} as its "
                                           f"guarantor; only the guarantor can confirm it", sid)
        if sub_state != "pending":
            return Outcome("not_pending", f"this submission is {sub_state}", sid)
        reason = _over_limit(conn, orcid, kind, target, now)
        if reason:
            return Outcome("limit", reason, sid)
        same = None if kind != "new" or new_paper else duplicate(conn, key, [orcid], exclude=sid)
        if same:                                            # confirmed twice in one window (design §4.5)
            return Outcome("duplicate", f"this looks like a claimset already confirmed: {same}", sid)
        conn.execute("UPDATE submission_guarantors SET confirmed = %s WHERE token_hash = %s", (now, row[0]))
        remaining = conn.execute("SELECT count(*) FROM submission_guarantors WHERE submission_id = %s"
                                 " AND confirmed IS NULL", (sid,)).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE submissions SET state = 'confirmed' WHERE id = %s", (sid,))
    return Outcome("confirmed", "confirmed", sid)
