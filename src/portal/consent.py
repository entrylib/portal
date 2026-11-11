"""Consent (design §4.2 steps 4–6, PLT-15, PLT-16): the guarantor confirms with ORCID.

    page_context(conn, token, dir)  -> what the consent page shows, or None for an unknown link
    start(conn, token)              -> an OAuth state for ORCID sign-in
    complete(conn, state, orcid)    -> Outcome: confirmed, or why not

Without the link (the guarantor lost it): at /confirm the guarantor signs in with ORCID and sees every pending
submission that names their iD; each has a one-time ticket behind its Confirm and Cancel buttons. /submissions
uses the same sign-in and shows, besides, everything else they submitted and guarantee.

    start_listing(conn, kind)       -> an OAuth state for that sign-in ("confirm" or "submissions")
    listing_kind(state)             -> which page a sign-in was for, or None if it is not a listing's
    listing(conn, state, orcid)     -> the pending submissions naming `orcid`, each with a ticket; None if the state
                                       is unknown, expired or used
    complete_ticket(conn, ticket, orcid) -> Outcome, as complete()
    cancel_ticket(conn, ticket, submissions_dir) -> Outcome: cancelled, or why not
    history(conn, orcid)            -> the rest of what `orcid` submitted, and the claimsets they guarantee

A submission is confirmed when the person who signs in with ORCID is its guarantor, the submission is still
pending, and the guarantor is within the limits of design §8. Confirmed submissions are published by the worker.
"""

import datetime as dt
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from claimset.render import render

from . import limits
from .publish import load_submission
from .submissions import CANCELLED, duplicate, token_hash

#: How long a sign-in started from a consent page may take.
SIGNIN_WINDOW = dt.timedelta(minutes=30)


@dataclass
class Outcome:
    result: str            # confirmed | cancelled | wrong_person | not_pending | limit | duplicate | unknown
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
    return _context_by_hash(conn, token_hash(token), submissions_dir)


def _context_by_hash(conn, hash_, submissions_dir):
    row = conn.execute(
        "SELECT g.submission_id, g.orcid, g.name, g.confirmed, s.state, s.kind, s.target, s.expires, s.file_name,"
        " s.published_id, s.detail FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
        " WHERE g.token_hash = %s", (hash_,)).fetchone()
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
                   n_claims=len(claims), reading_view=render(doc), subfield=_subfield_line(doc),
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


def complete(conn, state, orcid, now=None):
    """Finish a sign-in: confirm the submission if `orcid` is its guarantor's. Each state is used once."""
    now = now or dt.datetime.now(dt.UTC)
    with conn.transaction():
        row = conn.execute(
            "UPDATE consent_signins SET used = %s WHERE state = %s AND used IS NULL AND started > %s"
            " RETURNING token_hash", (now, state, now - SIGNIN_WINDOW)).fetchone()
        if row is None:
            return Outcome("unknown", "this sign-in has expired or was already used; open the consent link again")
        return _confirm(conn, row[0], orcid, now)


def _confirm(conn, token_hash_, orcid, now):
    """Confirm for the guarantor whose consent token has this hash, if `orcid` is theirs; inside a transaction."""
    g = conn.execute(
        "SELECT g.submission_id, g.orcid, s.state, s.kind, s.target, s.title_key, s.new_paper, s.expires"
        " FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
        " WHERE g.token_hash = %s FOR UPDATE OF s", (token_hash_,)).fetchone()
    sid, expected, sub_state, kind, target, key, new_paper, expires = g
    if orcid != expected:
        return Outcome("wrong_person", f"you signed in as {orcid}, but this claimset names {expected} as its "
                                       f"guarantor; only the guarantor can confirm it", sid)
    if sub_state != "pending":
        return Outcome("not_pending", f"this submission is {sub_state}", sid)
    over = limits.reached(conn, kind, orcid, target, now, exclude=sid)
    if over:                                            # the publication limits (design §8)
        why, from_, later = over
        if from_ <= expires:
            then = (f"You can confirm it from {limits.when(from_, now)}{later}, while its link is still valid "
                    f"(until {limits.when(expires, now)}).")
        else:
            then = (f"Its link expires before then, on {limits.when(expires, now)}: submit it again from "
                    f"{limits.when(from_, now)}{later}.")
        return Outcome("limit", f"This claimset can't be confirmed yet: the limit is reached.\n\n{why}\n\n{then}",
                       sid)
    same = None if kind != "new" or new_paper else duplicate(conn, key, [orcid], exclude=sid)
    if same:                                            # confirmed twice in one window (design §4.5)
        return Outcome("duplicate", f"this looks like a claimset already confirmed: {same}", sid)
    conn.execute("UPDATE submission_guarantors SET confirmed = %s WHERE token_hash = %s", (now, token_hash_))
    remaining = conn.execute("SELECT count(*) FROM submission_guarantors WHERE submission_id = %s"
                             " AND confirmed IS NULL", (sid,)).fetchone()[0]
    if remaining == 0:
        conn.execute("UPDATE submissions SET state = 'confirmed' WHERE id = %s", (sid,))
    return Outcome("confirmed", "confirmed", sid)


