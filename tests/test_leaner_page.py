"""A leaner paper page (design §7.4, decided 22 November 2026): each fact said once, where it is used."""

from portal import score_html, site


def test_written_with_names_each_model_once_with_all_its_labels():
    models = [{"id": "M1", "provider": "Anthropic", "name": "Claude Opus", "version": "5.5"}]
    agents = [{"type": "agent", "models": ["M1"], "harness": {"name": "Claude Code"}},
              {"type": "agent", "models": ["M1"], "label": "drafting", "harness": {"name": "Claude Code"}},
              {"type": "agent", "models": ["M1"], "label": "correction"},
              {"type": "agent", "models": ["M1"], "label": "drafting"}]
    out = site._agents(agents, models)
    assert len(out) == 1
    name = site.pageview.agent_name(agents[0], models)
    assert f"{name} <span class=\"cs-label\">· drafting, correction</span></span>" in out[0]
    assert out[0].count("<svg") == 1


def test_the_cite_row_copies_the_identifier_and_the_citation():
    row = site._cite_row("entrylib:2026.000001@v2", "Doe, J. (2026). A title. EntryLib.",
                         '<a href="/a.bib" download>BibTeX</a><a href="/a.ris" download>RIS</a>')
    assert '<code class="cite-id" data-copy-self title="Copy the identifier">entrylib:2026.000001@v2</code>' in row
    assert 'data-copy="cite-text"' in row and ">Text</button>" in row and "<details" not in row
    assert '<span class="cite-text" id="cite-text" hidden>Doe, J. (2026). A title. EntryLib.</span>' in row
    assert row.index(">Text</button>") < row.index(">BibTeX</a>") < row.index(">RIS</a>")


def test_the_status_tag_opens_what_changed():
    p = {"status": "corrected", "changes": [], "status_notice": {"date": "2026-11-18", "statement": "Adds a summary.",
                                                                "reason_code": "other", "issued_by": "A. Author"}}
    tag, note = site.status_top(p)
    assert tag.startswith('<a class="status status-neutral status-toggle" href="#versions" data-toggle="status-note"')
    assert note.startswith('<div class="notice notice-neutral status-note" id="status-note" hidden>')
    assert "Adds a summary." in note and "By A. Author" in note and "<summary>" not in note
    assert site.status_top({"status": "active"}) == ("", "")
    tag, note = site.status_top({"status": "retracted", "status_notice": {"date": "2026-11-18", "statement": "x"}})
    assert "status-toggle" not in tag and "notice" in note                # a retraction keeps its notice in full


def test_the_breakdown_lists_each_kind_of_problem_once():
    scores = {"problems": {
        "P1": {"check": "no_limitation", "group": "open", "cost": 10, "claims": ["C9"], "objects": [],
               "text": "A principal claim that declares no limitation", "fix": "Declare one."},
        "P2": {"check": "unchecked_assumption", "group": "open", "cost": 3, "claims": ["C1", "C2"],
               "objects": ["C30"], "text": "Assumption C30 is not checked: The errors are independent.",
               "fix": "Test the assumption."},
        "P3": {"check": "unchecked_assumption", "group": "open", "cost": 1, "claims": ["C1"],
               "objects": ["C31"], "text": "Assumption C31 is not checked: Sizes are continuous.",
               "fix": "Test the assumption."}}}
    html = score_html._paper_problems(scores, ["P1", "P2", "P3"])
    assert html.count("<li>") == 2 and html.count("Test the assumption.") == 1
    assert "−1 to −3" in html and "Assumptions not checked" in html
    assert '<td><a href="#C30">C30</a></td><td>The errors are independent.</td><td class="num">−3</td>' in html
    assert '<td class="num" title="C1, C2">2 claims</td>' in html and '<td class="num" title="C1">1 claim</td>' in html
    one = score_html._paper_problems(scores, ["P1", "P2"])                # one of a kind: an entry of its own
    assert "<table" not in one and one.count("<li>") == 2
