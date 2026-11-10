"""Scores of a claimset version, by EntryLib's rubric (github.com/entrylib/rubric; design §7.6).

    compute(conn, doc) -> the scores of one version, or None without the rubric installed
    text(scores)       -> the scores in plain text, for the end of the reading view
    version()          -> the rubric version, or None

The rubric decides every cost and every match; the portal only finds the candidates for the close-match check: claims
of claimsets first published before this one, by the full-text search of their statements.
"""

import re

try:
    import rubric
except ImportError:                                          # the page then shows "–"
    rubric = None

NOTE = ("Scores are computed by rules from the claimset file (EntryLib rubric {v}): they check the record, not the "
        "science, and may change as the rubric and reviews develop.")
LABELS = {"no_prior_found": "new", "extension": "extends earlier work", "replication": "replicates earlier work",
          "refutation": "refutes earlier work"}
CHECK = {"none": "no close match on EntryLib", "acknowledged": "close matches on EntryLib, acknowledged",
         "unacknowledged": "in question: close match on EntryLib not acknowledged"}


def version():
    return rubric.VERSION if rubric else None


def _candidates(conn, concept, statement, limit=20):
    """Claims of claimsets first published before `concept`, closest first by full-text search."""
    if conn is None or rubric is None:
        return []
    words = sorted(rubric.stems(statement))
    words = [w for w in words if re.fullmatch(r"[a-z0-9]+", w)]
    if not words:
        return []
    query = " | ".join(f"{w}:*" for w in words[:40])
    rows = conn.execute(
        "SELECT c.concept_id, c.claim_id, c.statement FROM claims c"
        " JOIN papers p ON p.concept_id = c.concept_id AND p.current_version = c.version"
        " WHERE c.concept_id <> %s AND NOT c.is_assumption"
        " AND p.first_published < (SELECT COALESCE(MIN(first_published), 'infinity'::date) FROM papers"
        "                          WHERE concept_id = %s)"
        " AND c.search @@ to_tsquery('english', %s)"
        " ORDER BY ts_rank(c.search, to_tsquery('english', %s)) DESC LIMIT %s",
        (concept, concept, query, query, limit)).fetchall()
    return [{"claim": f"{r[0]}#{r[1]}", "statement": r[2]} for r in rows]


def compute(conn, doc):
    """The scores of one claimset version: the rubric's result, plus novelty for every scored claim that has a
    novelty label. None without the rubric."""
    if rubric is None:
        return None
    result = rubric.score(doc)
    concept = (doc.get("paper") or {}).get("id")
    novelty = {}
    for c in doc.get("claims") or []:
        if not isinstance(c, dict) or c.get("id") not in result["claims"] or not c.get("novelty"):
            continue
        matches = _candidates(conn, concept, c.get("statement")) if c.get("role") == "principal" else []
        n = rubric.novelty(c, matches, concept)
        n["checked"] = c.get("role") == "principal" and conn is not None
        novelty[c["id"]] = n
    result["novelty"] = novelty
    result["note"] = NOTE.format(v=result["rubric"])
    return result


def label(n):
    """A claim's novelty in words: 'new (authors) · no close match on EntryLib'."""
    if not n or not n.get("label"):
        return ""
    words = f"{LABELS.get(n['label'], n['label'].replace('_', ' '))}, by the authors"
    return words + (f" · {CHECK[n['check']]}" if n.get("checked") else "")


def text(scores):
    """The scores in plain text, for the end of the reading view."""
    if not scores:
        return ""
    out = ["", "SCORES", scores["note"]]
    paper = scores.get("paper")
    if paper:
        out.append(f"Reliability of the paper: {paper['score']} ({paper['band']}), the score of its lowest principal "
                   f"claim, {paper['lowest']}.")
    for cid, c in scores["claims"].items():
        n = label(scores["novelty"].get(cid))
        out.append(f"{cid}: reliability {c['score']} ({c['band']})" + (f"; novelty: {n}" if n else ""))
    problems = paper["problems"] if paper else []
    if problems:
        out.append("Open problems in the principal claims and what they rest on:")
        for pid in problems:
            p = scores["problems"][pid]
            words = p["text"] if p["text"].rstrip().endswith((".", "!", "?")) else p["text"] + "."
            out.append(f"{pid} [{p['group']}; up to -{p['cost']}; {', '.join(p['claims'])}] {words} "
                       f"To remove it: {p['fix']}")
    return "\n".join(out) + "\n"
