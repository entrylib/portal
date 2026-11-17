"""A claimset cited by another is written as a reference by its guarantor (design §7.4): "Svetunkov (2026)"."""

from publishing import example, write

from portal import indexer
from portal.publish import publish


def test_a_cited_claimset_is_written_by_its_guarantor(env):
    ctx, tmp = env
    doc = example()
    concept, version = publish(write(tmp, doc), **ctx)
    conn = ctx["conn"]
    people = [c for c in doc["contributors"] if "guarantor" in (c.get("positions") or [])]
    surname = people[0]["name"].split()[-1]
    title = doc["paper"]["title"].rstrip(".")
    year = conn.execute("SELECT file->'paper'->>'date' FROM versions WHERE concept_id = %s",
                        (concept,)).fetchone()[0][:4]
    targets = [concept, f"{concept}@v1#C1", f"{concept}@v7", "entrylib:2026.999999#C1", "not an identifier", None]
    texts = indexer.claimset_texts(conn, targets)
    assert set(texts) == {concept, f"{concept}@v1#C1"}           # a version or a claimset not published: left out
    for written in texts.values():
        assert written.startswith(f"{surname}, ") and written.endswith(f"({year}). {title}. EntryLib.")
    assert "Claude" not in texts[concept]                         # an agent is no author of the reference


def test_the_surname_comes_first():
    assert indexer._surname_first("Ivan Svetunkov") == "Svetunkov, I."
    assert indexer._surname_first("Ada Maria Example") == "Example, A. M."
    assert indexer._surname_first("Plato") == "Plato"
