import copy
import datetime as dt
import json

import pytest
from claimset.package import build
from claimset.validate import validate
from publishing import BASE, example, write

from portal.classify import classifier_input
from portal.indexer import reindex
from portal.publish import PublishError, publish
from portal.registry import Registry


def test_publish_a_claimset_file(env):
    ctx, tmp = env
    concept, version = publish(write(tmp, example()), **ctx)
    assert (concept, version) == ("entrylib:2026.000001", 1)

    reg = ctx["registry"]
    doc = reg.read("2026/000/entrylib_2026.000001", 1)
    assert validate(doc, published=True).errors == []
    p = doc["paper"]
    assert (p["id"], p["version"], p["status"], p["date"]) == (concept, 1, "active", "2026-11-04")
    assert p["classification"]["subfield"] == "openalex:subfields/1803"
    assert p["classification"]["topics"] == ["openalex:T10001", "openalex:T10002"]
    assert all("verifiability" in c for c in doc["claims"])
    assert "entrylib_2026.000001-v1" in reg.git("tag").split()
    assert reg.read("2026/000/entrylib_2026.000001", 1, "validation.json")["classifier"] == "fake-classifier@1"

    out = ctx["published_dir"]
    assert json.loads((out / "p" / "2026.000001.json").read_text())["paper"]["id"] == concept
    assert (out / "p" / "2026.000001.txt").read_text().startswith("CLAIMSET ")
    assert (out / "p" / "2026.000001@v1.json").exists()
    versions = json.loads((out / "p" / "2026.000001" / "versions.json").read_text())
    assert versions["current_version"] == 1 and versions["versions"][0]["id"] == f"{concept}@v1"
    cards = [json.loads(line) for line in (out / "index.jsonl").read_text().splitlines()]
    assert [c["id"] for c in cards] == [concept]
    assert cards[0]["principal_claims"] and cards[0]["url"] == f"{BASE}/p/2026.000001.json"

    conn = ctx["conn"]
    assert conn.execute("SELECT current_version, status FROM papers").fetchall() == [(1, "active")]
    n_claims = len(doc["claims"])
    assert conn.execute("SELECT count(*) FROM claims").fetchone()[0] == n_claims


def test_identifiers_are_sequential(env):
    ctx, tmp = env
    a, _ = publish(write(tmp, example()), **ctx)
    b, _ = publish(write(tmp, example(), "other.claimset.json"), **ctx)
    assert (a, b) == ("entrylib:2026.000001", "entrylib:2026.000002")


def test_publish_a_package_with_files_and_a_lab_record(env):
    ctx, tmp = env
    study = tmp / "study"
    (study / "files").mkdir(parents=True)
    (study / "files" / "fig1.png").write_bytes(b"image bytes")
    (study / "files" / "lab.jsonl").write_text('{"seq": 1}\n', encoding="utf-8")
    doc = example()
    doc["artefacts"] += [
        {"id": "A3", "availability": {"level": "public"}, "kind": "figure", "function": "diagram",
         "description": "Design of the study.", "uri": "files/fig1.png", "licence": "CC-BY-4.0"},
        {"id": "A4", "availability": {"level": "public"}, "kind": "lab_record", "uri": "files/lab.jsonl",
         "licence": "CC-BY-4.0"}]
    src = write(study, doc)
    build(src, tmp / "paper.zip")
    concept, _ = publish(tmp / "paper.zip", **ctx)

    published = ctx["registry"].read("2026/000/entrylib_2026.000001", 1)
    by_id = {a["id"]: a for a in published["artefacts"]}
    digest = by_id["A3"]["version"].removeprefix("sha256:")
    assert by_id["A3"]["uri"] == f"{BASE}/p/2026.000001/v1/files/files/fig1.png"
    assert (ctx["published_dir"] / "p" / "2026.000001" / "v1" / "files" / "files" / "fig1.png").read_bytes() == \
        b"image bytes"
    assert len(digest) == 64 and not (ctx["published_dir"] / "files").exists()
    lab = ctx["registry"].version_dir("2026/000/entrylib_2026.000001", 1) / "lab.jsonl"
    assert lab.read_text() == '{"seq": 1}\n'
    versions = json.loads((ctx["published_dir"] / "p" / "2026.000001" / "versions.json").read_text())
    assert versions["versions"][0]["lab_record"]["copy"] == f"{BASE}/p/2026.000001/v1/lab.jsonl"
    assert (ctx["published_dir"] / "p" / "2026.000001" / "v1" / "lab.jsonl").exists()