#: How long the Confirm buttons of a /confirm listing stay valid.
TICKET_WINDOW = dt.timedelta(minutes=30)


#: The pages a listing sign-in is for, by the prefix of its OAuth state.
LISTINGS = {"l_": "confirm", "m_": "submissions"}


def start_listing(conn, now=None, kind="confirm"):
    """An OAuth state for a sign-in at /confirm or /submissions. Its prefix tells the shared ORCID callback whose
    it is."""
    prefix = next(p for p, k in LISTINGS.items() if k == kind)
    state = prefix + secrets.token_urlsafe(24)
    conn.execute("INSERT INTO confirm_signins (state, started) VALUES (%s, %s)",
                 (state, now or dt.datetime.now(dt.UTC)))
    return state


def listing_kind(state):
    return LISTINGS.get(state[:2]) if isinstance(state, str) else None


def is_listing_state(state):
    return listing_kind(state) is not None


def listing(conn, state, orcid, submissions_dir, now=None):
    """The pending submissions that name `orcid` as a guarantor not yet confirmed, newest first, each with what the
    consent page shows and a one-time `ticket` for its Confirm button. None if the sign-in is unknown or used."""
    now = now or dt.datetime.now(dt.UTC)
    if conn.execute("UPDATE confirm_signins SET used = %s WHERE state = %s AND used IS NULL AND started > %s"
                    " RETURNING state", (now, state, now - SIGNIN_WINDOW)).fetchone() is None:
        return None
    rows = conn.execute("SELECT g.submission_id FROM submission_guarantors g JOIN submissions s ON s.id ="
                        " g.submission_id WHERE g.orcid = %s AND g.confirmed IS NULL AND s.state = 'pending'"
                        " AND s.expires > %s ORDER BY s.received DESC", (orcid, now)).fetchall()
    out = []
    for (sid,) in rows:
        token_row = conn.execute("SELECT token_hash FROM submission_guarantors WHERE submission_id = %s"
                                 " AND orcid = %s", (sid, orcid)).fetchone()
        ctx = _context_by_hash(conn, token_row[0], submissions_dir)
        if ctx is None or ctx["state"] != "pending":
            continue
        ticket = secrets.token_urlsafe(24)
        conn.execute("INSERT INTO confirm_tickets (ticket_hash, submission_id, orcid, expires) VALUES (%s, %s, %s,"
                     " %s)", (token_hash(ticket), sid, orcid, now + TICKET_WINDOW))
        out.append({**ctx, "ticket": ticket})
    return out


def complete_ticket(conn, ticket, orcid=None, now=None):
    """Confirm the submission behind a ticket from /confirm: the ticket is bound to the iD that signed in."""
    now = now or dt.datetime.now(dt.UTC)
    with conn.transaction():
        row = _ticket(conn, ticket, now)
        if row is None:
            return Outcome("unknown", "this confirmation has expired or was already used; sign in again at /confirm")
        sid, signed_in = row
        g = conn.execute("SELECT token_hash FROM submission_guarantors WHERE submission_id = %s AND orcid = %s",
                         (sid, signed_in)).fetchone()
        if g is None:
            return Outcome("wrong_person", "this submission does not name you as its guarantor", sid)
        return _confirm(conn, g[0], signed_in, now)


