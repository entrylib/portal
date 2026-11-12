"""Scores on the claimset page (design §7.6): the panel's score, each claim's score and dots, and the section *Score*
that explains them. The numbers come from the rubric (scores.py); this module only shows them. Everything taken from
a claimset (limitation and assumption statements in a problem's text) is escaped.

The claim markers are given to the claimset package as its `marker` (claimset 0.41.6), which puts them in place of
its support lights; with an older package the lights stay and the scores remain in the panel and the section.
"""

import html

from . import scores as sc
from . import text

RUBRIC_URL = "https://github.com/entrylib/rubric/blob/main/RUBRIC.md"
#: The score's name on the site: the rubric's reliability score, named for what it measures (design §7.6). The files
#: and the API keep `reliability`.
NAME = "Support"
#: What a band means in words (rubric §4.1), and what the score does not say, shown beside it.
BANDS = {"high": "Well supported", "medium": "Partly supported", "low": "Weakly supported"}
CAPTION = "Checks the record, not the science."
DOT_WORDS = {"green": "nothing lost", "amber": "some points lost", "red": "many points lost"}


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def _groups():
    return [(g["name"], g["label"]) for g in sc.rubric.RUBRIC["groups"]] if sc.rubric else []


def dots(scores, cid=None):
    """Five dots, one per group, each explained on hover: a claim's (cid), or the paper's."""
    item = scores["claims"][cid] if cid else scores["paper"]
    costs = item.get("costs") or {p: scores["problems"][p]["cost"] for p in item["problems"]}
    out = []
    for name, label in _groups():
        mine = [p for p in item["problems"] if scores["problems"][p]["group"] == name and costs.get(p)]
        if mine:
            why = "; ".join(f"−{costs[p]} {text.readable(scores['problems'][p]['text'])}" for p in mine)
            title = f"{label}: −{sum(costs[p] for p in mine)}. {why}"
        else:
            title = f"{label}: nothing lost"
        colour = item["dots"][name]
        out.append(f'<span class="dot dot-{colour}" title="{esc(title)}"></span>')
    words = ", ".join(f"{label} {DOT_WORDS[item['dots'][name]]}" for name, label in _groups())
    return f'<span class="dots" role="img" aria-label="{esc(words)}">{"".join(out)}</span>'


def badge(scores, cid, small=False):
    c = scores["claims"][cid]
    label = f"{NAME} {c['score']}, {BANDS[c['band']].lower()}: why"
    return (f'<a class="score-badge band-{c["band"]}{" small" if small else ""}" href="#score-{esc(cid)}" '
            f'data-popup="score-{esc(cid)}" aria-label="{esc(label)}"><span class="badge-word">{NAME}</span> '
            f'{c["score"]}</a>')


def marker(scores):
    """What marks a claim on the page (claimset's render_parts `marker`): its score and dots before its meta line and
    its novelty after it; under Highlights, its score. None for a claim without a score: the package then shows its
    support light (an assumption has neither)."""
    def mark(c, where):
        cid = c.get("id")
        if not scores or cid not in scores["claims"]:
            return None
        if where == "brief":
            return badge(scores, cid, small=True)
        n = sc.label(scores["novelty"].get(cid))
        after = f'<span class="novelty"> · novelty: {esc(n)}</span>' if n else ""
        return badge(scores, cid) + dots(scores, cid), after
    return mark


def dot_list(scores, cid=None):
    """The five dots as a list, each beside its group's name and explained on hover: a claim's (cid), or the
    paper's. Each dot's colour and the points beside it say what it lost; no key is needed."""
    item = scores["claims"][cid] if cid else scores["paper"]
    costs = item.get("costs") or {p: scores["problems"][p]["cost"] for p in item["problems"]}
    rows = []
    for name, label in _groups():
        mine = [p for p in item["problems"] if scores["problems"][p]["group"] == name and costs.get(p)]
        lost = sum(costs[p] for p in mine)
        colour = item["dots"][name]
        title = (f"{label}: −{lost}. " + "; ".join(f"−{costs[p]} {text.readable(scores['problems'][p]['text'])}"
                                                    for p in mine)) if mine else f"{label}: nothing lost"
        rows.append(f'<li title="{esc(title)}"><span class="dot dot-{colour}" aria-hidden="true"></span>'
                    f'{esc(label)}<span class="visually-hidden">: {DOT_WORDS[colour]}</span>'
                    + (f' <span class="lost">−{lost}</span>' if lost else "") + "</li>")
    return f'<ul class="dot-list small">{"".join(rows)}</ul>'


