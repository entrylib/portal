"""Packaged files, kept with the claimset they belong to (claimset spec §2.5; design §7.1).

    put(path, key, version, rel) -> (sha256 hex digest, permanent URL)

A file of version n of a claimset is stored at `<published>/p/<key>/v<n>/files/<rel>`, under the path the package gave
it (`figures/calibration.png`), and published at `https://entrylib.org/p/<key>/v<n>/files/<rel>`: the claimset's
pages use it from there, and removing the claimset removes its files with it. A file a version keeps unchanged from
the version before is a hard link to it, not a second copy. The artefact's `version` keeps its checksum.

Before November 2026 files were stored by checksum, `<published>/files/<sha256>`; those addresses still answer, with a
redirect to where the file now is (indexer.move_legacy_files, app: /files/<sha256>).
"""

import hashlib
import os
import shutil
import urllib.parse
from pathlib import Path, PurePosixPath


class StorageError(ValueError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(rel):
    """The package path of a file as a safe relative path (figures/a.png), or StorageError."""
    if not isinstance(rel, str):
        raise StorageError("a file's path must be text")
    p = PurePosixPath(rel.replace("\\", "/").strip())
    if p.is_absolute() or not p.parts or any(part in ("", ".", "..") for part in p.parts) or len(str(p)) > 300:
        raise StorageError(f"not a path inside the package: {rel!r}")
    return p


class FileStore:
    def __init__(self, root, base_url):
        self.root = Path(root)
        self.base_url = base_url.rstrip("/")

    def path(self, key, version, rel):
        return self.root / "p" / key / f"v{version}" / "files" / Path(*safe_relative(rel).parts)

    def url(self, key, version, rel):
        return f"{self.base_url}/p/{key}/v{version}/files/{urllib.parse.quote(str(safe_relative(rel)))}"

    def put(self, path, key, version, rel):
        """Store a file of version `version` of the claimset `key`; returns (sha256 hex digest, permanent URL)."""
        digest = sha256_file(path)
        dest = self.path(key, version, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        before = self.path(key, version - 1, rel) if version > 1 else None
        tmp = dest.with_name(dest.name + ".tmp")
        if before is not None and before.exists() and sha256_file(before) == digest:
            tmp.unlink(missing_ok=True)
            os.link(before, tmp)                            # unchanged since the version before: one copy on disk
        else:
            shutil.copyfile(path, tmp)
        os.replace(tmp, dest)
        return digest, self.url(key, version, rel)
