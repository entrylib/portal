"""Whether a version changed claims (design §7.4, Status): a correction that changed what a paper claims is
"corrected"; one that changed anything else (links, labels, the summary, keywords, how a test binds its values) is
"updated". The published file's `paper.changes` lists what its version changed, as a JSON patch."""

import re

#: A change to a claim's statement, outcome, role or type, or a claim added or removed.
CLAIM_CHANGE = re.compile(r"^/claims(/(-|\d+)(/(statement|role|type|hypothesis(/outcome)?))?)?$")


def claims_changed(changes):
    """Whether a version's `changes` alter what the paper claims."""
    return any(isinstance(c, dict) and CLAIM_CHANGE.match(str(c.get("path", ""))) for c in changes or [])


def corrected_concepts(conn):
    """The papers some version of which, after the first, changed what they claim: they are marked "corrected" in
    lists (cards), whatever their latest version changed."""
    rows = conn.execute("SELECT concept_id, file->'paper'->'changes' FROM versions WHERE version > 1").fetchall()
    return {concept for concept, changes in rows if isinstance(changes, list) and claims_changed(changes)}