def score_block(score, band, popup):
    """The score as the panel shows it: the number, then one link to how it was made (the Score section's
    explanation, in a pop-up), and the caption."""
    return (f'<p class="score-line band-{band}"><a class="score-num" href="#score" data-popup="{popup}" '
            f'aria-label="{NAME} {score} of 100: why">{score}</a></p>'
            f'<p class="small score-why"><a href="#score" data-popup="{popup}">Why {score}?</a></p>'
            f'<p class="small caption">{CAPTION}</p>')


def panel_rows(scores, lights=None):
    """The panel's first rows: reliability and novelty, then the claims by band (without scores: by support
    light, from the page view)."""
    if not scores or not scores.get("paper"):
        names = {"green": "checkable", "amber": "not checkable", "red": "unsupported"}
        rows = "".join(f'<li><span class="light light-{k}"></span>{(lights or {}).get(k, 0)} {v}</li>'
                       for k, v in names.items())
        return (f'<div class="panel-row"><h2>{NAME}</h2><p class="score">–</p>'
                f'<p class="small">{CAPTION} <a href="/about#quality">How scores are given</a></p></div>'
                f'<div class="panel-row"><h2>Claims</h2><ul class="lights">{rows}</ul></div>')
    p = scores["paper"]
    counts = {b: 0 for b in BANDS}
    for c in scores["claims"].values():
        counts[c["band"]] += 1
    principal = [scores["novelty"].get(c) for c in p["principal"]]
    labels = {}
    for n in principal:
        if n and n.get("label"):
            word = sc.LABELS.get(n["label"], n["label"]).split(" ")[0]
            labels[word] = labels.get(word, 0) + 1
    checks = {n["check"] for n in principal if n and n.get("checked")}
    # Only a close match the authors do not acknowledge says something while the library is small.
    check = "in question: a close match on EntryLib is not acknowledged" if "unacknowledged" in checks else ""
    novelty = ", ".join(f"{v} {k}" for k, v in labels.items()) or "–"
    rows = "".join(f'<li><span class="score-badge small band-{b}">{counts[b]}</span>{w.lower()}</li>'
                   for b, w in BANDS.items())
    return (f'<div class="panel-row score-row"><h2>{NAME}</h2>'
            + score_block(p["score"], p["band"], "score-paper") + dot_list(scores)
            + f'<p class="novelty-row"><span class="novelty-label">Novelty</span> {esc(novelty)}'
            + (f'<span class="small"> · {esc(check)}</span>' if check else "")
            + ' · <a class="small" href="/about#quality" data-help="novelty-help" data-title="Novelty">'
              'What is this?</a>'
            + "</p>" + novelty_help(scores) + "</div>"
            f'<div class="panel-row"><h2>Claims</h2><ul class="bands">{rows}</ul></div>')


def novelty_help(scores):
    """What the panel's novelty means, for its pop-up (page.js, data-help): the authors' own account of each
    principal claim, and what EntryLib checks."""
    groups = {}
    for cid in scores["paper"].get("principal") or []:
        words = sc.label(scores["novelty"].get(cid)).replace(", by the authors", "") or "not stated"
        groups.setdefault(words, []).append(f'<a href="#{esc(cid)}">{esc(cid)}</a>')
    items = [f"<li><strong>{esc(w[:1].upper() + w[1:])}</strong>: {', '.join(c)}</li>" for w, c in groups.items()]
    return ('<template id="novelty-help"><h2>Novelty</h2>'
            '<p>How the authors place each principal claim against earlier work: new, '
            "extending it, replicating it or refuting it. It is their own account. EntryLib checks it only against "
            "the claims already published here, and says so when a close match is not acknowledged; it cannot check "
            "work published elsewhere, so read the paper's references too.</p>"
            f'<ul class="novelty-list">{"".join(items)}</ul>'
            '<p><a href="/how-to-judge">How to judge a paper</a></p></template>')


