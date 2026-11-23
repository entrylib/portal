"""The LaTeX draft of a published paper (design §4.6): what it holds, that nothing in the file becomes a TeX command,
where its lines come from, and the guarantor's button on Your submissions."""

import copy
import csv
import io
import re
import shutil
import subprocess
import zipfile

import psycopg
import pytest
from publishing import example
from test_confirm import confirm, sign_in_at, signed_in, tickets
from test_consent import submit, titled

from portal import latex, ratelimit

BASE = "https://entrylib.test"


def published(doc=None):
    doc = copy.deepcopy(doc or example())
    doc["paper"].update({"id": "entrylib:2026.000007", "version": 2, "date": "2026-11-20", "status": "active"})
    doc["paper"]["summary"] = "Method M forecasts monthly retail sales better than the seasonal naive method."
    return doc


def files(doc, **kw):
    name, data = latex.build(doc, BASE, **kw)
    z = zipfile.ZipFile(io.BytesIO(data))
    folder = name.removesuffix("-latex.zip")
    return name, {n.removeprefix(folder + "/"): z.read(n).decode("utf-8") for n in z.namelist()
                  if not n.startswith(f"{folder}/figures/")}, z.namelist()


def test_the_zip():
    name, f, names = files(published())
    assert name == "entrylib-2026.000007-v2-latex.zip"
    assert all(n.startswith("entrylib-2026.000007-v2/") for n in names)
    assert {"paper.tex", "supplement.tex", "references.bib", "traceability.csv", "GAPS.md", "README.md"} <= set(f)
    assert "pdflatex paper" in f["README.md"] and not any(n.endswith(".pdf") for n in names)     # no PDF
    assert latex.build(published(), BASE) == latex.build(published(), BASE)                      # the same every time


def test_it_names_its_claimset_three_times():
    _, f, _ = files(published())
    tex = f["paper.tex"]
    title = tex[tex.index("\\title{"):tex.index("\\author{")]
    assert "\\thanks{This paper is the human edition of the claimset" in title and "entrylib:2026.000007@v2" in title
    start = tex.index("\\section{Introduction}")
    intro = tex[start:tex.index("\\section{", start + 1)]
    assert "\\citep{entrylib2026.000007v2}" in intro
    assert "\\section*{Data, materials and provenance}" in tex
    assert f["references.bib"].startswith("@misc{entrylib2026.000007v2,")                    # the first entry
    assert "Keep the link to the claimset" in f["README.md"]


def test_it_sets_out_the_claimset_and_marks_what_is_missing():
    _, f, _ = files(published())
    tex = f["paper.tex"]
    assert "\\begin{abstract}\nMethod M forecasts" in tex
    assert "\\label{claim:C2}" in tex and "\\begin{assumption}\\label{asm:C1}" in tex      # a claim, its assumption
    assert "\\subsection{Limitations}" in tex and "All 1,200 series come from one retailer" in tex
    assert "A.~Researcher" not in tex and "A. Researcher" in tex                             # the human author
    assert "Example research agent" not in tex[tex.index("\\author{"):tex.index("\\date{")]   # agents are not authors
    assert "Example provider Example model 1.0" in tex                                       # named in Use of AI
    # what the claimset does not hold is a gap, listed with its line
    lines = tex.split("\n")
    gaps = [r for r in f["GAPS.md"].split("\n") if re.match(r"\| \d+ \|", r)]
    assert len(gaps) >= 5 and tex.count("\\gap{") == len(gaps)
    for row in gaps:
        n, what = re.match(r"\| (\d+) \| (.+) \|", row).groups()
        assert "\\gap{" in lines[int(n) - 1]
    assert any("affiliation of A. Researcher" in g for g in gaps) and any("motivation" in g for g in gaps)


def test_each_line_says_where_it_comes_from():
    _, f, _ = files(published())
    lines = f["paper.tex"].split("\n")
    rows = list(csv.DictReader(io.StringIO(f["traceability.csv"])))
    assert {r["file"] for r in rows} == {"paper.tex", "supplement.tex"}
    statement = [r for r in rows if r["file"] == "paper.tex" and r["object"] == "C2" and r["field"] == "statement"]
    assert statement
    text = "\n".join(lines[int(statement[0]["first_line"]) - 1:int(statement[0]["last_line"])])
    assert "improves forecast skill over the seasonal naive method" in text
    assert not any(x.lstrip().startswith("%") for x in lines)          # the record of origins is the CSV, not comments


