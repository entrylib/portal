"""The stylesheet of the page view (page.py), served as /claimset.css."""

CSS = """\
/* The page view of a claimset (EntryLib's page.py): the claimset's own part of a page, in a plain default look. A site
   supplies the page around it and its own look: the colours and the font are variables (--cs-*) it sets. */
.cs-page, .cs-body, .cs-header, .cs-toc {
  --cs-ink: #1b1b1b; --cs-muted: #5f5f5f; --cs-rule: #d0d0d0; --cs-rule-light: #e4e4e4; --cs-panel: #f4f4f4;
  --cs-accent: #0b57d0; --cs-target: #eef3fc;
  --cs-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --cs-math-font: math, "STIX Two Math", "Cambria Math", "Latin Modern Math", serif;
  --cs-code-font: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  --cs-green: #2e8b57; --cs-amber: #d08c1a; --cs-red: #c0392b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .cs-page, :root:not([data-theme="light"]) .cs-body,
  :root:not([data-theme="light"]) .cs-header, :root:not([data-theme="light"]) .cs-toc {
    --cs-ink: #e6e6e6; --cs-muted: #a3a3a3; --cs-rule: #3a3a3a; --cs-rule-light: #2c2c2c; --cs-panel: #1e1e1e;
    --cs-accent: #8ab4f8; --cs-target: #1d2633;
  }
}
.cs-page { max-width: 76rem; margin: 0 auto; padding: 24px 16px 64px; color: var(--cs-ink);
  font: 16px/1.55 var(--cs-font); font-variant-numeric: lining-nums tabular-nums; }
.cs-page a, .cs-body a, .cs-header a, .cs-toc a { color: var(--cs-accent); }
.cs-origin { display: inline-block; margin: 0; font-size: 13px; font-weight: 600; letter-spacing: .03em;
  text-transform: uppercase; border: 1px solid currentColor; border-radius: 3px; padding: 1px 8px; }
.cs-title { margin: 10px 0; font-size: clamp(28px, 4vw, 38px); line-height: 1.15; font-weight: 700; }
.cs-guarantor, .cs-authors, .cs-source { margin: 4px 0 0; overflow-wrap: anywhere; }
.cs-meta { margin: 4px 0 0; font-size: 16px; color: var(--cs-muted); }
.cs-label { color: var(--cs-muted); }
.orcid-wrap { color: var(--cs-muted); }
.orcid-wrap a { color: var(--cs-muted); }
.cs-layout { display: flex; flex-wrap: wrap; gap: 40px; margin-top: 28px; }
.cs-toc { flex: 0 0 210px; min-width: 0; align-self: flex-start; position: sticky; top: 16px;
  max-height: calc(100vh - 32px); overflow-y: auto; border-top: 2px solid var(--cs-ink); padding-top: 10px; font-size: 16px; }
.cs-toc-title { margin: 0 0 6px; font-size: 14px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--cs-muted); }
.cs-toc ol { margin: 0; padding: 0; list-style: none; line-height: 2; }
.cs-toc a { text-decoration: none; }
.count { color: var(--cs-muted); font-weight: 400; }
.cs-body { flex: 999 1 560px; min-width: 0; max-width: 50rem; }
.cs-section { border-top: 1px solid var(--cs-rule); padding-top: 22px; margin-top: 40px; }
.cs-section:first-child { border-top: 0; padding-top: 0; margin-top: 0; }
.cs-section h2 { margin: 0 0 10px; font-size: 26px; font-weight: 600; }
.cs-section h3 { margin: 22px 0 8px; font-size: 19px; font-weight: 600; }
.cs-brief { margin: 0; padding: 0; list-style: none; font-size: 18px; }
.cs-brief li { display: flex; gap: 10px; padding: 3px 0; }
.cs-brief li > span:last-child { min-width: 0; }       /* the statement, not its formulae, sets the width */
.cs-summary { margin: 0; font-size: 18px; }
.cs-brief .light { margin-top: 9px; }
.kind-tag .short { display: none; }
.kind-tag { flex: none; align-self: flex-start; margin-top: 4px; font-size: 13px; line-height: 1.5;
  padding: 0 6px; border-radius: 10px; border: 1px solid var(--cs-rule); color: var(--cs-muted); }
.cs-note, .cs-tail { font-size: 15px; color: var(--cs-muted); }
.cs-item { padding: 10px 0; border-top: 1px solid var(--cs-rule-light); }
.cs-item:target, .cs-def:target { background: var(--cs-target); margin: 0 -12px; padding-left: 12px; padding-right: 12px; }
.cs-item p { margin: 0; }
.cs-claim-meta { font-size: 15px; color: var(--cs-muted); }
.cs-statement { font-size: 18px; margin: 4px 0 6px !important; }
.cs-links { font-size: 15px; margin-top: 4px !important; }
.k { color: var(--cs-muted); }
.cs-id { color: var(--cs-muted); font-size: 15px; }
.light { display: inline-block; flex: 0 0 10px; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: 0; }
.light-green { background: var(--cs-green); } .light-amber { background: var(--cs-amber); } .light-red { background: var(--cs-red); }
.term { color: inherit !important; text-decoration: none; border-bottom: 1px dotted var(--cs-muted); }
.cs-context dt { font-weight: 600; margin-top: 12px; }
.cs-context dd { margin: 2px 0 0; }
.cs-def p { margin: 6px 0 0; }
.cs-def-nested { margin-left: 26px; border-left: 1px solid var(--cs-rule); padding-left: 14px; }
.cs-def-head strong { font-weight: 600; }
.cs-table { overflow-x: auto; border: 1px solid var(--cs-rule); margin: 10px 0; }
.cs-table table { border-collapse: collapse; width: 100%; font-size: 16px; }
.cs-table caption { text-align: left; padding: 8px 10px; font-size: 15px; caption-side: top; }
.cs-table th, .cs-table td { padding: 6px 10px; border-top: 1px solid var(--cs-rule-light); text-align: left; }
.cs-table thead th { background: var(--cs-panel); font-weight: 600; }
.cs-table th[scope="row"] { position: sticky; left: 0; background: var(--cs-panel); font-weight: 400; }
.cs-table td.num { text-align: right; }
.cs-results, .cs-steps { margin: 8px 0; padding-left: 22px; }
.cs-figures { display: flex; flex-wrap: wrap; gap: 16px; margin: 10px 0; }
.cs-figure { margin: 0; flex: 1 1 260px; max-width: 100%; }
.cs-figure img { display: block; max-width: 100%; height: auto; border: 1px solid var(--cs-rule); background: #fff; }
.cs-figure figcaption { font-size: 15px; margin-top: 6px; }
.cs-refs, .cs-artefacts { margin: 0; padding: 0; list-style: none; }
.cs-refs li, .cs-artefacts li { padding: 6px 0; border-top: 1px solid var(--cs-rule-light); overflow-wrap: anywhere; }
@media (max-width: 860px) {
  .cs-toc { position: static; max-height: none; }
  .cs-layout { gap: 24px; }
}
math { font-family: var(--cs-math-font); font-size: 1.05em; }
math[display="block"] { margin: 10px 0; max-width: 100%; overflow-x: auto; overflow-y: hidden; }
/* A formula wider than a phone's screen scrolls on its own instead of widening the page. On a narrow screen only:
   an inline formula that scrolls may clip a little of an italic letter's overhang. */
@media (max-width: 640px) { math { max-width: 100%; overflow-x: auto; overflow-y: hidden; padding: 0 0.1em; } }
mtable[columnspacing="0"] mtd { padding-left: 0; padding-right: 0; }      /* aligned equations: = under = */
.cs-code, .math-tex { font-family: var(--cs-code-font); font-size: 0.9em; background: var(--cs-panel);
  border: 1px solid var(--cs-rule-light); border-radius: 3px; padding: 0 4px; overflow-wrap: anywhere; }
.cs-table td.txt { text-align: left; }
"""