def test_an_invalid_submission_is_refused_and_leaves_no_trace(env):
    ctx, tmp = env
    doc = example()
    doc["claims"][0]["support"] = []                                  # rule 2: every claim has support
    with pytest.raises(PublishError) as exc:
        publish(write(tmp, doc), **ctx)
    assert any(e["rule"] == "2" for e in exc.value.errors)
    assert ctx["registry"].folders() == []
    assert ctx["conn"].execute("SELECT count(*) FROM id_counters").fetchone()[0] == 0


def test_local_references_are_refused(env):
    ctx, tmp = env
    doc = example()
    doc["claims"][0].setdefault("relations", []).append(
        {"type": "extends", "target": "other-study/paper.claimset.json#C1", "id_type": "claimset_local"})
    with pytest.raises(PublishError, match="claimset_local"):
        publish(write(tmp, doc), **ctx)


def test_correction(env):
    ctx, tmp = env
    concept, _ = publish(write(tmp, example()), **ctx)
    doc = example()
    cid = doc["claims"][0]["id"]
    doc["claims"][0]["statement"] = doc["claims"][0]["statement"].rstrip(".") + " in every run."
    doc["paper"]["id"] = concept
    doc["paper"]["correction_reason"] = "The statement of the first claim omitted that it held in every run."
    concept2, version = publish(write(tmp, doc, "fixed.claimset.json"), **{**ctx, "today": dt.date(2026, 11, 5)})
    assert (concept2, version) == (concept, 2)

    v2 = ctx["registry"].read("2026/000/entrylib_2026.000001", 2)
    assert validate(v2, published=True).errors == []
    p = v2["paper"]
    assert (p["status"], p["previous_version"], p["date"]) == ("corrected", f"{concept}@v1", "2026-11-05")
    assert p["status_notice"]["statement"] == doc["paper"]["correction_reason"]
    g = next(c for c in doc["contributors"] if "guarantor" in c.get("positions", []))
    assert p["status_notice"]["issued_by"] == f"{g['name']} (ORCID {g['orcid']})"
    assert p["changes"] and all(ch["reason"] == doc["paper"]["correction_reason"] for ch in p["changes"])
    assert any(cid in ch["path"] or "/claims/0" in ch["path"] for ch in p["changes"])

    out = ctx["published_dir"] / "p"
    assert json.loads((out / "2026.000001.json").read_text())["paper"]["version"] == 2
    assert json.loads((out / "2026.000001@v1.json").read_text())["paper"]["version"] == 1
    versions = json.loads((out / "2026.000001" / "versions.json").read_text())
    assert [v["version"] for v in versions["versions"]] == [1, 2]
    assert ctx["conn"].execute("SELECT current_version, status FROM papers").fetchone() == (2, "corrected")


def test_a_correction_must_name_a_published_claimset(env):
    ctx, tmp = env
    doc = example()
    doc["paper"]["id"] = "entrylib:2026.000999"
    doc["paper"]["correction_reason"] = "Something was wrong."
    with pytest.raises(PublishError, match="not published here"):
        publish(write(tmp, doc), **ctx)