def test_tables_are_printed_and_kept_as_csv():
    doc = published()
    rows = [{"id": f"r{i}", "label": [f"series {i}"], "values": [0.1 + i / 1000]} for i in range(1, 61)]
    doc["evidence"][0]["tables"] = [{"id": "T1", "description": "MASE per series", "row_labels": ["series"],
                                     "columns": ["D1"], "rows": rows}]
    doc["claims"][2]["support"][0]["results"] = ["E1.T1.r3"]
    _, f, _ = files(doc)
    table = list(csv.reader(io.StringIO(f["tables/E1.T1.csv"])))
    assert table[0] == ["row", "series", "forecast skill"] and len(table) == 61
    assert table[3][2] == repr(0.1 + 3 / 1000)                                               # every digit
    tex = f["paper.tex"]
    assert "series 3 & 0.103" in tex and "series 4 &" not in tex                            # 60 rows: the cited
    assert "The 1 rows the claims cite, of 60" in tex and "Table~\\ref{tab:E1.T1}" in tex


HOSTILE = [r"\input{/etc/passwd}", r"$\input{/etc/passwd}$", r"$x^^5cinput$", r"$\text{\input{x}}$",
           r"$\mathrm{\write18{ls}}$", r"$a % b$", r"\immediate\write18{ls}", "$$\\def\\x{1}$$",
           r"\catcode`\@=11", "50% of #1 & $_^~"]


def test_nothing_from_the_file_becomes_a_command():
    doc = published()
    doc["paper"]["title"] = r"\input{/etc/passwd} title"
    doc["claims"][2]["statement"] = " ".join(HOSTILE)
    doc["definitions"][0]["definition"] = "Code:\n```\n\\end{verbatim}\\input{x}\n```\nafter"
    doc["contributors"][1]["name"] = r"A. \write18{ls} Researcher"
    _, f, _ = files(doc)
    tex = f["paper.tex"]
    outside = re.sub(r"\\begin\{verbatim\}.*?\\end\{verbatim\}", "", tex, flags=re.S)
    for command in ("\\input", "\\write", "\\def", "\\catcode", "\\immediate", "^^"):
        assert command not in outside, command
    assert "\\end {verbatim}\\input{x}" in tex                       # a fenced block cannot end its environment
    assert "\\textbackslash{}input" in tex


@pytest.mark.parametrize("tex,ok", [(r"\frac{a}{b}", True), (r"\hat{\beta}_t \sim N(0, \sigma^2)", True),
                                    (r"\begin{cases} 1 & x > 0 \\ 0 & x \le 0 \end{cases}", True),
                                    (r"\input{x}", False), (r"\text{\input{a}}", False), (r"a % b", False),
                                    (r"a^^5c", False), (r"\mathrm{\write18}", False), (r"\label{x}", False),
                                    (r"\begin{verbatim}x\end{verbatim}", False), (r"\text{a_b}", False),
                                    (r"1 & 2", False), (r"a \\ b", False), (r"\foo", False)])
def test_safe_math(tex, ok):
    assert (latex.safe_math(tex) is not None) is ok


def test_align_and_unicode_in_formulae():
    assert latex.safe_math(r"\begin{align} a &= b \end{align}") == r"\begin{aligned} a &= b \end{aligned}"
    assert " ".join(latex.safe_math("x ≤ y").split()) == r"x \leq y"          # a symbol as TeX writes it


def test_text_is_escaped():
    d = latex._Draft()
    assert d.esc("50% of #1 & $x_1^2 ~ {a}\\") == (r"50\% of \#1 \& \$x\_1\textasciicircum{}2 \textasciitilde{} "
                                                     r"\{a\}\textbackslash{}")
    assert d.esc("--seed") == "-{}-seed"                                   # a command line keeps its hyphens
    assert d.esc("α ≤ β") == r"\ensuremath{\alpha} \ensuremath{\leq} \ensuremath{\beta}"
    d.esc("漢")
    assert d.unknown == {"漢"}                                              # declared for pdflatex in the preamble


def test_figures_are_included(tmp_path):
    doc = published()
    png = tmp_path / "fig.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    doc["artefacts"].append({"id": "A3", "kind": "figure", "function": "data_plot", "uri": f"{BASE}/x.png",
                             "description": "Skill by horizon", "shows": ["E1.T1"]})
    doc["claims"][2]["support"][0]["artefacts"] = ["A2", "A3"]
    name, data = latex.build(doc, BASE, figure_file=lambda a: png if a["id"] == "A3" else None)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert "entrylib-2026.000007-v2/figures/figure-1.png" in z.namelist()              # numbered, not by its ID
    tex = z.read("entrylib-2026.000007-v2/paper.tex").decode()
    assert "\\includegraphics[width=\\linewidth]{figures/figure-1.png}" in tex
    assert "\\caption{Skill by horizon}" in tex and "Figure~\\ref{fig:A3}" in tex      # no ID in the caption
    _, f, _ = files(doc)
    assert "\\gap{this figure, from https://entrylib.test/x.png}" in f["paper.tex"]  # not stored here: a gap


