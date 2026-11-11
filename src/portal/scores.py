"""Scores of a claimset version, by EntryLib's rubric (github.com/entrylib/rubric; design §7.6).

    compute(conn, doc)    -> the scores of one version, or None without the rubric installed
    finder(conn, concept) -> find(statement) for rubric.assess: the candidates for the close-match check
    text(scores)          -> the scores in plain text, for the end of the reading view
    issues_text(...)      -> every issue, for the authors' agent (rubric.report)
    version()             -> the rubric version, or None

The rubric decides every cost and every match (rubric.assess) and writes the report (rubric.report); the portal only
finds the candidates for the close-match check: claims of claimsets first published before this one (every published
claimset, for one not yet submitted), by the full-text search of their statements. A claimset is scored before it is
submitted by the same functions (`claimset score`, the MCP tool score; design §7.6).
"""

import re
import sys

try:
    import rubric
except ImportError:                                          # the page then shows "–"
    rubric = None

#: What the portal calls in the rubric. A rubric without one of them (installed before it was added) counts as not
#: installed, so that it cannot stop publication or a rebuild; the next start installs the current one.
NEEDED = ("VERSION", "RUBRIC", "assess", "report", "score", "stems")
if rubric is not None and not all(hasattr(rubric, n) for n in NEEDED):
    print(f"portal: the installed rubric lacks {', '.join(n for n in NEEDED if not hasattr(rubric, n))}; scores show "
          "\"–\" until a current one is installed", file=sys.stderr)
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
        " WHERE c.concept_id IS DISTINCT FROM %s AND NOT c.is_assumption"
        " AND p.first_published < (SELECT COALESCE(MIN(first_published), 'infinity'::date) FROM papers"
        "                          WHERE concept_id = %s)"
        " AND c.search @@ to_tsquery('english', %s)"
        " ORDER BY ts_rank(c.search, to_tsquery('english', %s)) DESC LIMIT %s",
        (concept, concept, query, query, limit)).fetchall()
    return [{"claim": f"{r[0]}#{r[1]}", "statement": r[2]} for r in rows]


def finder(conn, concept):
    """find(statement) for rubric.assess: the candidates of _candidates(), or None without a database."""
    if conn is None:
        return None
    return lambda statement: _candidates(conn, concept, statement)


def compute(conn, doc):
    """The scores of one claimset version: rubric.assess() with the portal's candidates, and the note. None without
    the rubric."""
    if rubric is None:
        return None
    result = rubric.assess(doc, finder(conn, (doc.get("paper") or {}).get("id")))
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


def issues_text(scores, concept, n, base_url):
    """Every issue that lowers a reliability score, as plain text for the authors' agent to work through in the next
    version (/p/<key>@v<n>.issues.txt)."""
    if not scores:
        return ""
    key = concept.split(":", 1)[-1]
    out = [f"EntryLib: the issues that lower the reliability scores of {concept}@v{n}, by the EntryLib rubric "
           f"{scores['rubric']}.",
           "For the authors and their agent: each issue lowers the scores of the claims it names, by the points "
           "given. Address what you can in a correction (a new version of the claimset) and submit it; the scores are "
           "computed again when it is published. Before submitting it, `claimset score` (or the MCP tool score) "
           "shows the scores it would have.",
           NOTE.format(v=scores["rubric"]),
           "Rubric: https://github.com/entrylib/rubric/blob/main/RUBRIC.md",
           f"Page: {base_url}/p/{key}@v{n}#score · Scores as JSON: {base_url}/p/{key}@v{n}.score.json", ""]
    return "\n".join(out) + "\n" + rubric.report(scores)
