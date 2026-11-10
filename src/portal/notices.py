"""Retraction and removal (design §7.5, portal issue #47).

    request(conn, ...)              -> a new request: the guarantor's waits for ORCID sign-in, anyone else's for review
    start_signin(conn, request_id)  -> an OAuth state for the guarantor's ORCID sign-in
    complete_signin(conn, state, orcid, name) -> Outcome: confirmed when the person signing in is the guarantor
    decide(conn, request_id, apply, note) -> EntryLib's decision on a reviewed request
    apply_confirmed(conn, ...)      -> write confirmed requests to the registry and the site (worker.py calls it)
    overlay(doc, notices)           -> the claimset as readers see it: retracted when its notices say so

A retraction keeps the claimset readable with a notice at its top; a removal replaces it, at the same addresses, by a
notice. Both are recorded in the registry as `<folder>/notices.json` (revision spec §2.4): a removal's commit also
deletes the claimset's versions; history is not rewritten. Every notice says who, when and why.
"""

import copy
import datetime as dt
import re
import secrets
from dataclasses import dataclass

from . import ids
from .screening import screen

#: Reasons, in the order the form lists them; each list ends with Other, which needs the requester's own words.
REASONS = {
    "retract": {"error_in_results": "Error in the results", "error_in_method": "Error in the method",
                "superseded": "Superseded by another entry", "other": "Other"},
    "remove": {"personal_data": "Personal data", "participant_data": "Data identifying research participants",
               "copyright": "Copyright", "no_coauthor_consent": "Published without a co-author's consent",
               "security": "Security-sensitive content", "other": "Other"},
}
ACTIONS = {"retract": "retracted", "remove": "removed"}
#: How long a request may wait for its ORCID sign-in, and a sign-in may take.
SIGNIN_WINDOW = dt.timedelta(minutes=30)
STALE = dt.timedelta(days=1)
MAX_STATEMENT = 2000
MAX_GROUNDS = 5000
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class NoticeError(Exception):
    """A request that cannot be made; the message says why, for the requester."""


@dataclass
class Outcome:
    result: str            # confirmed | wrong_person | not_waiting | unknown
    message: str
    request: str | None = None


def reason_label(code):
    for reasons in REASONS.values():
        if code in reasons:
            return reasons[code]
    return code


def _clean(text, limit, what):
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) > limit:
        raise NoticeError(f"{what} is too long: at most {limit} characters")
    for f in screen({"statement": text}):
        raise NoticeError(f"{what}: {f['message']}")
    return text


def _paper(conn, concept):
    row = conn.execute("SELECT concept_id, guarantors FROM papers WHERE concept_id = %s", (concept,)).fetchone()
    if row is None:
        if conn.execute("SELECT 1 FROM removed WHERE concept_id = %s", (concept,)).fetchone():
            raise NoticeError(f"{concept} has been removed already")
        raise NoticeError(f"no published claimset {concept}; give its identifier, such as entrylib:2026.000001")
    return row


def normalise_id(text):
    """entrylib:2026.000001 from what a requester may paste: the identifier, a versioned one, or its address."""
    text = (text or "").strip()
    m = re.search(r"(\d{4})\.(\d+)", text)
    return f"{ids.PREFIX}{m.group(1)}.{m.group(2)}" if m else text


