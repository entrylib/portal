"""Fetching a submission by URL (design §4.4): https only, public addresses only, redirects checked, size capped."""

import io
import socket
import threading

import pytest

from portal import fetch


@pytest.mark.parametrize("url", ["http://example.org/p.zip", "ftp://example.org/p.zip", "file:///etc/passwd",
                                 "https://127.0.0.1/p.zip", "https://10.0.0.5/p.zip", "https://[::1]/p.zip",
                                 "https://169.254.169.254/latest/meta-data", "https://192.168.1.1/p.zip",
                                 "https://[::ffff:127.0.0.1]/p.zip", "https://user:pw@example.org/p.zip",
                                 "https:///p.zip", "https://example.org:x/p.zip", "https://e.org/" + "a" * 3000, 42])
def test_urls_refused(url):
    with pytest.raises(fetch.FetchError):
        fetch.check_url(url)


def test_urls_accepted():
    assert fetch.check_url("https://zenodo.org/records/1/files/p.zip?download=1") == (
        "zenodo.org", 443, "/records/1/files/p.zip?download=1")
    assert fetch.check_url("https://8.8.8.8:8443") == ("8.8.8.8", 8443, "/")


def test_public_address():
    assert fetch.public_address("8.8.8.8") and fetch.public_address("2606:4700::1111")
    for a in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
              "::1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "224.0.0.1"):
        assert not fetch.public_address(a), a


def test_a_connection_to_a_private_address_is_refused_before_anything_is_sent():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = []

    def accept():
        conn, _ = server.accept()
        conn.settimeout(2)
        try:
            received.append(conn.recv(10))
        except OSError:
            received.append(b"")
        conn.close()
    t = threading.Thread(target=accept)
    t.start()
    with pytest.raises(fetch.FetchError, match="not a public address"):
        fetch._public_socket(server.getsockname(), timeout=2)
    t.join(5)
    server.close()
    assert received == [b""]                                # no TLS handshake, no request


class FakeResponse(io.BytesIO):
    def __init__(self, status, body=b"", headers=None, reason="OK"):
        super().__init__(body)
        self.status, self.reason, self.headers = status, reason, headers or {}

    def getheader(self, name):
        return self.headers.get(name)


class FakeServer:
    """connection(host, port, timeout) for download: answers from a table of (host, path) -> response."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def __call__(self, host, port, timeout):
        server = self

        class Conn:
            def request(self, method, path, headers):
                server.asked.append((host, path))
                self.path = path

            def getresponse(self):
                return server.routes[(host, self.path)]()

            def close(self):
                pass
        return Conn()


def test_download_follows_redirects(tmp_path):
    srv = FakeServer({("zenodo.org", "/r/1"): lambda: FakeResponse(302, headers={"Location": "/files/p.json"}),
                      ("zenodo.org", "/files/p.json"): lambda: FakeResponse(200, b'{"a": 1}')})
    path = fetch.download("https://zenodo.org/r/1", tmp_path, connection=srv)
    assert path.read_bytes() == b'{"a": 1}' and srv.asked[-1] == ("zenodo.org", "/files/p.json")


def test_a_redirect_is_checked_again(tmp_path):
    srv = FakeServer({("e.org", "/a"): lambda: FakeResponse(301, headers={"Location": "https://10.0.0.1/x"}),
                      ("e.org", "/b"): lambda: FakeResponse(301, headers={"Location": "http://e.org/x"}),
                      ("e.org", "/loop"): lambda: FakeResponse(302, headers={"Location": "/loop"})})
    with pytest.raises(fetch.FetchError, match="public"):
        fetch.download("https://e.org/a", tmp_path, connection=srv)
    with pytest.raises(fetch.FetchError, match="https"):
        fetch.download("https://e.org/b", tmp_path, connection=srv)
    with pytest.raises(fetch.FetchError, match="redirects"):
        fetch.download("https://e.org/loop", tmp_path, connection=srv)


def test_size_status_and_empty(tmp_path):
    srv = FakeServer({("e.org", "/big"): lambda: FakeResponse(200, b"x" * 100),
                      ("e.org", "/said"): lambda: FakeResponse(200, b"x", {"Content-Length": "1000"}),
                      ("e.org", "/gone"): lambda: FakeResponse(404, reason="Not Found"),
                      ("e.org", "/empty"): lambda: FakeResponse(200, b"")})
    for path, words in (("/big", "larger"), ("/said", "larger"), ("/gone", "404"), ("/empty", "empty")):
        with pytest.raises(fetch.FetchError, match=words):
            fetch.download(f"https://e.org{path}", tmp_path, connection=srv, limit=50)
    assert list(tmp_path.iterdir()) == []                   # nothing left behind