def _ticket(conn, ticket, now):
    """Use a ticket of a /confirm listing: (submission, the iD that signed in), or None if it is unknown, expired or
    used."""
    return conn.execute("UPDATE confirm_tickets SET used = %s WHERE ticket_hash = %s AND used IS NULL AND"
                        " expires > %s RETURNING submission_id, orcid", (now, token_hash(ticket or ""), now)
                        ).fetchone()


def cancel_ticket(conn, ticket, submissions_dir, now=None):
    """Cancel the submission behind a ticket (design §4.2 step 5): its guarantor no longer wants it. It is refused at
    once, its content deleted as on expiry; it then stops counting against the limits."""
    now = now or dt.datetime.now(dt.UTC)
    with conn.transaction():
        row = _ticket(conn, ticket, now)
        if row is None:
            return Outcome("unknown", "this button has expired or was already used; sign in again at /confirm")
        sid, signed_in = row
        if conn.execute("SELECT 1 FROM submission_guarantors WHERE submission_id = %s AND orcid = %s",
                        (sid, signed_in)).fetchone() is None:
            return Outcome("wrong_person", "this submission does not name you as its guarantor", sid)
        done = conn.execute("UPDATE submissions SET state = 'refused', file_name = NULL, title = NULL,"
                            " client_ip = NULL, title_key = NULL, detail = %s"
                            " WHERE id = %s AND state = 'pending' RETURNING id", (CANCELLED, sid)).fetchone()
        if done is None:
            state = conn.execute("SELECT state FROM submissions WHERE id = %s", (sid,)).fetchone()
            return Outcome("not_pending", f"this submission is {state[0] if state else 'gone'}", sid)
    for f in Path(submissions_dir).glob(f"{sid}.*"):
        f.unlink(missing_ok=True)
    return Outcome("cancelled", "cancelled", sid)


def history(conn, orcid, now=None):
    """What /submissions shows besides the pending submissions waiting for `orcid`: {"others": submissions that wait
    for another guarantor or are being published, "closed": those closed in the last 14 days (with the reason),
    "published": the current version of every claimset `orcid` guarantees}, each newest first."""
    now = now or dt.datetime.now(dt.UTC)
    rows = conn.execute(
        "SELECT s.id, s.state, s.kind, s.target, s.title, s.received, s.detail, s.published_id, g.confirmed"
        " FROM submissions s JOIN submission_guarantors g ON g.submission_id = s.id WHERE g.orcid = %s"
        " ORDER BY s.received DESC", (orcid,)).fetchall()
    keys = ("submission", "state", "kind", "target", "title", "received", "detail", "published_id", "confirmed")
    subs = [dict(zip(keys, r, strict=True)) for r in rows]
    published = conn.execute(
        "SELECT p.concept_id, p.current_version, p.title, p.status, p.updated FROM papers p"
        " WHERE %s = ANY(p.guarantors) ORDER BY p.updated DESC, p.concept_id DESC", (orcid,)).fetchall()
    return {"others": [x for x in subs if x["state"] in ("pending", "confirmed", "publishing") and
                       not (x["state"] == "pending" and x["confirmed"] is None)],
            "closed": [x for x in subs if x["state"] in ("refused", "expired")],
            "published": [dict(zip(("id", "version", "title", "status", "date"), r, strict=True))
                          for r in published]}


def forget_old(conn, now=None):
    """Delete /confirm sign-ins and tickets older than a day: they are long expired."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=1)
    conn.execute("DELETE FROM confirm_signins WHERE started < %s", (cutoff,))
    conn.execute("DELETE FROM confirm_tickets WHERE expires < %s", (cutoff,))


def _subfield_line(doc):
    """What the guarantor is told about the subfield: the one the submission proposes, or that it is assigned."""
    from .publish import proposed_subfield
    from .site import subfield_name
    sub = proposed_subfield(doc)
    if sub:
        return f"{subfield_name({'paper': {'classification': {'subfield': sub}}})} (proposed by the submission)"
    return ("assigned at publication by EntryLib's classifier; to choose it, propose paper.classification.subfield "
            "(an OpenAlex subfield) and submit again")