def request(conn, *, concept, action, reason_code, statement="", guarantor=True, contact=None, grounds=None,
            now=None):
    """Record a request. Returns its id. The guarantor's request waits for sign-in; anyone else's for review."""
    now = now or dt.datetime.now(dt.UTC)
    concept = normalise_id(concept)
    if action not in REASONS:
        raise NoticeError("choose retraction or removal")
    if reason_code not in REASONS[action]:
        raise NoticeError(f"choose a reason for {'retraction' if action == 'retract' else 'removal'} from the list")
    statement = _clean(statement, MAX_STATEMENT, "the explanation")
    if reason_code == "other" and not statement:
        raise NoticeError("with Other as the reason, say why in your own words")
    _paper(conn, concept)
    notices = current_notice(conn, concept)
    if notices and notices["action"] == "retracted" and action == "retract":
        raise NoticeError(f"{concept} is retracted already")
    if guarantor:
        contact, grounds, state = None, None, "signin"
    else:
        contact = (contact or "").strip()
        if not EMAIL.match(contact):
            raise NoticeError("give an email address we can answer you at")
        grounds = _clean(grounds, MAX_GROUNDS, "the grounds")
        if not grounds:
            raise NoticeError("say what your request rests on, and how we can check it")
        state = "review"
    rid = "rq_" + secrets.token_urlsafe(12)
    conn.execute("INSERT INTO notice_requests (id, concept_id, action, reason_code, statement, state, contact,"
                 " grounds, received) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                 (rid, concept, action, reason_code, statement, state, contact, grounds, now))
    return rid


def start_signin(conn, request_id, now=None):
    now = now or dt.datetime.now(dt.UTC)
    row = conn.execute("SELECT state FROM notice_requests WHERE id = %s", (request_id,)).fetchone()
    if row is None or row[0] != "signin":
        return None
    state = "n_" + secrets.token_urlsafe(24)               # the prefix tells the shared ORCID callback whose it is
    conn.execute("INSERT INTO notice_signins (state, request_id, started) VALUES (%s, %s, %s)",
                 (state, request_id, now))
    return state


def is_notice_state(state):
    return isinstance(state, str) and state.startswith("n_")


def complete_signin(conn, state, orcid, name, now=None):
    """Confirm a guarantor's request if `orcid` is a guarantor of the claimset's current version."""
    now = now or dt.datetime.now(dt.UTC)
    with conn.transaction():
        row = conn.execute("UPDATE notice_signins SET used = %s WHERE state = %s AND used IS NULL AND started > %s"
                           " RETURNING request_id", (now, state, now - SIGNIN_WINDOW)).fetchone()
        if row is None:
            return Outcome("unknown", "this sign-in has expired or was already used; fill in the form again")
        rid = row[0]
        req = conn.execute("SELECT r.concept_id, r.state, p.guarantors FROM notice_requests r LEFT JOIN papers p"
                           " ON p.concept_id = r.concept_id WHERE r.id = %s FOR UPDATE OF r", (rid,)).fetchone()
        concept, req_state, guarantors = req
        if req_state != "signin":
            return Outcome("not_waiting", f"this request is {req_state}", rid)
        if guarantors is None:
            return Outcome("not_waiting", f"{concept} is no longer published", rid)
        if orcid not in (guarantors or []):
            return Outcome("wrong_person", f"you signed in as {orcid}, but the guarantor of {concept} is "
                                           f"{', '.join(guarantors)}. If you are a co-author or have another reason, "
                                           f"send the request for review instead.", rid)
        conn.execute("UPDATE notice_requests SET state = 'confirmed', by_orcid = %s, by_name = %s, decided = %s"
                     " WHERE id = %s", (orcid, name, now, rid))
    return Outcome("confirmed", "confirmed", rid)


def decide(conn, request_id, apply, note=None, now=None):
    """EntryLib's decision on a request under review. Returns the new state."""
    now = now or dt.datetime.now(dt.UTC)
    row = conn.execute("SELECT state FROM notice_requests WHERE id = %s", (request_id,)).fetchone()
    if row is None:
        raise NoticeError(f"no request {request_id}")
    if row[0] != "review":
        raise NoticeError(f"{request_id} is {row[0]}, not waiting for review")
    state = "confirmed" if apply else "declined"
    conn.execute("UPDATE notice_requests SET state = %s, decided = %s, detail = %s, contact = CASE WHEN %s THEN"
                 " contact ELSE NULL END, grounds = CASE WHEN %s THEN grounds ELSE NULL END WHERE id = %s",
                 (state, now, note, apply, apply, request_id))
    return state


def forget_stale(conn, now=None):
    """Delete requests whose guarantor never signed in."""
    now = now or dt.datetime.now(dt.UTC)
    return conn.execute("DELETE FROM notice_requests WHERE state = 'signin' AND received < %s RETURNING id",
                        (now - STALE,)).fetchall()


# --- notices ----------------------------------------------------------------------------------------------------------

def issuer(by_name, by_orcid):
    """Who a notice names: the guarantor (name and ORCID iD), or EntryLib for a reviewed request."""
    if by_orcid:
        return f"{by_name or 'The guarantor'} (ORCID {by_orcid})"
    return "EntryLib"


def make_notice(row, today, versions):
    """A notice for the registry, from a request row (action, reason_code, statement, by_name, by_orcid)."""
    action, reason_code, statement, by_name, by_orcid = row
    return {"action": ACTIONS[action], "date": today.isoformat(), "reason_code": reason_code,
            "reason": reason_label(reason_code), "statement": statement,
            "issued_by": issuer(by_name, by_orcid), "by": {"name": by_name, "orcid": by_orcid} if by_orcid else None,
            "versions": versions}


def latest(notices_doc):
    items = (notices_doc or {}).get("notices") or []
    return items[-1] if items else None


def current_notice(conn, concept):
    row = conn.execute("SELECT file->'paper'->'status_notice', file->'paper'->>'status' FROM versions v JOIN papers p"
                       " ON p.concept_id = v.concept_id AND p.current_version = v.version WHERE p.concept_id = %s",
                       (concept,)).fetchone()
    if row and row[1] == "retracted":
        return {"action": "retracted", **(row[0] or {})}
    return None


def status_notice(notice):
    """The claimset's `status_notice` (claimset spec §3.1) for a notice."""
    statement = notice.get("statement") or notice.get("reason") or reason_label(notice.get("reason_code"))
    return {"date": notice["date"], "reason_code": notice["reason_code"], "statement": statement,
            "issued_by": notice["issued_by"]}


def overlay(doc, notices_doc):
    """The claimset as readers see it: with a retraction in its notices, `status: retracted` and its notice (status
    and status_notice are assigned by the platform, claimset spec §9). Otherwise the file unchanged."""
    n = latest(notices_doc)
    if not n or n.get("action") != "retracted":
        return doc
    out = copy.deepcopy(doc)
    out["paper"]["status"] = "retracted"
    out["paper"]["status_notice"] = status_notice(n)
    return out


# --- applying ---------------------------------------------------------------------------------------------------------

def _confirmed(conn):
    return conn.execute("SELECT r.id, r.concept_id, r.action, r.reason_code, r.statement, r.by_name, r.by_orcid,"
                        " p.folder FROM notice_requests r JOIN papers p ON p.concept_id = r.concept_id"
                        " WHERE r.state = 'confirmed' ORDER BY r.received").fetchall()


def _prepared(registry, row, today):
    rid, concept, action, reason_code, statement, by_name, by_orcid, folder = row
    doc = registry.notices(folder) or {"id": concept, "notices": []}
    versions = registry.versions(folder)
    notice = make_notice((action, reason_code, statement, by_name, by_orcid), today, versions)
    doc["notices"].append(notice)
    verb = "Retract" if action == "retract" else "Remove"
    message = f"{verb} {concept}: {notice['reason']}"
    return folder, doc, action == "remove", message


def _close(conn, rid, state, detail=None):
    conn.execute("UPDATE notice_requests SET state = %s, detail = COALESCE(%s, detail), contact = NULL,"
                 " grounds = NULL WHERE id = %s", (state, detail, rid))


def apply_confirmed(conn, *, registry, published_dir, base_url, remote=None, today=None):
    """Write confirmed requests to the registry and the site. In github mode, open a registry pull request for each
    (state `publishing`) and apply those whose pull request was merged. Returns [(request id, state)]."""
    from .indexer import apply_notices
    today = today or dt.date.today()
    done = []
    if remote is not None:
        done += _settle(conn, remote=remote, published_dir=published_dir, base_url=base_url)
    for row in _confirmed(conn):
        rid = row[0]
        folder, doc, remove, message = _prepared(remote.registry if remote else registry, row, today)
        if remote is None:
            registry.write_notices(folder, doc, message, remove=remove)
            apply_notices(conn, registry, folder, published_dir, base_url)
            _close(conn, rid, "applied")
            done.append((rid, "applied"))
            continue
        branch = f"notice/{folder.rsplit('/', 1)[-1]}-{len(doc['notices'])}"
        body = (f"{message}.\n\nRequested on EntryLib and "
                + ("confirmed by the guarantor with ORCID." if row[6] else "approved by EntryLib after review.")
                + "\n\nOpened by the EntryLib portal; merged by it when the registry checks pass.")
        opened = remote.open_notices(folder, doc, remove, message, body, branch)
        conn.execute("UPDATE notice_requests SET state = 'publishing', registry_pr = %s, registry_branch = %s"
                     " WHERE id = %s", (opened.number, opened.branch, rid))
        done.append((rid, "publishing"))
    return done


def _settle(conn, *, remote, published_dir, base_url):
    from .indexer import apply_notices
    done = []
    rows = conn.execute("SELECT r.id, r.concept_id, r.registry_pr, r.registry_branch, p.folder FROM notice_requests r"
                        " LEFT JOIN papers p ON p.concept_id = r.concept_id WHERE r.state = 'publishing'"
                        " ORDER BY r.received").fetchall()
    for rid, concept, number, branch, folder in rows:
        outcome, reason = remote.settle(number, branch, f"Notice for {concept}")
        if outcome == "waiting":
            continue
        if outcome == "failed":
            _close(conn, rid, "failed", reason)
            done.append((rid, "failed"))
            continue
        apply_notices(conn, remote.registry, folder, published_dir, base_url)
        _close(conn, rid, "applied")
        done.append((rid, "applied"))
    return done
