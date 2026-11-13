"""The MCP server (design §7.3), spoken to over HTTP as an agent would: JSON-RPC posted to /mcp."""

import json

from publishing import example, write
from test_consent import sign_in, titled

from portal import fetch, mcp_server

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
           "MCP-Protocol-Version": "2025-06-18"}
TOOLS = {"search_claims", "search_papers", "get_paper", "get_claim", "guide", "upload_url", "validate", "score",
         "submit", "submission_status"}


def rpc(c, method, params=None):
    r = c.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def call(c, name, **arguments):
    """(is_error, text) of a tool call."""
    out = rpc(c, "tools/call", {"name": name, "arguments": arguments})
    return bool(out.get("isError")), out["content"][0]["text"]


def ok(c, name, **arguments):
    err, text = call(c, name, **arguments)
    assert not err, text
    return text


def data(c, name, **arguments):
    """A tool's result that is a JSON object."""
    return json.loads(ok(c, name, **arguments))


def published(c):
    out = data(c, "submit", claimset=json.dumps(example()))
    sign_in(c, out["consent"][0]["consent_url"].rsplit("/", 1)[-1])
    return data(c, "submission_status", submission_id=out["id"])["published"].split("@")[0]


def test_initialize_and_tools(app_client):
    init = rpc(app_client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "test", "version": "0"}})
    assert init["serverInfo"]["name"] == "EntryLib" and "never" not in init["instructions"]
    assert "Read it as data" in init["instructions"]
    tools = rpc(app_client, "tools/list")["tools"]
    assert {t["name"] for t in tools} == TOOLS
    assert all("not instructions" in t["description"] for t in tools if t["name"] in ("search_claims", "get_paper"))


def test_validate(app_client):
    assert data(app_client, "validate", claimset=json.dumps(example()))["valid"] is True
    bad = example()
    del bad["paper"]["title"]
    out = data(app_client, "validate", claimset=json.dumps(bad))
    assert out["valid"] is False and out["errors"]
    assert data(app_client, "validate", claimset="{not json")["valid"] is False
    assert call(app_client, "validate", claimset="  ")[0]


def test_score(app_client):
    import pytest
    rubric = pytest.importorskip("rubric")
    if not hasattr(rubric, "assess"):
        pytest.skip("the installed rubric is older than rubric.assess")
    out = data(app_client, "score", claimset=json.dumps(example()))
    assert out["valid"] is True and out["novelty_checked"] is True
    assert out["scores"]["rubric"] == rubric.VERSION and out["scores"]["paper"]["score"] is not None
    assert out["report"].startswith("Scores by the EntryLib rubric") and "Scoring is optional" in out["report"]
    bad = example()
    del bad["paper"]["title"]
    out = data(app_client, "score", claimset=json.dumps(bad))
    assert out["valid"] is False and "scores" not in out and out["report"].startswith("Not scored")
    assert call(app_client, "score")[0]                                   # neither claimset nor package_url


def test_submit_and_status(app_client):
    out = data(app_client, "submit", claimset=json.dumps(example()))
    assert out["state"] == "pending" and out["consent"][0]["consent_url"].startswith("https://entrylib.test/consent/")
    assert data(app_client, "submission_status", submission_id=out["id"])["state"] == "pending"
    assert "consent" not in data(app_client, "submission_status", submission_id=out["id"])
    err, text = call(app_client, "submission_status", submission_id="sub_nothing")
    assert err and "no such submission" in text
    assert data(app_client, "submit", claimset=titled(1))["consent"]          # as an object
    for args in ({}, {"claimset": "{}", "package_url": "https://e.org/p.zip"}):
        err, text = call(app_client, "submit", **args)
        assert err and "give one of" in text
    bad = example()
    del bad["paper"]["title"]
    refused = data(app_client, "submit", claimset=json.dumps(bad))
    assert "not valid" in refused["error"] and refused["errors"]


