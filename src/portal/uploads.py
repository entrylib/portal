"""Upload addresses (design §4.4): how an agent that reaches EntryLib through MCP sends its package without the file
passing through the model. MCP carries only what the model writes; the package goes to a one-time address instead.

    issue(conn, base_url)              -> {upload_id, url, method, expires, max_bytes}: a new address
    open_for(conn, token)              -> whether the address may receive a file now
    receive(conn, token, path, size)   -> the file sent to the address, kept until it is used or expires
    copy(conn, upload_id, into)        -> a copy of what was sent, for a tool to check or submit
    consume(conn, upload_id)           -> forget an upload once it is submitted
    expire(conn)                       -> delete uploads past their window

The upload_id is the address's secret: whoever holds it can use what was sent there, as with a consent link. Only
its hash is stored.
"""

import datetime as dt
import secrets
import shutil
import tempfile
from pathlib import Path

from .submissions import MAX_UPLOAD_BYTES, token_hash

#: How long an upload address and what is sent to it are kept.
UPLOAD_WINDOW = dt.timedelta(hours=2)


class UploadError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _dir(submissions_dir):
    return Path(submissions_dir) / "uploads"


def issue(conn, base_url, client_ip=None, now=None):
    """A new single-use upload address."""
    now = now or dt.datetime.now(dt.UTC)
    token = "up_" + secrets.token_urlsafe(24)
    expires = now + UPLOAD_WINDOW
    conn.execute("INSERT INTO uploads (token_hash, created, expires, client_ip) VALUES (%s, %s, %s, %s)",
                 (token_hash(token), now, expires, client_ip))
    url = f"{base_url}/api/uploads/{token}"
    return {"upload_id": token, "url": url, "method": "PUT", "expires": expires.isoformat(),
            "max_bytes": MAX_UPLOAD_BYTES,
            "how": f"curl --fail -T <paper>.zip {url}  (the zip `claimset package` builds, or a claimset file); "
                   f"then call validate, score or submit with upload_id"}


def open_for(conn, token, now=None):
    """Whether the address exists, has not expired and has received nothing yet."""
    now = now or dt.datetime.now(dt.UTC)
    return conn.execute("SELECT 1 FROM uploads WHERE token_hash = %s AND expires > %s AND received IS NULL",
                        (token_hash(token or ""), now)).fetchone() is not None


def receive(conn, token, path, size, submissions_dir, now=None):
    """Keep the file sent to an address (moved from `path`). Raises UploadError if the address cannot take it."""
    now = now or dt.datetime.now(dt.UTC)
    h = token_hash(token or "")
    name = f"{h[:40]}.bin"
    with conn.transaction():
        row = conn.execute("UPDATE uploads SET received = %s, size = %s, file_name = %s WHERE token_hash = %s"
                           " AND expires > %s AND received IS NULL RETURNING expires",
                           (now, size, name, h, now)).fetchone()
        if row is None:
            raise UploadError("no such upload address, or it has expired or already received a file: ask for a new "
                              "one with the MCP tool upload_url", status=404)
        target = _dir(submissions_dir) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), target)
    return {"upload_id": token, "received": True, "size": size, "expires": row[0].isoformat(),
            "next": "call validate, score or submit with this upload_id"}


def copy(conn, upload_id, submissions_dir, into, now=None):
    """A copy, in the directory `into`, of what was sent to the address. Raises UploadError."""
    now = now or dt.datetime.now(dt.UTC)
    row = conn.execute("SELECT file_name, received FROM uploads WHERE token_hash = %s AND expires > %s",
                       (token_hash(upload_id or ""), now)).fetchone()
    if row is None:
        raise UploadError("no such upload, or it has expired: ask for a new address with upload_url", status=404)
    if row[1] is None:
        raise UploadError("nothing has been sent to this upload address yet: send the file to its url first (PUT)")
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    fh = tempfile.NamedTemporaryFile(dir=into, prefix="upload-", delete=False)
    fh.close()
    shutil.copyfile(_dir(submissions_dir) / row[0], fh.name)
    return Path(fh.name)


def consume(conn, upload_id, submissions_dir):
    """Forget an upload once it is submitted: the submission keeps its own copy."""
    row = conn.execute("DELETE FROM uploads WHERE token_hash = %s RETURNING file_name",
                       (token_hash(upload_id or ""),)).fetchone()
    if row and row[0]:
        (_dir(submissions_dir) / row[0]).unlink(missing_ok=True)


def expire(conn, submissions_dir, now=None):
    """Delete uploads past their window, and their files."""
    now = now or dt.datetime.now(dt.UTC)
    for (name,) in conn.execute("DELETE FROM uploads WHERE expires <= %s RETURNING file_name", (now,)).fetchall():
        if name:
            (_dir(submissions_dir) / name).unlink(missing_ok=True)
