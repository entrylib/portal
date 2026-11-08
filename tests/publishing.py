"""Helpers for tests that publish claimsets: the example files, a fake classifier and the base URL. The `env`
fixture (conftest.py) gives a database, a registry and a published directory."""

import datetime as dt
import json

from portal.classify import Classification

BASE = "https://entrylib.test"
TODAY = dt.date(2026, 11, 4)


def example(name="submission-native.json"):
    from importlib import resources
    return json.loads((resources.files("claimset") / "data" / "examples" / name).read_text(encoding="utf-8"))


def fake_classifier(doc):
    return Classification("openalex:subfields/1803", ("openalex:T10001", "openalex:T10002"), "fake-classifier@1")


def write(tmp_path, doc, name="paper.claimset.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p
