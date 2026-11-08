"""`portal check` on registry pull requests: built on real git repositories, without the database."""

import json
import subprocess

import pytest
from claimset.lab.core import Lab
from claimset.validate import validate
from publishing import example

from portal.check import check
from portal.registry import Registry, dump

CONCEPT = "entrylib:2026.000001"
FOLDER = "2026/000/entrylib_2026.000001"


def published(version=1, concept=CONCEPT):
    """A valid published file: the published example under the given identifier and version."""
    doc = example("published-native.json")
    doc["paper"]["id"] = concept
    doc["paper"]["version"] = version
    if version > 1:
        doc["paper"]["status"] = "corrected"
        doc["paper"]["previous_version"] = f"{concept}@v{version - 1}"
        doc["paper"]["status_notice"] = {"date": "2026-11-05", "reason_code": "correction",
                                         "statement": "A number in C1 was misreported.", "issued_by": "platform"}
        doc["paper"]["changes"] = [{"op": "replace", "path": "/claims/0/statement",
                                    "value": doc["claims"][0]["statement"], "reason": "A number was misreported."}]
    assert validate(doc, published=True).errors == []
    return doc


def version_files(doc, lab=None):
    files = {"claimset.json": dump(doc), "validation.json": dump({"validator": "claimset test"})}
    if lab is not None:
        files["lab.jsonl"] = lab
    return files


@pytest.fixture
def repo(tmp_path):
    """A registry with one published claimset on main, and a pull request branch to add to."""
    reg = Registry(tmp_path / "registry").init()
    (reg.path / "README.md").write_text("Registry\n")
    reg.git("add", "README.md")
    reg.git("commit", "-q", "-m", "init")
    reg.write_version(FOLDER, 1, version_files(published()), f"Publish {CONCEPT}@v1")
    reg.git("checkout", "-q", "-b", "pr")
    return reg


def commit(reg, files):
    """Write {path: text or None to delete} and commit on the pull request branch."""
    for path, text in files.items():
        p = reg.path / path
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    reg.git("add", "-A")
    reg.git("commit", "-q", "-m", "change")


def add_version(reg, folder, n, files):
    commit(reg, {f"{folder}/v{n}/{name}": text for name, text in files.items()})


def lab_record(tmp_path):
    lab = Lab.create(tmp_path / "lab", "Test study")
    human = lab.append("actor", {"kind": "human", "name": "A. Researcher", "orcid": "0000-0000-0000-0000"},
                       by="AC1")["id"]
    lab.append("question", {"text": "Does X help?"}, by=human)
    return lab.log_path.read_text(encoding="utf-8")


def problems(r):
    return [c for c, _ in r.problems]


def test_a_new_claimset_passes(repo):
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(published(concept="entrylib:2026.000002")))
    r = check(repo.path, "main")
    assert r.ok, r.problems
    assert (r.kind, r.published) == ("publication", "entrylib:2026.000002@v1")
    assert "Passed" in r.markdown()


def test_a_correction_passes(repo):
    add_version(repo, FOLDER, 2, version_files(published(version=2)))
    r = check(repo.path, "main")
    assert r.ok, r.problems


def test_a_lab_record_is_verified(repo, tmp_path):
    good = lab_record(tmp_path)
    add_version(repo, "2026/000/entrylib_2026.000002", 1,
                version_files(published(concept="entrylib:2026.000002"), lab=good))
    r = check(repo.path, "main")
    assert r.ok and any("hash chain verified" in n for n in r.notes), (r.problems, r.notes)


def test_a_broken_lab_record_fails(repo, tmp_path):
    lines = lab_record(tmp_path).splitlines()
    event = json.loads(lines[1])
    event["body"]["name"] = "Someone Else"                              # edited after the fact
    lines[1] = json.dumps(event)
    add_version(repo, "2026/000/entrylib_2026.000002", 1,
                version_files(published(concept="entrylib:2026.000002"), lab="\n".join(lines) + "\n"))
    r = check(repo.path, "main")
    assert not r.ok and any(c.startswith("lab record") for c in problems(r))


