"""The limits on publication (design §8), in one place: what they are, whether a guarantor or a claimset has reached
them, and, if so, when they can go on, in words for people.

    NEW_PER_WEEK, VERSIONS_PER_DAY  -> the limits in force (PORTAL_MAX_NEW_PER_WEEK, PORTAL_MAX_VERSIONS_PER_DAY)
    reached(conn, kind, orcid, target, now, exclude=None) -> None, or why not and from when, as sentences

Counted against the limit: what is published or on its way in the window, and what is waiting for confirmation, so
that a submission is refused when it is made rather than after its guarantor has confirmed it.
"""

import datetime as dt
import os

#: The design's values (§8) are 2 new claimsets per guarantor in any seven days and 3 versions per claimset in any
#: day. Raised while the library is seeded with its owner's claimsets: issue #64 returns them to the design's.
NEW_PER_WEEK = int(os.environ.get("PORTAL_MAX_NEW_PER_WEEK", "20"))
VERSIONS_PER_DAY = int(os.environ.get("PORTAL_MAX_VERSIONS_PER_DAY", "10"))

WEEK, DAY = dt.timedelta(days=7), dt.timedelta(days=1)


def when(t, now):
    """Saturday 14 November at 15:02 UTC (with the year only when it is not this year)."""
    year = f" {t.year}" if t.year != now.year else ""
    return f"{t:%A} {t.day} {t:%B}{year} at {t:%H:%M} UTC"


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def reached(conn, kind, orcid, target, now, exclude=None):
    """None if one more new claimset by `orcid` (kind "new") or one more version of `target` may be submitted or
    confirmed now; otherwise (sentences saying why, the earliest time from which it can go on, and a note for when
    that time depends on submissions still waiting)."""
    if kind == "new":
        limit, window = NEW_PER_WEEK, WEEK
        done = conn.execute(
            "SELECT g.confirmed FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
            " WHERE g.orcid = %s AND s.kind = 'new' AND s.state IN ('confirmed', 'publishing', 'published')"
            " AND g.confirmed > %s", (orcid, now - window)).fetchall()
        waiting = conn.execute(
            "SELECT s.expires FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
            " WHERE g.orcid = %s AND s.kind = 'new' AND s.state = 'pending' AND s.expires > %s"
            " AND s.id IS DISTINCT FROM %s", (orcid, now, exclude)).fetchall()
    else:
        limit, window = VERSIONS_PER_DAY, DAY
        done = conn.execute(
            "SELECT max(g.confirmed) FROM submission_guarantors g JOIN submissions s ON s.id = g.submission_id"
            " WHERE s.target = %s AND s.state IN ('confirmed', 'publishing', 'published')"
            " GROUP BY s.id HAVING max(g.confirmed) > %s", (target, now - window)).fetchall()
        waiting = conn.execute(
            "SELECT expires FROM submissions WHERE target = %s AND state = 'pending' AND expires > %s"
            " AND id IS DISTINCT FROM %s", (target, now, exclude)).fetchall()
    # Each counted item stops counting at a known time: a publication when it leaves the window, a waiting
    # submission when its consent link expires (if it is confirmed first, it counts for longer, as a publication).
    frees = sorted([t + window for (t,) in done] + [t for (t,) in waiting])
    if len(frees) < limit:
        return None
    from_ = frees[len(frees) - limit]
    later = (" (later, if those waiting are confirmed)" if waiting else "")
    if kind == "new":
        why = (f"Each person can publish up to {_plural(limit, 'new claimset')} in any seven days. You already have "
               f"{len(done)} published in the last seven days and {len(waiting)} waiting for your confirmation.")
    else:
        why = (f"Each claimset can have up to {_plural(limit, 'new version')} in a day. {target} already has "
               f"{len(done)} published in the last day and {len(waiting)} waiting for confirmation.")
    return why, from_, later
