"""A pending submission's pages are made once (previews.py, design §4.2), and Read takes the scores written with a
paper's files (read.scores_of): both validated and scored on every visit before, seconds each."""

import json
import os
import time

from publishing import example
from test_consent import submit

from portal import consent, previews, read, scores, site


def test_kept_once_until_the_package_changes(tmp_path, monkeypatch):
    made = []

    def make():
        made.append(1)
        return {"n": len(made)}
    assert previews.kept(tmp_path, "abc", "page", make) == {"n": 1}
    assert previews.kept(tmp_path, "abc", "page", make) == {"n": 1} and made == [1]
    monkeypatch.setattr(site, "claimset_fingerprint", lambda: "a newer claimset")
    assert previews.kept(tmp_path, "abc", "page", make) == {"n": 2}
    assert previews.kept(tmp_path, None, "page", make) == {"n": 3}             # no checksum: made each time


def test_prune_removes_old_entries(tmp_path):
    previews.kept(tmp_path, "old", "page", lambda: 1)
    previews.kept(tmp_path, "new", "page", lambda: 2)
    old = tmp_path / previews.FOLDER / "old.page.json"
    past = time.time() - previews.KEEP.total_seconds() - 60
    os.utime(old, (past, past))
    previews.prune(tmp_path)
    assert not old.exists() and (tmp_path / previews.FOLDER / "new.page.json").exists()


def test_the_consent_page_validates_and_scores_once(app_client, monkeypatch):
    validated, scored = [], []
    real_v, real_s = consent.with_verifiability, scores.compute
    monkeypatch.setattr(consent, "with_verifiability", lambda d: validated.append(1) or real_v(d))
    monkeypatch.setattr(scores, "compute", lambda conn, d: scored.append(1) or real_s(conn, d))
    _, token = submit(app_client)
    for _ in range(2):
        r = app_client.get(f"/consent/{token}")
        assert r.status_code == 200 and "Preview, not published yet." in r.text
    assert validated == [1] and scored == [1]


def test_read_takes_the_scores_written_with_the_files(tmp_path, monkeypatch):
    if scores.rubric is None:
        return
    doc = example()
    doc["paper"].update(id="entrylib:2026.000042", version=2)
    stored = {"rubric": scores.version(), "paper": {"score": 77}}
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "2026.000042@v2.score.json").write_text(json.dumps(stored))
    monkeypatch.setattr(scores, "compute", lambda conn, d: (_ for _ in ()).throw(AssertionError("computed")))
    assert read.scores_of(doc, tmp_path) == stored
    (tmp_path / "p" / "2026.000042@v2.score.json").write_text(json.dumps({**stored, "rubric": "0.0"}))
    monkeypatch.setattr(scores, "compute", lambda conn, d: {"rubric": "now"})
    read._scores.cache_clear()
    assert read.scores_of(doc, tmp_path) == {"rubric": "now"}                    # by another rubric: computed
