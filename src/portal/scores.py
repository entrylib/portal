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

import contextlib
import inspect
import re
import sys


def rubric_error(what, detail):
    """Report a failure of the rubric, named as such: the scores are left out ("–") and the rest of the portal goes on
    (publication, the registry, the index, the pages)."""
    print(f"portal: RUBRIC ERROR while {what}: {detail}. Scores show \"–\"; the rest of the portal is not affected.",
          file=sys.stderr)


try:
    import rubric
except ImportError:                                          # not installed: the page then shows "–"
    rubric = None
except Exception as exc:  # noqa: BLE001 - a broken rubric must not stop the portal
    rubric_error("importing it", f"{type(exc).__name__}: {exc}")
    rubric = None

#: What the portal calls in the rubric. A rubric without one of them (installed before it was added) counts as not
#: installed; the next start installs the current one.
NEEDED = ("VERSION", "RUBRIC", "assess", "report", "score", "stems")
if rubric is not None and not all(hasattr(rubric, n) for n in NEEDED):
    rubric_error("loading it", f"the installed rubric lacks {', '.join(n for n in NEEDED if not hasattr(rubric, n))}")
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


def _warnings(doc):
    """The current validator's warnings for a published file, which the rubric reads from 0.3 (warning 17: numbers no
    recorded result holds; warning 46: a limitation restating the declared competing interest). None if it fails."""
    try:
        from claimset.validate import validate
        return validate(doc, published=True).warnings
    except Exception as exc:  # noqa: BLE001 - scored without the warnings, as before rubric 0.3
        rubric_error("validating for the scores", f"{type(exc).__name__}: {exc}")
        return None


def _with_warnings(fn, doc, *args):
    """fn(doc, *args), given the validator's warnings when the installed rubric reads them."""
    if "warnings" in inspect.signature(fn).parameters:
        return fn(doc, *args, warnings=_warnings(doc))
    return fn(doc, *args)


def compute(conn, doc):
    """The scores of one claimset version: rubric.assess() with the portal's candidates, and the note. None without
    the rubric."""
    if rubric is None:
        return None
    paper = doc.get("paper") or {}
    try:
        # a savepoint: a failed query of the close-match check must not abort the caller's transaction
        with conn.transaction() if conn is not None else contextlib.nullcontext():
            result = _with_warnings(rubric.assess, doc, finder(conn, paper.get("id")))
        result["note"] = NOTE.format(v=result["rubric"])
    except Exception as exc:  # noqa: BLE001 - the rubric's failure leaves the scores out, nothing else
        rubric_error(f"scoring {paper.get('id') or 'a claimset'}@v{paper.get('version', '?')} (rubric {version()})",
                     f"{type(exc).__name__}: {exc}")
        return None
    return result


def paper_score(doc):
    """The paper's reliability for a list card, or None without the rubric or when it fails."""
    if rubric is None:
        return None
    try:
        return _with_warnings(rubric.score, doc)["paper"]
    except Exception as exc:  # noqa: BLE001 - the rubric's failure leaves the score out, nothing else
        rubric_error(f"scoring {(doc.get('paper') or {}).get('id')} for a list (rubric {version()})",
                     f"{type(exc).__name__}: {exc}")
        return None


def paper_basis(paper):
    """How the paper's score was made, in words: the mean of its principal claims (rubric 0.3), or, under an earlier
    rubric, its lowest principal claim's."""
    if "lowest_score" in paper:
        n = len(paper.get("principal") or [])
        return (f"the mean of its {n} principal claim{'s' if n != 1 else ''}; the lowest is {paper['lowest']} at "
                f"{paper['lowest_score']}")
    return f"the score of its lowest principal claim, {paper['lowest']}"


def label(n):
    """A claim's novelty in words: 'new, by the authors', and '· in question: …' when a close match on EntryLib is not
    acknowledged."""
    if not n or not n.get("label"):
        return ""
    words = f"{LABELS.get(n['label'], n['label'].replace('_', ' '))}, by the authors"
    # Only a close match the authors do not acknowledge says something while the library is small (UX audit).
    return words + (f" · {CHECK[n['check']]}" if n.get("checked") and n.get("check") == "unacknowledged" else "")


def text(scores):
    """The scores in plain text, for the end of the reading view."""
    if not scores:
        return ""
    out = ["", "SCORES", scores["note"]]
    paper = scores.get("paper")
    if paper:
        out.append(f"Reliability of the paper: {paper['score']} ({paper['band']}), {paper_basis(paper)}.")
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
    try:
        report = rubric.report(scores)
    except Exception as exc:  # noqa: BLE001 - the rubric's failure leaves the issues out, nothing else
        rubric_error(f"writing the issues of {concept}@v{n} (rubric {version()})", f"{type(exc).__name__}: {exc}")
        return ""
    return "\n".join(out) + "\n" + report
