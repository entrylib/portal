"""The consent pages, in the site's shell. Every value from a submission is escaped; nothing submitted is rendered as
HTML."""

from html import escape


def page(title, body):
    """A consent page in the site's own shell (design §4.3): the header with its menu, the footer and the site's styles,
    so that a guarantor who confirms can go on to the rest of the site. Not indexed."""
    from . import site
    return site.shell(title, f'<div class="wrap prose consent"><h1>{escape(title)}</h1>{body}</div>',
                      active="submissions", head='<meta name="robots" content="noindex">')


def message(title, text, status_url=None, back=None):
    link = f"<p class=\"muted\">Status: <a href=\"{escape(status_url)}\">{escape(status_url)}</a></p>" \
        if status_url else ""
    if back:                                                # (url, label): where to go next
        link += f'<p><a href="{escape(back[0])}">{escape(back[1])}</a></p>'
    paragraphs = "".join(f"<p>{escape(t)}</p>" for t in str(text).split("\n\n") if t.strip())   # blank lines part them
    return page(title, f"{paragraphs}{link}")


def outcome_text(outcome):
    """An outcome's message as a sentence, with the errors of a package that is not valid, as text."""
    text = outcome.message[:1].upper() + outcome.message[1:]
    text = text if text.endswith(".") else text + "."
    if outcome.errors:
        text += " " + " ".join(f"Rule {e.get('rule')} at {e.get('where') or 'the file'}: {e.get('message')}."
                               for e in outcome.errors[:10])
    return text


def _source_box(ctx):
    """The published paper a claimset restates, and what the portal found about its authors (design §4.5)."""
    src = ctx.get("source")
    if not src or not src.get("doi"):
        return ""
    doi = escape(src["doi"])
    named = escape(src.get("title") or f"doi:{src['doi']}")
    more = ""
    if src.get("coauthor_orcids"):
        more = ('<p class="muted">The paper\'s record gives ORCID iDs for co-authors this claimset does not name: '
                + "; ".join(escape(x) for x in src["coauthor_orcids"]) + ". Your agent can add them in a new "
                "version.</p>")
    return (f'<p>Converted by its authors from <a href="https://doi.org/{doi}">{named}</a>. Authorship: '
            f'{escape(src.get("authorship") or "")}.</p>{more}')


def consent(ctx, start_url, status_url, attach_url=None, attached=False):
    """The page a guarantor opens from their consent link. A submission waiting for its package (design §4.4) asks
    for it first: the Confirm button comes once it is attached."""
    state = ctx["state"]
    if state != "pending":
        texts = {"confirmed": "You have confirmed this paper; it is being published.",
                 "publishing": "You have confirmed this paper. It is being checked in the public registry and "
                               "will be published when the checks pass; the status link shows progress.",
                 "published": f"This paper is published as {ctx.get('published')}.",
                 "refused": f"This submission could not be published: {ctx.get('detail') or ''}",
                 "expired": "This submission expired: it was not confirmed within 48 hours. The agent can submit "
                            "it again."}
        return message("Confirm a submission", texts.get(state, state), status_url)
    principal = "".join(f"<li>{escape(s)}</li>" for s in ctx["principal"])
    correction = ""
    if ctx["kind"] == "correction":
        correction = (f"<p><strong>This is a correction of {escape(ctx['target'])}.</strong> Reason given: "
                      f"{escape(ctx.get('correction_reason') or '')}</p>")
    expires = ctx["expires"].strftime("%d %B %Y, %H:%M UTC")
    body = f"""
<p>An AI agent has submitted a paper to EntryLib that names you, <strong>{escape(ctx['name'] or '')}</strong>
(ORCID <code>{escape(ctx['orcid'])}</code>), as its responsible researcher (in the claimset format, its
guarantor).</p>
{correction}
<div class="box">
<p><strong>{escape(ctx['title'])}</strong></p>
<p class="muted">{ctx['n_claims']} claims · licence {escape(ctx['licence'])}</p>
<p class="muted">Subfield: {escape(ctx.get('subfield') or '')}</p>
{_source_box(ctx)}<p>Principal claims:</p><ul>{principal}</ul>
<details><summary>The whole paper, as models will read it</summary><pre>{escape(ctx['reading_view'])}</pre></details>
</div>
<p>By confirming, you state that you are the main author of this work and the person to contact about it, that you
answer for its research (whether the claims are true and the work was done properly), and that it may be published
under the licence {escape(ctx['licence'])}. Once published, a paper stays: it can be corrected or retracted, and
is removed only when it must be (<a href="/removal">retraction and removal</a>).</p>
{_package_box(ctx, attach_url, attached)}
{_confirm_button(ctx, start_url)}
<p class="muted">Only {escape(ctx['orcid'])} can confirm. This link expires {escape(expires)}. If you did not
expect this, ignore it: nothing is published without your confirmation.</p>
"""
    return page("Confirm a submission", body)


def _confirm_button(ctx, start_url):
    """The Confirm button, once nothing waits: a submission waiting for its package shows the package form instead."""
    if ctx.get("waiting_package"):
        return ""
    return f'<p><a class="button" href="{escape(start_url)}">Sign in with ORCID and confirm</a></p>'


def _package_box(ctx, attach_url, attached):
    """The package form of a submission waiting for it, or the note that it was attached."""
    if attached and not ctx.get("waiting_package"):
        return '<p class="box"><strong>The package is attached and checked.</strong> You can now confirm.</p>'
    if not ctx.get("waiting_package") or not attach_url:
        return ""
    files = "".join(f"<li><code>{escape(f)}</code></li>" for f in ctx.get("package_files") or [])
    return f"""<div class="box">
<p><strong>First, attach the package.</strong> The agent sent the claimset without the files it names; attach
the package it made (the <code>.zip</code> file that <code>claimset package</code> builds), which holds the
claimset and:</p>
<ul>{files}</ul>
<form method="post" action="{escape(attach_url)}" enctype="multipart/form-data">
<p><input type="file" name="package" accept=".zip,application/zip" required> <button type="submit">Attach</button></p>
</form>
<p class="muted">EntryLib checks the package and that it holds the claimset shown here. Then you can confirm.</p>
</div>"""
