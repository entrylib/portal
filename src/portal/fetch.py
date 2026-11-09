"""Fetching a submission by URL (design §4.4): an https URL of a package or a claimset file, from a public address.

    download(url, directory) -> Path of the fetched file, or FetchError saying why not

Only https; at most MAX_REDIRECTS redirects, each checked as the first URL; at most submissions.MAX_UPLOAD_BYTES; at
most DEADLINE_SECONDS in all. The address is checked on the socket actually connected (not on a separate DNS lookup),
so a name that resolves to a private address, at once or after a check, is refused (SSRF, DNS rebinding).
"""

import http.client
import ipaddress
import socket
import ssl
import tempfile
import time
import urllib.parse
from pathlib import Path

from . import submissions

MAX_REDIRECTS = 5
DEADLINE_SECONDS = 120
CONNECT_TIMEOUT = 15
MAX_URL = 2048
USER_AGENT = "EntryLib-portal (+https://entrylib.org/llms.txt)"


class FetchError(Exception):
    """The URL cannot be fetched: says why, in words for the submitter."""


def public_address(address):
    """Whether an IP address is on the public internet (not loopback, private, link-local, reserved, ...)."""
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _public_socket(address, *args, **kwargs):
    """socket.create_connection, refusing a connection to a non-public address before anything is sent on it."""
    sock = socket.create_connection(address, *args, **kwargs)
    if not public_address(sock.getpeername()[0]):
        sock.close()
        raise FetchError(f"{address[0]} is not a public address")
    return sock


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection that refuses to talk to a non-public address: checked after the TCP connection is made
    and before the TLS handshake."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _public_socket


def check_url(url):
    """The parts of an acceptable URL: (host, port, path with query). Raises FetchError."""
    if not isinstance(url, str) or len(url) > MAX_URL:
        raise FetchError(f"the URL must be text of at most {MAX_URL} characters")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme != "https":
        raise FetchError("only https URLs are fetched")
    if not parts.hostname or parts.username or parts.password:
        raise FetchError("the URL needs a host and no user name or password")
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        literal = None
    if literal is not None and not public_address(literal):
        raise FetchError(f"{parts.hostname} is not a public address")
    try:
        port = parts.port or 443
    except ValueError:
        raise FetchError("the URL's port is not a number") from None
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return parts.hostname, port, path


def _connection(host, port, timeout):
    return _PublicHTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())


def download(url, directory, *, connection=_connection, limit=None):
    """Fetch `url` into a new file in `directory`. `connection(host, port, timeout)` makes the connection (tests
    replace it). Raises FetchError."""
    limit = limit or submissions.MAX_UPLOAD_BYTES
    deadline = time.monotonic() + DEADLINE_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        host, port, path = check_url(url)
        conn = connection(host, port, CONNECT_TIMEOUT)
        try:
            try:
                conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                resp = conn.getresponse()
            except FetchError:
                raise
            except (OSError, http.client.HTTPException) as exc:
                raise FetchError(f"cannot fetch {host}: {type(exc).__name__}: {exc}") from None
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise FetchError(f"{host} answered with a redirect and no location")
                url = urllib.parse.urljoin(url, location)
                continue
            if resp.status != 200:
                raise FetchError(f"{host} answered {resp.status} {resp.reason}")
            length = resp.getheader("Content-Length")
            if length and length.isdigit() and int(length) > limit:
                raise FetchError(f"the file is larger than {limit} bytes")
            return _save(resp, directory, limit, deadline)
        finally:
            conn.close()
    raise FetchError(f"more than {MAX_REDIRECTS} redirects")


def _save(resp, directory, limit, deadline):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fh = tempfile.NamedTemporaryFile(dir=directory, prefix="fetched-", delete=False)
    size = 0
    try:
        while True:
            if time.monotonic() > deadline:
                raise FetchError(f"the download took longer than {DEADLINE_SECONDS} seconds")
            try:
                chunk = resp.read(1 << 16)
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                raise FetchError(f"the download failed: {type(exc).__name__}") from None
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise FetchError(f"the file is larger than {limit} bytes")
            fh.write(chunk)
    except BaseException:
        fh.close()
        Path(fh.name).unlink(missing_ok=True)
        raise
    fh.close()
    if size == 0:
        Path(fh.name).unlink(missing_ok=True)
        raise FetchError("the file is empty")
    return Path(fh.name)
