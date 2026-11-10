"""Scores on the claimset page (design §7.6): the panel's score, each claim's score and dots, and the section *Score*
that explains them. The numbers come from the rubric (scores.py); this module only shows them. Everything taken from
a claimset (limitation and assumption statements in a problem's text) is escaped.

The claim markers are put into the page view the claimset package rendered, in place of its support lights, by the
package's stable markup (`cs-item cs-claim … id`, `cs-claim-meta`, `light`); if that markup changes, the lights stay
and the scores remain in the panel and the section.
"""

import html
import re

from . import scores as sc

RUBRIC_URL = "https://github.com/entrylib/rubric/blob/main/RUBRIC.md"
BANDS = {"high": "High", "medium": "Medium", "low": "Low"}
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
            why = "; ".join(f"−{costs[p]} {scores['problems'][p]['text']}" for p in mine)
            title = f"{label}: −{sum(costs[p] for p in mine)}. {why}"
        else:
            title = f"{label}: nothing lost"
        colour = item["dots"][name]
        out.append(f'<span class="dot dot-{colour}" title="{esc(title)}"></span>')
    words = ", ".join(f"{label} {DOT_WORDS[item['dots'][name]]}" for name, label in _groups())
    return f'<span class="dots" role="img" aria-label="{esc(words)}">{"".join(out)}</span>'


def badge(scores, cid, small=False):
    c = scores["claims"][cid]
    label = f"Reliability {c['score']}, {BANDS[c['band']].lower()}: why"
    return (f'<a class="score-badge band-{c["band"]}{" small" if small else ""}" href="#score-{esc(cid)}" '
            f'data-popup="score-{esc(cid)}" aria-label="{esc(label)}">{c["score"]}</a>')


CLAIM = re.compile(r'(<div class="cs-item cs-claim[^"]*" id="([^"]+)"><p class="cs-claim-meta">)'
                   r'(<span class="light[^"]*"[^>]*></span>)?((?:(?!</p>).)*)</p>', re.S)
BRIEF = re.compile(r'<li><span class="light[^"]*"[^>]*></span>(<span>(?:(?!</li>).)*?'
                   r'<a class="cs-id" href="#([^"]+)">[^<]*</a></span></li>)', re.S)


def decorate(body, scores):
    """The page view with each scored claim's light replaced by its score and dots, and its novelty added."""
    if not scores:
        return body

    def claim(m):
        cid = m.group(2)
        if cid not in scores["claims"]:
            return m.group(0)
        n = sc.label(scores["novelty"].get(cid))
        novelty = f'<span class="novelty"> · novelty: {esc(n)}</span>' if n else ""
        return f'{m.group(1)}{badge(scores, cid)}{dots(scores, cid)}{m.group(4)}{novelty}</p>'

    def brief(m):
        cid = m.group(2)
        if cid not in scores["claims"]:
            return m.group(0)
        return f"<li>{badge(scores, cid, small=True)}{m.group(1)}"

    return BRIEF.sub(brief, CLAIM.sub(claim, body))


def panel_rows(scores, lights=None):
    """The panel's first rows: reliability and novelty, then the claims by band (without scores: by support
    light, from the page view)."""
    if not scores or not scores.get("paper"):
        names = {"green": "checkable", "amber": "not checkable", "red": "unsupported"}
        rows = "".join(f'<li><span class="light light-{k}"></span>{(lights or {}).get(k, 0)} {v}</li>'
                       for k, v in names.items())
        return ('<div class="panel-row"><h2>Reliability</h2><p class="score">–</p>'
                f'<p class="small"><a href="{RUBRIC_URL}">How scores are given</a></p></div>'
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
    check = ("in question: a close match on EntryLib is not acknowledged" if "unacknowledged" in checks
             else "no close match on EntryLib" if checks == {"none"} else
             "close matches on EntryLib, acknowledged" if checks else "")
    novelty = ", ".join(f"{v} {k}" for k, v in labels.items()) or "–"
    rows = "".join(f'<li><span class="score-badge small band-{b}">{counts[b]}</span>{w.lower()}</li>'
                   for b, w in BANDS.items())
    return (f'<div class="panel-row score-row"><h2>Reliability</h2>'
            f'<p class="score-big band-{p["band"]}"><a href="#score" data-popup="score-paper">'
            f'<span class="score-num">{p["score"]}</span> <span class="score-band">{BANDS[p["band"]]}</span></a></p>'
            f'{dots(scores)}'
            f'<p class="small">The lowest of the principal claims: <a href="#{esc(p["lowest"])}">'
            f'{esc(p["lowest"])}</a>. <a href="#score" data-popup="score-paper">Why</a></p>'
            f'<p class="novelty-row"><span class="novelty-label">Novelty</span> {esc(novelty)}'
            + (f'<span class="small"> · {esc(check)}</span>' if check else "") + "</p></div>"
            f'<div class="panel-row"><h2>Claims</h2><ul class="bands">{rows}</ul></div>')


def _sentence(text):
    text = str(text).rstrip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _problem(scores, pid, cost=None):
    p = scores["problems"][pid]
    groups = dict(_groups())
    claims = ", ".join(f'<a href="#{esc(c)}">{esc(c)}</a>' for c in p["claims"])
    return (f'<li><span class="cost">−{cost if cost is not None else p["cost"]}</span> '
            f'<span class="group">{esc(groups.get(p["group"], p["group"]))}</span> {esc(_sentence(p["text"]))}'
            + (f' <span class="small">In {claims}.</span>' if claims and cost is None else "")
            + f' <span class="fix">To remove it: {esc(p["fix"])}</span></li>')


def section(scores):
    """The section *Score*: the paper's explanation, then every claim's. The pop-ups show parts of it."""
    if not scores:
        return ""
    note = f'<p class="score-note">{esc(scores["note"])} <a href="{RUBRIC_URL}">The rubric</a>.</p>'
    out = ['<section class="cs-section score-section" id="score"><h2>Score</h2>']
    p = scores.get("paper")
    if p:
        problems = "".join(_problem(scores, pid) for pid in p["problems"])
        out.append(f'<div class="score-explain" id="score-paper"><h3>Reliability of the paper: '
                   f'<span class="band-{p["band"]}">{p["score"]}, {BANDS[p["band"]]}</span></h3>{note}'
                   f'<p>The paper scores as its lowest principal claim, <a href="#{esc(p["lowest"])}">'
                   f'{esc(p["lowest"])}</a>. Open problems in the principal claims and what they rest on, each '
                   f'counted once, with the most it costs a claim:</p>'
                   + (f'<ol class="problems">{problems}</ol>' if problems else "<p>None.</p>") + "</div>")
    out.append("<h3>Claims</h3>")
    for cid, c in scores["claims"].items():
        problems = "".join(_problem(scores, pid, c["costs"][pid]) for pid in c["problems"])
        n = sc.label(scores["novelty"].get(cid))
        out.append(f'<div class="score-explain score-claim" id="score-{esc(cid)}"><h4><a href="#{esc(cid)}">'
                   f'{esc(cid)}</a>: <span class="band-{c["band"]}">{c["score"]}, {BANDS[c["band"]]}</span> '
                   f'{dots(scores, cid)}</h4>'
                   + (f'<p class="small">Novelty: {esc(n)}</p>' if n else "")
                   + (f'<ol class="problems">{problems}</ol>' if problems else '<p class="small">Nothing lost.</p>')
                   + "</div>")
    out.append("</section>")
    return "".join(out)