def _basis(p):
    """How the paper's score was made, with a link to the lowest principal claim (scores.paper_basis)."""
    link = f'<a href="#{esc(p["lowest"])}">{esc(p["lowest"])}</a>'
    if "lowest_score" in p:
        n = len(p.get("principal") or [])
        return (f"The mean of its {n} principal claim{'s' if n != 1 else ''}; the lowest is {link} at "
                f"{esc(p['lowest_score'])}")
    return f"The paper scores as its lowest principal claim, {link}"


def _sentence(text):
    text = str(text).rstrip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _problem(scores, pid, cost=None):
    p = scores["problems"][pid]
    groups = dict(_groups())
    claims = ", ".join(f'<a href="#{esc(c)}">{esc(c)}</a>' for c in p["claims"])
    return (f'<li><span class="cost">−{cost if cost is not None else p["cost"]}</span> '
            f'<span class="group">{esc(groups.get(p["group"], p["group"]))}</span> {text.html(_sentence(p["text"]))}'
            + (f' <span class="small">In {claims}.</span>' if claims and cost is None else "")
            + f' <span class="fix">To remove it: {text.html(p["fix"])}</span></li>')


def _claim_explain(scores, cid):
    c = scores["claims"][cid]
    problems = "".join(_problem(scores, pid, c["costs"][pid]) for pid in c["problems"])
    n = sc.label(scores["novelty"].get(cid))
    return (f'<div class="score-explain score-claim" id="score-{esc(cid)}"><h4><a href="#{esc(cid)}">'
            f'{esc(cid)}</a>: <span class="band-{c["band"]}">{c["score"]}, {BANDS[c["band"]]}</span> '
            f'{dots(scores, cid)}</h4>'
            + (f'<p class="small">Novelty: {esc(n)}</p>' if n else "")
            + (f'<ol class="problems">{problems}</ol>' if problems else '<p class="small">Nothing lost.</p>')
            + "</div>")


def claim_section(scores, cids):
    """The section *Score* of a claim's page: the explanation of each scored claim in `cids` (the claim and those it
    rests on), the claim first."""
    shown = [c for c in cids if scores and c in scores["claims"]]
    if not shown:
        return ""
    note = f'<p class="score-note">{esc(scores["note"])} <a href="{RUBRIC_URL}">The rubric</a>.</p>'
    return ('<section class="cs-section score-section" id="score"><h2>Score</h2>' + note
            + "".join(_claim_explain(scores, c) for c in shown) + "</section>")


def section(scores, issues_url=None):
    """The section *Score*: the paper's explanation, then every claim's. The pop-ups show parts of it."""
    if not scores:
        return ""
    note = (f'<p class="score-note">{esc(scores["note"])} <a href="{RUBRIC_URL}">The rubric</a>.'
            + (f' <a href="{esc(issues_url)}">Every issue as text</a>, for an agent preparing the next version.'
               if issues_url else "") + "</p>")
    out = ['<section class="cs-section score-section" id="score"><h2>Score</h2>']
    p = scores.get("paper")
    if p:
        problems = "".join(_problem(scores, pid) for pid in p["problems"])
        out.append(f'<div class="score-explain" id="score-paper"><h3>{NAME} of the paper: '
                   f'<span class="band-{p["band"]}">{p["score"]}, {BANDS[p["band"]]}</span></h3>{note}'
                   f'<p>{_basis(p)}. Open problems in the principal claims and what they rest on, each '
                   f'counted once, with the most it costs a claim:</p>'
                   + (f'<ol class="problems">{problems}</ol>' if problems else "<p>None.</p>") + "</div>")
    out.append("<h3>Claims</h3>")
    for cid in scores["claims"]:
        out.append(_claim_explain(scores, cid))
    out.append("</section>")
    return "".join(out)