def test_reindex_rebuilds_everything_from_the_registry(env):
    ctx, tmp = env
    publish(write(tmp, example()), **ctx)
    publish(write(tmp, example(), "b.claimset.json"), **ctx)
    conn = ctx["conn"]
    before = conn.execute("SELECT concept_id, current_version, title FROM papers ORDER BY 1").fetchall()
    index_before = (ctx["published_dir"] / "index.jsonl").read_text()

    conn.execute("DELETE FROM papers")
    conn.execute("DELETE FROM id_counters")
    (ctx["published_dir"] / "index.jsonl").unlink()
    (ctx["published_dir"] / "p" / "2026.000001.json").unlink()

    folders = reindex(conn, ctx["registry"], ctx["published_dir"], BASE)
    assert folders == ["2026/000/entrylib_2026.000001", "2026/000/entrylib_2026.000002"]
    assert conn.execute("SELECT concept_id, current_version, title FROM papers ORDER BY 1").fetchall() == before
    assert (ctx["published_dir"] / "index.jsonl").read_text() == index_before
    assert (ctx["published_dir"] / "p" / "2026.000001.json").exists()
    concept, _ = publish(write(tmp, example(), "c.claimset.json"), **ctx)
    assert concept == "entrylib:2026.000003"                             # counters restored from the registry


def test_classifier_input_uses_title_and_principal_claims():
    doc = example()
    inp = classifier_input(doc)
    assert inp["title"] == doc["paper"]["title"]
    first = doc["paper"]["contributions"][0]
    statement = next(c["statement"] for c in doc["claims"] if c["id"] == first)
    assert statement in inp["abstract"]


def test_registry_never_rewrites_a_version(tmp_path):
    from portal.registry import RegistryError
    reg = Registry(tmp_path / "r").init()
    reg.write_version("2026/000/entrylib_2026.000001", 1, {"claimset.json": "{}\n"}, "first")
    with pytest.raises(RegistryError):
        reg.write_version("2026/000/entrylib_2026.000001", 1, {"claimset.json": "{}\n"}, "again")
    assert copy.copy(reg.versions("2026/000/entrylib_2026.000001")) == [1]


def test_a_classifier_outage_uses_up_no_identifiers(env):
    from portal.classify import ClassifierError
    ctx, tmp = env

    def down(doc):
        raise ClassifierError("classifier unavailable: connection refused")
    for _ in range(3):
        with pytest.raises(ClassifierError):
            publish(write(tmp, example()), **{**ctx, "classifier": down})
    assert ctx["conn"].execute("SELECT count(*) FROM id_counters").fetchone()[0] == 0
    concept, _ = publish(write(tmp, example()), **ctx)
    assert concept == "entrylib:2026.000001"


def test_registry_folders_are_found_by_year_and_block(tmp_path):
    reg = Registry(tmp_path / "reg").init()
    for folder in ("2027/000/entrylib_2027.000001", "2026/001/entrylib_2026.001350", "2026/000/entrylib_2026.000002"):
        reg.write_version(folder, 1, {"claimset.json": "{}\n"}, f"Publish {folder}")
    (tmp_path / "reg" / "README.md").write_text("x\n")
    assert reg.folders() == ["2026/000/entrylib_2026.000002", "2026/001/entrylib_2026.001350",
                             "2027/000/entrylib_2027.000001"]
    assert "entrylib_2026.001350-v1" in reg.git("tag").split()


def test_a_failed_reindex_leaves_the_index_as_it_was(env, monkeypatch):
    ctx, tmp = env
    publish(write(tmp, example()), **ctx)
    publish(write(tmp, example(), "b.claimset.json"), **ctx)
    conn = ctx["conn"]
    before = conn.execute("SELECT concept_id, current_version, title FROM papers ORDER BY 1").fetchall()
    claims = conn.execute("SELECT count(*) FROM claims").fetchone()

    from portal import indexer
    index_version = indexer.index_version

    def failing(conn, registry, folder, n, *args):
        if folder.endswith("000002"):
            raise RuntimeError("indexing failed")
        return index_version(conn, registry, folder, n, *args)

    monkeypatch.setattr(indexer, "index_version", failing)
    with pytest.raises(RuntimeError):
        reindex(conn, ctx["registry"], ctx["published_dir"], BASE)
    assert conn.execute("SELECT concept_id, current_version, title FROM papers ORDER BY 1").fetchall() == before
    assert conn.execute("SELECT count(*) FROM claims").fetchone() == claims
