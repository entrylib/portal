"""The registry: a git repository holding the published record (revision spec §2.4).

    <year>/<block>/<name>/v1/claimset.json  v1/lab.jsonl  v1/validation.json
    <year>/<block>/<name>/v2/claimset.json  ...
    <year>/<block>/<name>/notices.json      EntryLib's retractions and removals (design §7.5); a removed claimset
                                            keeps only this

A claimset's folder (its path, `2026/000/entrylib_2026.000123`) follows from its identifier
(`claimset.revision.record_folder`). Only the platform writes to the registry, one commit per published version,
tagged `<name>-v<n>`. This module works on a
local clone; pushing to the hosted registry happens elsewhere.
"""

import json
import os
import re
import subprocess
from pathlib import Path

VERSION_DIR = re.compile(r"^v([1-9]\d*)$")
NOTICES = "notices.json"
YEAR_DIR = re.compile(r"^\d{4}$")
BLOCK_DIR = re.compile(r"^\d{3,}$")


class RegistryError(Exception):
    pass


def tag_name(folder, n):
    """The tag of version n of the claimset in `folder`: its name (the folder's last part) and the version,
    `entrylib_2026.000123-v2` (revision spec §2.4)."""
    return f"{folder.rsplit('/', 1)[-1]}-v{n}"


def dump(obj):
    """How the registry writes JSON: stable, readable, UTF-8."""
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


class Registry:
    def __init__(self, path, author_name="EntryLib", author_email="registry@entrylib.org"):
        self.path = Path(path)
        self.env = {**os.environ, "GIT_AUTHOR_NAME": author_name, "GIT_AUTHOR_EMAIL": author_email,
                    "GIT_COMMITTER_NAME": author_name, "GIT_COMMITTER_EMAIL": author_email}

    def git(self, *args):
        res = subprocess.run(["git", "-C", str(self.path), *args], env=self.env, capture_output=True, text=True)
        if res.returncode != 0:
            raise RegistryError(f"git {' '.join(args)}: {res.stderr.strip()}")
        return res.stdout

    def init(self):
        """Create an empty registry (for tests and a first setup)."""
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self.git("init", "-q", "-b", "main")
        return self

    def version_dir(self, folder, n):
        return self.path / folder / f"v{n}"

    def versions(self, folder):
        """The version numbers present for a claimset, in order."""
        d = self.path / folder
        if not d.is_dir():
            return []
        return sorted(int(m.group(1)) for p in d.iterdir() if p.is_dir() and (m := VERSION_DIR.match(p.name)))

    def folders(self):
        """Every claimset folder in the registry (`<year>/<block>/<name>`)."""
        out = []
        for year in sorted(p for p in self.path.iterdir() if p.is_dir() and YEAR_DIR.match(p.name)):
            for block in sorted(p for p in year.iterdir() if p.is_dir() and BLOCK_DIR.match(p.name)):
                out += [f"{year.name}/{block.name}/{p.name}" for p in sorted(block.iterdir())
                        if p.is_dir() and self.versions(f"{year.name}/{block.name}/{p.name}")]
        return out

    def read(self, folder, n, name="claimset.json"):
        return json.loads((self.version_dir(folder, n) / name).read_text(encoding="utf-8"))

    def write_version(self, folder, n, files, message):
        """Write one version's documents ({name: text}) and commit them with the tag `<name>-v<n>`.
        A version that exists is never overwritten."""
        d = self.version_dir(folder, n)
        if d.exists():
            raise RegistryError(f"{folder}/v{n} exists; published versions are never rewritten")
        d.mkdir(parents=True)
        for name, text in files.items():
            (d / name).write_text(text, encoding="utf-8")
        self.git("add", "--", f"{folder}/v{n}")
        self.git("commit", "-q", "-m", message)
        self.git("tag", tag_name(folder, n))
        return d

    def notices(self, folder):
        """The claimset's notices document ({id, notices: [...]}), or None."""
        f = self.path / folder / NOTICES
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def removed_folders(self):
        """Folders of removed claimsets: a notices document and no versions."""
        out = []
        for f in sorted(self.path.glob(f"[0-9][0-9][0-9][0-9]/*/*/{NOTICES}")):
            folder = f.parent.relative_to(self.path).as_posix()
            if not self.versions(folder):
                out.append(folder)
        return out

    def write_notices(self, folder, notices, message, remove=False):
        """Write a claimset's notices document and commit it; with `remove`, the commit also deletes its versions.
        History is not rewritten: the removed files stay in earlier commits."""
        apply_notices(self.path, folder, notices, remove, self.git)
        self.git("commit", "-q", "-m", message)


def apply_notices(root, folder, notices, remove, git):
    """Stage a notices document (and, with `remove`, the deletion of every version) in a work tree."""
    d = Path(root) / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / NOTICES).write_text(dump(notices), encoding="utf-8")
    git("add", "--", f"{folder}/{NOTICES}")
    if remove:
        for v in sorted(p.name for p in d.iterdir() if p.is_dir() and VERSION_DIR.match(p.name)):
            git("rm", "-r", "-q", "--", f"{folder}/{v}")
