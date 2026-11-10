"""The registry on GitHub (design §5): the portal publishes through pull requests, as the EntryLib GitHub App.

    GitHubApp            the App's REST API access to the registry repository
    RemoteRegistry       a local clone of the registry that opens, settles and merges pull requests

A version is pushed as the branch `publish/<name>-v<n>`, checked by the registry's `portal check` workflow,
squash-merged by the portal when the checks pass, and tagged `<name>-v<n>` on the merge commit (`<name>` being
the last part of the claimset's folder, `entrylib_2026.000123`). A pull request
whose checks fail is closed and its branch deleted; the identifier it carried is never given again.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .registry import RegistryError, tag_name

#: Check conclusions that let a pull request be merged.
PASSING = {"success", "neutral", "skipped"}


class GitHubError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GitHubApp:
    """The App's access to one repository: an installation token, renewed before it expires (one hour)."""

    def __init__(self, app_id, private_key, repo, api="https://api.github.com", timeout=30):
        self.app_id = str(app_id)
        self.private_key = private_key
        self.repo = repo
        self.api = api.rstrip("/")
        self.timeout = timeout
        self._token = None
        self._expires = 0.0
        self._installation = None

    # -- authentication
    def _jwt(self):
        import jwt
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.private_key,
                          algorithm="RS256")

    def token(self):
        if self._token and time.time() < self._expires - 300:
            return self._token
        if self._installation is None:
            self._installation = self._call("GET", f"/repos/{self.repo}/installation",
                                            auth=f"Bearer {self._jwt()}")["id"]
        out = self._call("POST", f"/app/installations/{self._installation}/access_tokens",
                         auth=f"Bearer {self._jwt()}")
        self._token = out["token"]
        self._expires = time.time() + 3600
        return self._token

    def git_env(self):
        """Environment for git that authenticates pushes to github.com with the installation token, without the
        token appearing in a command line or a remote URL."""
        basic = base64.b64encode(f"x-access-token:{self.token()}".encode()).decode()
        return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}

    # -- REST
    def _call(self, method, path, body=None, auth=None):
        req = urllib.request.Request(f"{self.api}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28",
                                              "Authorization": auth or f"Bearer {self.token()}",
                                              "User-Agent": "entrylib-portal"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise GitHubError(f"GitHub {method} {path}: {exc.code} {detail}", exc.code) from exc
        except OSError as exc:
            raise GitHubError(f"GitHub {method} {path}: {exc}") from exc
        return json.loads(raw) if raw else {}

    def create_pull(self, head, title, body, base="main"):
        return self._call("POST", f"/repos/{self.repo}/pulls",
                          {"title": title, "head": head, "base": base, "body": body})["number"]

    def find_pull(self, head):
        """The open pull request from branch `head`, if any (after a crash between push and opening it)."""
        owner = self.repo.split("/")[0]
        found = self._call("GET", f"/repos/{self.repo}/pulls?state=open&head={owner}:{head}")
        return found[0]["number"] if found else None

    def pull(self, number):
        p = self._call("GET", f"/repos/{self.repo}/pulls/{number}")
        return {"state": p["state"], "merged": p.get("merged", False), "head_sha": p["head"]["sha"],
                "merge_sha": p.get("merge_commit_sha"), "url": p["html_url"]}

    def checks(self, sha):
        """[{name, status, conclusion, summary}] of the check runs on a commit."""
        out = self._call("GET", f"/repos/{self.repo}/commits/{sha}/check-runs?per_page=100")
        return [{"name": c["name"], "status": c["status"], "conclusion": c.get("conclusion"),
                 "summary": ((c.get("output") or {}).get("summary") or (c.get("output") or {}).get("title") or ""),
                 "url": c.get("html_url")} for c in out.get("check_runs", [])]

    def merge(self, number, sha, title):
        """Squash-merge, only if the head is still `sha`. Returns the merge commit."""
        return self._call("PUT", f"/repos/{self.repo}/pulls/{number}/merge",
                          {"sha": sha, "merge_method": "squash", "commit_title": title, "commit_message": ""})["sha"]

    def close(self, number, comment=None):
        if comment:
            self._call("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": comment})
        self._call("PATCH", f"/repos/{self.repo}/pulls/{number}", {"state": "closed"})

    def delete_branch(self, branch):
        try:
            self._call("DELETE", f"/repos/{self.repo}/git/refs/heads/{branch}")
        except GitHubError as exc:
            if exc.status not in (404, 422):
                raise

    def tag(self, name, sha):
        try:
            self._call("POST", f"/repos/{self.repo}/git/refs", {"ref": f"refs/tags/{name}", "sha": sha})
        except GitHubError as exc:
            if exc.status != 422:                       # 422: the tag exists (a retried round)
                raise


