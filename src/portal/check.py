"""`portal check`: the registry's checks on a pull request (design §6), run by the registry's GitHub Actions.

A pull request either publishes one version or maintains the repository, never both:

- **Publication**: adds exactly one folder `<year>/<block>/<name>/v<n>/` (revision spec §2.4) holding
  `claimset.json`, `validation.json` and optionally `lab.jsonl`, and changes nothing else. The version must be
  the claimset's next, its file must be a valid published file whose identifier names the folder, it must pass the
  deterministic screening, and its lab record must verify.
- **Notice**: appends one retraction or removal to a claimset's `notices.json` (notices.py); a removal also deletes
  every file of the claimset's versions, and nothing else.
- **Maintenance**: changes only the repository's own files (README, LICENSE, `.github/`), and no claimset.

A published file is never modified, and deleted only by a removal: any other pull request that touches an existing
version fails.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from claimset.lab.core import verify_events
from claimset.revision import record_folder
from claimset.validate import validate

from .screening import SCREENING_VERSION, screen

VERSION_FILES = {"claimset.json", "validation.json", "lab.jsonl"}
REQUIRED_FILES = {"claimset.json", "validation.json"}
REPOSITORY_FILES = re.compile(r"^(?:README\.md|LICENSE|NOTICE|\.gitignore|\.gitattributes|\.github/.+)$")
VERSION_PATH = re.compile(r"^(?P<folder>\d{4}/\d{3,}/[^/]+)/v(?P<n>[1-9]\d*)/(?P<name>[^/]+)$")
NOTICES_PATH = re.compile(r"^(?P<folder>\d{4}/\d{3,}/[^/]+)/notices\.json$")


@dataclass
class Result:
    kind: str = "maintenance"                       # publication | maintenance
    published: str | None = None                    # entrylib:…@v<n>
    problems: list = field(default_factory=list)    # [(check, message)]
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems

    def fail(self, check, message):
        self.problems.append((check, message))

    def markdown(self):
        what = {"publication": "publication of", "notice": "notice for"}.get(self.kind)
        head = (f"### {'Passed' if self.ok else 'Failed'}: "
                + (f"{what} `{self.published}`" if self.published and what else f"{self.kind} pull request"))
        lines = [head, ""]
        lines += [f"- **{check}**: {msg}" for check, msg in self.problems]
        lines += [f"- {n}" for n in self.notes]
        return "\n".join(lines) + "\n"


def _git(repo, *args):
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


def changes(repo, base):
    """[(status, path)] of what HEAD changes against the merge base with `base`."""
    out = _git(repo, "diff", "--name-status", "--no-renames", f"{base}...HEAD")
    return [(line.split("\t", 1)[0], line.split("\t", 1)[1]) for line in out.splitlines() if line.strip()]


def _exists_at(repo, ref, path):
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{ref}:{path}"],
                          capture_output=True).returncode == 0


def llm_screening(doc):
    """The LLM screening (design §6). Not switched on yet: a provider is chosen before launch."""
    return None


def check(repo, base):
    """Check the pull request checked out at `repo` (HEAD) against `base` (e.g. origin/main)."""
    r = Result()
    repo = Path(repo)
    diff = changes(repo, base)
    if not diff:
        r.fail("changes", "the pull request changes nothing")
        return r

    if any(NOTICES_PATH.match(p) for _, p in diff):
        return _check_notice(repo, base, diff, r)

    in_versions = [(s, p) for s, p in diff if VERSION_PATH.match(p)]
    other = [(s, p) for s, p in diff if not VERSION_PATH.match(p)]
    for s, p in diff:
        if s != "A" and VERSION_PATH.match(p):
            r.fail("append-only", f"{p} is {'deleted' if s == 'D' else 'modified'}; published versions are never "
                                  f"changed")
    if not in_versions:
        for _, p in other:
            if not REPOSITORY_FILES.match(p):
                r.fail("maintenance", f"{p} is not a repository file (README, LICENSE, .github/); claimsets are "
                                      f"published only as <year>/<block>/<name>/v<n>/")
        r.notes.append("maintenance pull request: no claimset changed")
        return r

    # A publication.
    r.kind = "publication"
    for _, p in other:
        r.fail("scope", f"{p}: a publication adds one version and changes nothing else")
    targets = {(m["folder"], int(m["n"])) for _, p in in_versions if (m := VERSION_PATH.match(p))}
    if len(targets) != 1:
        r.fail("scope", f"a publication adds exactly one version; this adds {len(targets)}: "
                        + ", ".join(f"{f}/v{n}" for f, n in sorted(targets)))
        return r
    (folder, n), = targets
    if _exists_at(repo, base, f"{folder}/v{n}"):
        r.fail("append-only", f"{folder}/v{n} is published already; nothing is added to a published version")
        return r
    names = {VERSION_PATH.match(p)["name"] for _, p in in_versions}
    for name in sorted(names - VERSION_FILES):
        r.fail("files", f"{folder}/v{n}/{name} is not a registry document ({', '.join(sorted(VERSION_FILES))})")
    for name in sorted(REQUIRED_FILES - names):
        r.fail("files", f"{folder}/v{n}/{name} is missing")
    if not r.ok:
        return r

    vdir = repo / folder / f"v{n}"
    try:
        doc = json.loads((vdir / "claimset.json").read_text(encoding="utf-8"))
        json.loads((vdir / "validation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        r.fail("files", f"not readable JSON: {exc}")
        return r
    paper = doc.get("paper") if isinstance(doc.get("paper"), dict) else {}
    concept = paper.get("id")
    r.published = f"{concept}@v{n}"

    # The version is where its identifier says, and is the claimset's next.
    try:
        expected = record_folder(concept)
    except ValueError as exc:
        r.fail("identifier", str(exc))
        expected = None
    if expected and expected != folder:
        r.fail("identifier", f"the file names {concept}, whose folder is {expected}, not {folder}")
    if paper.get("version") != n:
        r.fail("version", f"the file says version {paper.get('version')!r}, the folder v{n}")
    if n == 1 and _exists_at(repo, base, folder):     # a v1 in an existing folder (another claimset's)
        r.fail("version", f"{folder} exists already; a new claimset needs a new identifier")
    if n > 1:
        if not _exists_at(repo, base, f"{folder}/v{n - 1}/claimset.json"):
            r.fail("version", f"v{n} needs v{n - 1}, which is not in the registry")
        if paper.get("previous_version") != f"{concept}@v{n - 1}":
            r.fail("version", f"previous_version must be {concept}@v{n - 1}")
    if _exists_at(repo, base, f"{folder}/v{n + 1}"):
        r.fail("version", f"{folder}/v{n + 1} exists already")

    # The claimset package's rules for a published file.
    rep = validate(doc, published=True)
    for e in rep.errors:
        r.fail(f"validator rule {e['rule']}", f"{e['where']}: {e['message']}")
    r.notes.append(f"validator: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")

    # Screening.
    for f in screen(doc):
        r.fail(f"screening {f['rule']}", f"{f['where']}: {f['message']}")
    r.notes.append(f"screening: {SCREENING_VERSION}")
    llm = llm_screening(doc)
    r.notes.append("LLM screening: off (no provider chosen yet)" if llm is None else f"LLM screening: {llm}")

    # The lab record verifies.
    lab = vdir / "lab.jsonl"
    if lab.exists():
        try:
            events = [json.loads(line) for line in lab.read_text(encoding="utf-8").splitlines() if line.strip()]
        except ValueError as exc:
            r.fail("lab record", f"not JSON Lines: {exc}")
        else:
            out = verify_events(events)
            for e in out["errors"]:
                r.fail(f"lab record {e['rule']}", f"seq {e['seq']} {e.get('id') or ''}: {e['message']}")
            r.notes.append(f"lab record: {out['events']} event(s), hash chain "
                           f"{'verified' if out['ok'] else 'NOT verified'}")
    return r


def _show(repo, ref, path):
    return _git(repo, "show", f"{ref}:{path}")


def _check_notice(repo, base, diff, r):
    """A notice pull request: one retraction or removal appended to a claimset's notices.json."""
    from .notices import ACTIONS, REASONS
    r.kind = "notice"
    folders = {m["folder"] for _, p in diff if (m := NOTICES_PATH.match(p))}
    if len(folders) != 1:
        r.fail("scope", "a notice pull request changes one claimset's notices.json")
        return r
    folder, = folders
    deleted = set()
    for s, p in diff:
        if NOTICES_PATH.match(p):
            if s not in ("A", "M"):
                r.fail("append-only", f"{p} is {'deleted' if s == 'D' else 'changed'}; notices are only added")
        elif (m := VERSION_PATH.match(p)) and m["folder"] == folder and s == "D":
            deleted.add(p)
        else:
            r.fail("scope", f"{p}: a notice pull request changes only {folder}/notices.json and, for a removal, "
                            f"deletes the claimset's versions")
    try:
        new = json.loads((repo / folder / "notices.json").read_text(encoding="utf-8"))
        old = json.loads(_show(repo, base, f"{folder}/notices.json")) if _exists_at(repo, base,
                                                                                   f"{folder}/notices.json") else None
    except (OSError, ValueError, RuntimeError) as exc:
        r.fail("files", f"{folder}/notices.json is not readable JSON: {exc}")
        return r
    items = new.get("notices") if isinstance(new, dict) else None
    before = (old or {}).get("notices") or []
    if not isinstance(items, list) or items[:len(before)] != before or len(items) != len(before) + 1:
        r.fail("append-only", "notices.json must keep every earlier notice and add exactly one")
        return r
    try:
        if record_folder(new.get("id")) != folder:
            r.fail("identifier", f"notices.json names {new.get('id')!r}, whose folder is not {folder}")
    except (ValueError, TypeError) as exc:
        r.fail("identifier", str(exc))
    if before and before[-1].get("action") == "removed":
        r.fail("final", "the claimset was removed already; a removal is final")
    n = items[-1]
    action = n.get("action") if isinstance(n, dict) else None
    if action not in ACTIONS.values():
        r.fail("notice", f"action must be one of {sorted(ACTIONS.values())}")
        return r
    kind = {v: k for k, v in ACTIONS.items()}[action]
    if n.get("reason_code") not in REASONS[kind]:
        r.fail("notice", f"reason_code {n.get('reason_code')!r} is not a reason for {action}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(n.get("date") or "")):
        r.fail("notice", "date must be YYYY-MM-DD")
    if not isinstance(n.get("issued_by"), str) or not n["issued_by"].strip():
        r.fail("notice", "issued_by must say who acted")
    if not isinstance(n.get("statement", ""), str):
        r.fail("notice", "statement must be text")
    for f in screen({"statement": n.get("statement") or "", "issued_by": n.get("issued_by") or ""}):
        r.fail(f"screening {f['rule']}", f"{f['where']}: {f['message']}")
    present = set(_git(repo, "ls-tree", "-r", "--name-only", base, "--", f"{folder}/").split())
    in_versions = {p for p in present if VERSION_PATH.match(p)}
    if action == "removed":
        if deleted != in_versions:
            r.fail("removal", "a removal deletes every file of the claimset's versions: "
                              f"{len(in_versions - deleted)} left")
    elif deleted:
        r.fail("append-only", "a retraction deletes nothing")
    r.published = new.get("id")
    r.notes.append(f"notice: {action} ({n.get('reason_code')}) by {n.get('issued_by')}")
    return r