def test_a_published_version_is_never_changed(repo):
    path = f"{FOLDER}/v1/claimset.json"
    doc = json.loads((repo.path / path).read_text())
    doc["paper"]["title"] = "A better title"
    commit(repo, {path: dump(doc)})
    assert "append-only" in problems(check(repo.path, "main"))


def test_a_published_version_is_never_deleted(repo):
    commit(repo, {f"{FOLDER}/v1/validation.json": None})
    assert "append-only" in problems(check(repo.path, "main"))


def test_one_version_per_pull_request(repo):
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(published(concept="entrylib:2026.000002")))
    add_version(repo, "2026/000/entrylib_2026.000003", 1, version_files(published(concept="entrylib:2026.000003")))
    assert "scope" in problems(check(repo.path, "main"))


def test_a_publication_changes_nothing_else(repo):
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(published(concept="entrylib:2026.000002")))
    commit(repo, {"README.md": "Changed\n"})
    assert "scope" in problems(check(repo.path, "main"))


def test_the_identifier_must_name_the_folder(repo):
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(published(concept="entrylib:2026.000009")))
    assert "identifier" in problems(check(repo.path, "main"))


def test_a_version_must_be_in_its_year_and_block(repo):
    doc = published(concept="entrylib:2026.000002")
    add_version(repo, "2026/001/entrylib_2026.000002", 1, version_files(doc))        # wrong block
    assert "identifier" in problems(check(repo.path, "main"))


def test_the_flat_layout_is_refused(repo):
    add_version(repo, "entrylib_2026.000002", 1, version_files(published(concept="entrylib:2026.000002")))
    assert "maintenance" in problems(check(repo.path, "main"))


def test_versions_follow_in_order(repo):
    add_version(repo, FOLDER, 3, version_files(published(version=3)))
    assert "version" in problems(check(repo.path, "main"))


def test_nothing_is_added_to_a_published_version(repo, tmp_path):
    commit(repo, {f"{FOLDER}/v1/lab.jsonl": lab_record(tmp_path)})
    assert problems(check(repo.path, "main")) == ["append-only"]


def test_extra_and_missing_files(repo):
    files = version_files(published(concept="entrylib:2026.000002"))
    files["notes.txt"] = "x"
    del files["validation.json"]
    add_version(repo, "2026/000/entrylib_2026.000002", 1, files)
    assert problems(check(repo.path, "main")).count("files") == 2


def test_an_invalid_file_fails_the_validator(repo):
    doc = published(concept="entrylib:2026.000002")
    doc["claims"][0]["support"] = []
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(doc))
    assert "validator rule 2" in problems(check(repo.path, "main"))


def test_screening_runs_on_the_published_file(repo):
    doc = published(concept="entrylib:2026.000002")
    doc["claims"][0]["statement"] += "‮"
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(doc))
    assert "screening SI1" in problems(check(repo.path, "main"))


def test_maintenance_pull_requests(repo):
    commit(repo, {"README.md": "The EntryLib registry\n", ".github/workflows/check.yml": "name: check\n"})
    r = check(repo.path, "main")
    assert r.ok and r.kind == "maintenance"


def test_maintenance_may_not_add_other_files(repo):
    commit(repo, {"scripts/tool.py": "print(1)\n"})
    assert "maintenance" in problems(check(repo.path, "main"))


def test_cli_exit_code_and_summary(repo, tmp_path, monkeypatch):
    from portal.cli import main
    add_version(repo, "2026/000/entrylib_2026.000002", 1, version_files(published(concept="entrylib:2026.000002")))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main(["check", "--registry", str(repo.path), "--base", "main"]) == 0
    assert "Passed" in summary.read_text()
    commit(repo, {f"{FOLDER}/v1/validation.json": None})
    assert main(["check", "--registry", str(repo.path), "--base", "main"]) == 1


def test_git_is_available():
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0