@pytest.mark.skipif(not shutil.which("pdflatex") or not shutil.which("bibtex"), reason="no TeX installed")
def test_it_compiles(tmp_path):
    for i, doc in enumerate((published(), _hostile(), theorems())):
        _, data = latex.build(doc, BASE)
        zipfile.ZipFile(io.BytesIO(data)).extractall(tmp_path / str(i))
        work = next((tmp_path / str(i)).iterdir())
        for name in ("paper", "supplement"):
            for cmd in (["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", name],
                        ["bibtex", name],
                        ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", name]):
                r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=120)
                assert r.returncode == 0 or cmd[0] == "bibtex", r.stdout[-2000:]
            assert (work / f"{name}.pdf").exists()


def _hostile():
    doc = published()
    doc["paper"]["title"] = r"\input{/etc/passwd} 100% & more"
    doc["claims"][2]["statement"] = " ".join(HOSTILE) + " 漢字"
    return doc


def test_the_draft_counts_against_validation():
    assert ratelimit.kind_of("POST", "/submissions/draft/2026.000001") == "validate"
    assert ratelimit.kind_of("GET", "/submissions/draft/2026.000001") is None


def lab_made():
    return example("submission-from-lab.json")


def test_only_research_done_with_the_lab_gets_a_draft():
    """A draft is made of research that has no paper yet, never of a claimset that restates a published paper."""
    assert latex.refusal(lab_made()) is None
    assert latex.refusal(example()) is None                                        # written directly as a claimset
    own = lab_made()
    own["paper"]["published_as"] = {"id_type": "doi", "id": "10.1016/j.ijforecast.2025.01.001"}
    assert latex.refusal(own) == "restates"                                        # converted by its authors
    manuscript = lab_made()
    manuscript["artefacts"].append({"id": "A9", "kind": "manuscript", "uri": "https://doi.org/10.1016/j.ijforecast.2025.01.001"})
    assert latex.refusal(manuscript) == "restates"
    other = lab_made()
    other["paper"]["origin"] = "converted"
    assert latex.refusal(other) == "restates"                                      # converted by others
    for key, (short, full) in latex.NO_DRAFT.items():
        assert short and "written directly" in full, key


def publish_one(c, doc=None):
    submit(c, doc or lab_made())
    [ticket] = tickets(sign_in_at(c, "submissions").text)
    assert "published as entrylib:" in confirm(c, ticket).text


def test_the_guarantors_button(app_client, settings):
    """Your submissions offers each published paper's guarantor a LaTeX draft: a confirmation, then the zip."""
    publish_one(app_client)
    assert app_client.get("/submissions/draft/2026.000001", follow_redirects=False).status_code == 303  # signed out
    page = signed_in(app_client).text
    row = page[page.index('<ul class="pub-list">'):page.index("</ul>", page.index('<ul class="pub-list">'))]
    assert 'class="button-quiet pub-action" href="/submissions/draft/2026.000001">LaTeX draft' in row
    r = app_client.get("/submissions/draft/2026.000001")
    assert r.status_code == 200 and "Build the draft" in r.text and 'method="post"' in r.text
    assert "adds nothing" in r.text and "GAPS.md" in r.text
    r = app_client.post("/submissions/draft/2026.000001")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="entrylib-2026.000001-v1-latex.zip"' in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "entrylib-2026.000001-v1/paper.tex" in names
    assert app_client.get("/submissions/draft/not-a-key").status_code == 404
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("UPDATE papers SET status = 'retracted'")
    assert app_client.post("/submissions/draft/2026.000001").status_code == 404           # retracted: no draft
    assert "LaTeX draft" not in signed_in(app_client).text