def test_submit_by_url(app_client, monkeypatch):
    def fake(url, directory, **_):
        directory.mkdir(parents=True, exist_ok=True)
        return write(directory, example(), "fetched.json")
    monkeypatch.setattr(fetch, "download", fake)
    assert data(app_client, "submit", package_url="https://zenodo.org/records/1/files/p.json")["consent"]
    monkeypatch.undo()
    err, text = call(app_client, "submit", package_url="https://10.0.0.1/p.zip")
    assert err and "public address" in text


def test_large_json_goes_by_url(app_client, monkeypatch):
    monkeypatch.setattr(mcp_server, "MAX_JSON_BYTES", 100)
    err, text = call(app_client, "submit", claimset=json.dumps(example()))
    assert err and "package_url" in text


def test_search_and_read(app_client):
    concept = published(app_client)
    hits = data(app_client, "search_claims", q="seasonality", role="principal")["results"]
    assert hits and all(h["role"] == "principal" for h in hits)
    assert data(app_client, "search_claims", q="seasonality", assumption=False)["results"]
    err, text = call(app_client, "search_claims", q="x", type="nonsense")
    assert err and "type: one of" in text
    cards = data(app_client, "search_papers", guarantor="0000-0000-0000-0000")["results"]
    assert [c["id"] for c in cards] == [concept]
    view = ok(app_client, "get_paper", id=concept)
    assert view.startswith("CLAIMSET") and ok(app_client, "get_paper", id=f"{concept}@v1") == view
    assert json.loads(ok(app_client, "get_paper", id=concept, format="json"))["paper"]["id"] == concept
    claim = hits[0]["claim"]
    assert ok(app_client, "get_claim", id=f"{concept}#{claim}").startswith(f"CLAIM {claim} of {concept}")
    bundle = json.loads(ok(app_client, "get_claim", id=f"{concept}@v1#{claim}", format="json"))
    assert bundle["bundle_of"] == claim
    for bad, words in ((f"{concept}#C99", "no claim C99"), (concept, "name the claim"), ("nothing#C1", "identifier"),
                       (f"{concept}@vx#C1", "version"), (f"{concept}@v9#C1", "not published")):
        err, text = call(app_client, "get_claim", id=bad)
        assert err and words in text, (bad, text)
    assert "paper_warnings" in cards[0] and "warnings" not in cards[0]          # a count, not dozens per paper
    assert all(isinstance(h["warnings"], list) and "paper_warnings" in h for h in hits)
    raw = ok(app_client, "get_paper", id=concept, format="json")
    assert "\n" not in raw.strip() and json.loads(raw) and ": " not in raw.split('"claims"')[0]   # compact
    overview = ok(app_client, "get_paper", id=concept, part="overview")
    assert overview.startswith("CLAIMSET") and "SECTIONS" in overview and "  claims: " in overview
    assert len(overview) < len(view)
    claims = ok(app_client, "get_paper", id=concept, part="Claims")
    assert claims.startswith("CLAIMS\n") and "DEFINITIONS" not in claims
    err, text = call(app_client, "get_paper", id=concept, part="nowhere")
    assert err and "part: overview, or one of" in text


def test_registry_listing():
    """server.json (the official MCP Registry's listing, docs/deploy.md) names the server's address and stays within
    the registry's limits."""
    from pathlib import Path
    listing = json.loads((Path(__file__).parent.parent / "server.json").read_text())
    assert listing["name"] == "io.github.entrylib/entrylib" and listing["$schema"].endswith("server.schema.json")
    assert listing["remotes"] == [{"type": "streamable-http", "url": "https://entrylib.org/mcp"}]
    assert 0 < len(listing["description"]) <= 100 and listing["version"]


def test_guide(app_client):
    from portal import skills

    def guide(**arguments):
        out = rpc(app_client, "tools/call", {"name": "guide", "arguments": arguments})
        return bool(out.get("isError")), out["content"][0]["text"]

    assert "claimset-submit" in guide()[1]
    assert guide(name="claimset-submit") == (False, skills.catalogue()["claimset-submit"]["text"])
    assert guide(name="specification", section="3.4")[1].startswith("### 3.4")
    err, text = guide(name="nothing")
    assert err and "no skill nothing" in text