def load_private_key(settings):
    """The App's private key, from GITHUB_APP_PRIVATE_KEY_FILE or GITHUB_APP_PRIVATE_KEY."""
    if settings.github_app_private_key_file:
        with open(settings.github_app_private_key_file, encoding="utf-8") as fh:
            return fh.read()
    return settings.github_app_private_key


@dataclass
class Opened:
    number: int
    branch: str


class RemoteRegistry:
    """A local clone of the registry whose `main` follows GitHub, and through which versions are proposed."""

    def __init__(self, registry, gh, remote="origin"):
        self.registry = registry
        self.gh = gh
        self.remote = remote

    def _git(self, *args, auth=False):
        env = self.gh.git_env() if auth else {}
        saved = dict(self.registry.env)
        self.registry.env.update(env)
        try:
            return self.registry.git(*args)
        finally:
            self.registry.env.clear()
            self.registry.env.update(saved)

    def sync(self):
        """Bring the clone's main to the remote's, with its tags."""
        self._git("fetch", "-q", "--tags", "--force", self.remote, "main")
        self._git("checkout", "-q", "-B", "main", f"{self.remote}/main")
        self._git("reset", "-q", "--hard", f"{self.remote}/main")
        self._git("clean", "-q", "-fd")

    @staticmethod
    def branch_of(prepared):
        return f"publish/{tag_name(prepared.folder, prepared.version)}"

    def open(self, prepared, body):
        """Push the prepared version as a branch from main and open its pull request. Idempotent: a branch or a
        pull request left by an interrupted round is reused."""
        self.sync()
        branch = self.branch_of(prepared)
        d = self.registry.version_dir(prepared.folder, prepared.version)
        if d.exists():
            raise RegistryError(f"{prepared.folder}/v{prepared.version} is on main already")
        self._git("checkout", "-q", "-B", branch, f"{self.remote}/main")
        try:
            d.mkdir(parents=True)
            for name, text in prepared.files.items():
                (d / name).write_text(text, encoding="utf-8")
            self._git("add", "--", f"{prepared.folder}/v{prepared.version}")
            self._git("commit", "-q", "-m", prepared.message)
            self._git("push", "-q", "--force", self.remote, f"{branch}:refs/heads/{branch}", auth=True)
        finally:
            self.sync()
        number = self.gh.find_pull(branch)
        if number is None:
            number = self.gh.create_pull(branch, prepared.message, body)
        return Opened(number, branch)

    def open_notices(self, folder, notices, remove, message, body, branch):
        """Push a claimset's notices document (and, with `remove`, the deletion of its versions) as a branch from
        main and open its pull request (notices.py). Idempotent like `open`."""
        from .registry import apply_notices
        self.sync()
        self._git("checkout", "-q", "-B", branch, f"{self.remote}/main")
        try:
            apply_notices(self.registry.path, folder, notices, remove, self._git)
            self._git("commit", "-q", "-m", message)
            self._git("push", "-q", "--force", self.remote, f"{branch}:refs/heads/{branch}", auth=True)
        finally:
            self.sync()
        number = self.gh.find_pull(branch)
        if number is None:
            number = self.gh.create_pull(branch, message, body)
        return Opened(number, branch)

    def settle(self, number, branch, title, tag=None):
        """Look at a pull request. Returns ("waiting", None), ("merged", None) or ("failed", reason). Merged pull
        requests are tagged and the clone brought up to date; failed ones are closed and their branch deleted."""
        pr = self.gh.pull(number)
        if pr["merged"]:
            if tag:
                self.gh.tag(tag, pr["merge_sha"])
            self.gh.delete_branch(branch)
            self.sync()
            return "merged", None
        if pr["state"] == "closed":
            return "failed", f"the registry pull request {pr['url']} was closed without being merged"
        runs = self.gh.checks(pr["head_sha"])
        if not runs or any(c["status"] != "completed" for c in runs):
            return "waiting", None
        failed = [c for c in runs if c["conclusion"] not in PASSING]
        if failed:
            reason = "; ".join(f"{c['name']}: {c['conclusion']}" + (f" ({c['summary'][:300]})" if c["summary"] else "")
                               for c in failed)
            self.gh.close(number, f"Not published: the registry checks failed.\n\n{reason}")
            self.gh.delete_branch(branch)
            return "failed", f"the registry checks failed ({pr['url']}): {reason}"
        sha = self.gh.merge(number, pr["head_sha"], title)
        if tag:
            self.gh.tag(tag, sha)
        self.gh.delete_branch(branch)
        self.sync()
        return "merged", None


def ensure_clone(path, repo, registry_factory):
    """A clone of github.com/<repo> at `path` (public: cloned anonymously)."""
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        import subprocess
        res = subprocess.run(["git", "clone", "-q", f"https://github.com/{repo}.git", str(path)],
                             capture_output=True, text=True, env={**os.environ})
        if res.returncode != 0:
            raise RegistryError(f"git clone {repo}: {res.stderr.strip()}")
    return registry_factory(path)