def test_the_guarantor_is_told_why_a_paper_has_no_draft(app_client):
    """A claimset written directly has the button; one that restates a published paper says why it has none."""
    publish_one(app_client, example())                                             # written directly
    restating = titled("restated")
    restating["paper"]["published_as"] = {"id_type": "doi", "id": "10.1016/j.ijforecast.2025.01.001"}
    publish_one(app_client, restating)
    page = signed_in(app_client).text
    rows = page[page.index('<ul class="pub-list">'):page.index("</ul>", page.index('<ul class="pub-list">'))]
    direct, restated = (rows[rows.index(f'href="/p/{k}"'):] for k in ("2026.000001", "2026.000002"))
    assert 'href="/submissions/draft/2026.000001">LaTeX draft' in direct
    assert 'href="/submissions/draft/2026.000002"' not in rows
    assert "No LaTeX draft: it restates a published paper" in restated
    assert latex.DRAFT_RULE in page                                                # the rule, said once
    for r in (app_client.get("/submissions/draft/2026.000002"), app_client.post("/submissions/draft/2026.000002")):
        assert r.status_code == 403 and "already published" in r.text
    assert app_client.post("/submissions/draft/2026.000001").status_code == 200


def test_someone_else_gets_no_draft(app_client):
    publish_one(app_client)
    signed_in(app_client, as_orcid="0000-0002-1825-0097")
    assert app_client.get("/submissions/draft/2026.000001").status_code == 404
    assert app_client.post("/submissions/draft/2026.000001").status_code == 404


# ---------- a paper, not the claimset's objects (design §4.6, revised 23 November 2026) ----------

def theorems():
    """A small paper of theorems and findings: a short proof, a long one, a numerical check, two findings in one
    section, and two claims that relate to the same work with the same note."""
    doc = published()
    doc["definitions"].append({"id": "D6", "term": "mean", "kind": "concept", "symbol": "$\\mu$",
                               "definition": "The expectation $\\mu = \\mathrm{E}[y]$ of a variable $y$."})
    note = "Smith (2001) defines the mean for every distribution with a finite first moment."
    short = [{"id": "S1", "statement": "\\mathrm{E}[a y] = a\\,\\mathrm{E}[y]", "by": ["D6"]},
             {"id": "S2", "statement": "Hence the mean scales with the variable.", "by": []}]
    long_ = [{"id": f"S{i}", "statement": f"x_{i} = x_{i - 1} + 1", "by": ["C4"]} for i in range(1, 9)]
    doc["evidence"] += [
        {"id": "E2", "profile": "formal", "foundation": "probability", "steps": short},
        {"id": "E3", "profile": "formal", "foundation": "probability", "steps": long_},
        {"id": "E4", "profile": "simulation", "description": "Numerical checks at 40-digit precision (proofs.md, run "
         "RN6): each statement evaluated by numerical integration.",
         "results": [{"id": "R1", "variable": "largest relative error", "value": 3e-41}]},
    ]
    doc["evidence"][0]["description"] = "Lab runs RN1 under plan PL1. Design: " + doc["evidence"][0]["description"]
    doc["claims"] += [
        {"id": "C4", "statement": "For a [[D6:mean]], $\\mathrm{E}[a y] = a\\,\\mathrm{E}[y]$.", "type": "formal",
         "role": "principal", "name": "The mean is linear (in [0, 1] too)",
         "support": [{"kind": "formal_proof", "evidence": "E2"}, {"kind": "simulation", "evidence": "E4",
                                                                  "results": ["E4.R1"]}],
         "relations": [{"type": "extends", "id_type": "doi", "target": "10.1000/x", "reference": "B1", "note": note}]},
        {"id": "C5", "statement": "A long chain ends where it should.", "type": "formal", "role": "secondary",
         "name": "A long chain", "support": [{"kind": "formal_proof", "evidence": "E3"}]},
        {"id": "C6", "statement": "Method M is quick to compute.", "type": "descriptive", "role": "secondary",
         "name": "Speed", "support": [{"kind": "expert_judgement", "holder": "the authors"}]},
    ]
    c2 = next(c for c in doc["claims"] if c["id"] == "C2")
    c2["name"] = "Skill"
    c2["relations"] = [{"type": "extends", "id_type": "doi", "target": "10.1000/x", "reference": "B1", "note": note}]
    doc["paper"]["sections"] = [{"title": "Theory", "claims": ["C4", "C5"]},
                                {"title": "Findings", "claims": ["C2", "C6"]}]
    doc["paper"]["contributions"] = ["C4", "C2"]
    return doc


def test_formal_claims_are_theorems_titled_by_their_names():
    tex = files(theorems())[1]["paper.tex"]
    assert "\\begin{theorem}[{The mean is linear (in [0, 1] too)}]\\label{thm:C4}" in tex     # a bracket cannot end it
    assert "\\begin{proposition}[{A long chain}]\\label{thm:C5}" in tex                      # secondary: a proposition
    assert "\\newtheorem{proposition}[theorem]{Proposition}" in tex                           # one counter
    assert "\\begin{definition}[{mean, $\\mu$}]\\label{def:D6}" in tex                       # before its first use
    assert tex.index("\\label{def:D6}") < tex.index("\\label{thm:C4}")


