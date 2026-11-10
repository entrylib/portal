"""The consent pages: plain HTML. Every value from a submission is escaped; nothing submitted is rendered as HTML."""

from html import escape

STYLE = """
body { font: 16px/1.55 system-ui, sans-serif; max-width: 46rem; margin: 2.5rem auto; padding: 0 1rem; color: #1b1b1b; }
pre { white-space: pre-wrap; background: #f4f4f4; padding: 1rem; border-radius: 4px; font-size: 13px; }
.box { border: 1px solid #ccc; border-radius: 6px; padding: 1rem 1.25rem; margin: 1.25rem 0; }
.button { display: inline-block; background: #a6ce39; color: #1b1b1b; padding: 0.6rem 1.1rem; border-radius: 4px;
          text-decoration: none; font-weight: 600; }
.muted { color: #666; font-size: 14px; }
@media (prefers-color-scheme: dark) { body { background: #111; color: #e6e6e6; } pre { background: #1e1e1e; }
  .box { border-color: #444; } .muted { color: #999; } }
"""


def page(title, body):
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<meta name=\"robots\" content=\"noindex\"><title>{escape(title)} · EntryLib</title>"
            f"<style>{STYLE}</style></head><body><h1>{escape(title)}</h1>{body}</body></html>")


def message(title, text, status_url=None):
    link = f"<p class=\"muted\">Status: <a href=\"{escape(status_url)}\">{escape(status_url)}</a></p>" \
        if status_url else ""
    paragraphs = "".join(f"<p>{escape(t)}</p>" for t in str(text).split("\n\n") if t.strip())   # blank lines part them
    return page(title, f"{paragraphs}{link}")


def consent(ctx, start_url, status_url):
    """The page a guarantor opens from their consent link."""
    state = ctx["state"]
    if state != "pending":
        texts = {"confirmed": "You have confirmed this claimset; it is being published, or waits for the "
                              "publication limit (the status link says when).",
                 "publishing": "You have confirmed this claimset. It is being checked in the public registry and "
                               "will be published when the checks pass; the status link shows progress.",
                 "published": f"This claimset is published as {ctx.get('published')}.",
                 "refused": f"This submission could not be published: {ctx.get('detail') or ''}",
                 "expired": "This submission expired: it was not confirmed within 48 hours. The agent can submit "
                            "it again."}
        return message("Claimset consent", texts.get(state, state), status_url)
    principal = "".join(f"<li>{escape(s)}</li>" for s in ctx["principal"])
    correction = ""
    if ctx["kind"] == "correction":
        correction = (f"<p><strong>This is a correction of {escape(ctx['target'])}.</strong> Reason given: "
                      f"{escape(ctx.get('correction_reason') or '')}</p>")
    expires = ctx["expires"].strftime("%d %B %Y, %H:%M UTC")
    body = f"""
<p>An agent has submitted a claimset to EntryLib that names you, <strong>{escape(ctx['name'] or '')}</strong>
(ORCID <code>{escape(ctx['orcid'])}</code>), as its guarantor.</p>
{correction}
<div class="box">
<p><strong>{escape(ctx['title'])}</strong></p>
<p class="muted">{ctx['n_claims']} claims · licence {escape(ctx['licence'])}</p>
<p class="muted">Subfield: {escape(ctx.get('subfield') or '')}</p>
<p>Principal claims:</p><ul>{principal}</ul>
<details><summary>The whole claimset, as models will read it</summary><pre>{escape(ctx['reading_view'])}</pre></details>
</div>
<p>By confirming, you state that you are the main author of this work and the person to contact about it, that you
answer for its research (whether the claims are true and the work was done properly), and that it may be published
under the licence {escape(ctx['licence'])}. Once published, a claimset stays: it can be corrected or retracted, and
is removed only when it must be (<a href="/removal">retraction and removal</a>).</p>
<p><a class="button" href="{escape(start_url)}">Sign in with ORCID and confirm</a></p>
<p class="muted">Only {escape(ctx['orcid'])} can confirm. This link expires {escape(expires)}. If you did not
expect this, ignore it: nothing is published without your confirmation.</p>
"""
    return page("Confirm a claimset", body)