def test_a_short_proof_follows_its_theorem_and_a_long_one_goes_to_the_appendix():
    tex = files(theorems())[1]["paper.tex"]
    after = tex[tex.index("\\label{thm:C4}"):tex.index("\\label{thm:C5}")]
    assert "\\begin{proof}\n" in after and "\\tag*{by Definition~\\ref{def:D6}}" in after     # the step's `by`
    assert "The proof is in Appendix~\\ref{app:proofs}." in tex
    appendix = tex[tex.index("\\appendix"):]
    assert "\\begin{proof}[Proof of Proposition~\\ref{thm:C5}]" in appendix
    assert "by Theorem~\\ref{thm:C4}" in appendix                                             # a claim, by its number
    assert "The longer proofs are in Appendix~\\ref{app:proofs}." in tex                      # said in the roadmap


def test_the_paper_names_no_id_of_the_record():
    _, f, _ = files(theorems())
    tex = f["paper.tex"]
    prose = re.sub(r"\\(label|ref|hyperref|citep|citet)(\[[^]]*\])?\{[^}]*\}", "", tex)
    for word in ("Claim C", "Claim~C", "Evidence E", "RN1", "PL1", "run RN6", "(hypothesis"):
        assert word not in prose, word
    assert "\\paragraph{Design.} Benchmark of method M" in tex                                # the lab's words gone
    sup = f["supplement.tex"]
    assert "\\paragraph{Claim C4 (Theorem 1 in the paper): The mean is linear" in sup          # the record keeps them
    assert "\\paragraph{Evidence E4.}" in sup and "Proof (in probability)" in sup


def test_numerical_checks_are_said_once_in_the_appendix():
    tex = files(theorems())[1]["paper.tex"]
    checks = tex[tex.index("\\section{Numerical checks}"):]
    assert "Numerical checks at 40-digit precision: each statement" in checks                # the run's file left out
    assert "These checks were made of Theorem~\\ref{thm:C4}." in checks
    assert "largest relative error is at most 3e-41" in checks
    body = tex[tex.index("\\section{Theory}"):tex.index("\\section{Discussion}")]
    assert "3e-41" not in body and "relative error" not in body


def test_findings_have_run_in_headings_and_are_named_by_their_section():
    tex = files(theorems())[1]["paper.tex"]
    assert "\\paragraph{Skill.}\\label{claim:C2}" in tex and "\\paragraph{Speed.}\\label{claim:C6}" in tex
    one = published()
    next(c for c in one["claims"] if c["id"] == "C2")["name"] = "Skill"
    one["paper"]["sections"] = [{"title": "Findings", "claims": ["C2"]}]
    alone = files(one)[1]["paper.tex"]
    assert "\\paragraph{Skill.}" not in alone and "\\label{claim:C2} Method M improves" in alone   # alone: none
    assert "Section~\\ref{sec:part-2}" in tex[tex.index("\\section{Introduction}"):]


def test_the_introduction_motivates_and_holds_no_claim():
    _, f, _ = files(theorems())
    tex = f["paper.tex"]
    intro = tex[tex.index("\\section{Introduction}"):tex.index("\\subsection{Earlier work}")]
    assert "\\ref{thm:" not in intro and "\\item" not in intro and "The mean is linear" not in intro
    assert "Section~\\ref{sec:part-1} (Theory)" in intro                                      # the roadmap stays
    assert "A contribution: The mean is linear (in [0, 1] too)" in f["GAPS.md"]            # given for the motivation


def test_earlier_work_is_a_literature_review():
    _, f, _ = files(theorems())
    tex = f["paper.tex"]
    work = tex[tex.index("\\subsection{Earlier work}"):tex.index("\\section{Theory}")]
    assert "Smith (2001) defines the mean for every distribution with a finite first moment \\citep{B1}." in work
    assert work.count("Smith (2001) defines the mean") == 1                                   # the note once
    assert "extend" not in work and "\\ref{" not in work                                     # no claim of the paper
    assert "B1: The mean is linear (in [0, 1] too) (extends); Skill (extends)" in f["GAPS.md"]


def test_each_gap_comes_with_what_the_claimset_gives():
    _, f, _ = files(theorems())
    gaps = f["GAPS.md"]
    assert "## What the claimset gives towards them" in gaps
    assert "B1: The mean is linear" in gaps                                                   # for the earlier work
    assert "Theorem 1: The mean is linear" in gaps                                            # for the discussion
    assert "a sentence leading into this section (Theory)" in gaps
