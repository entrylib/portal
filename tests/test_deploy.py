"""The server scripts (docs/deploy.md): launch.sh refuses to start until the settings only a person can give are in
.env, and the pieces agree on where things are."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL = {"PORTAL_DOMAIN": "entrylib.org", "POSTGRES_PASSWORD": "a" * 64, "OPENALEX_API_KEY": "k",
        "ORCID_CLIENT_ID": "APP-X", "ORCID_CLIENT_SECRET": "s", "PORTAL_REGISTRY_MODE": "github", "GITHUB_APP_ID": "1"}


def launch(tmp_path, env):
    (tmp_path / "deploy").mkdir(exist_ok=True)
    shutil.copy(ROOT / "deploy" / "launch.sh", tmp_path / "deploy" / "launch.sh")
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    return subprocess.run(["bash", str(tmp_path / "deploy" / "launch.sh")], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"})


def test_launch_refuses_missing_settings(tmp_path):
    out = launch(tmp_path, {**FULL, "ORCID_CLIENT_SECRET": "", "GITHUB_APP_ID": "",
                            "GITHUB_APP_PRIVATE_KEY_PATH": str(tmp_path / "nope.pem")})
    assert out.returncode == 1
    assert "ORCID_CLIENT_SECRET" in out.stderr and "GITHUB_APP_ID" in out.stderr and "GitHub App key" in out.stderr
    assert "PORTAL_DOMAIN" not in out.stderr


def test_launch_refuses_the_example_password(tmp_path):
    key = tmp_path / "github-app.pem"
    key.write_text("-----BEGIN RSA PRIVATE KEY-----\n")
    key.chmod(0o600)
    out = launch(tmp_path, {**FULL, "POSTGRES_PASSWORD": "change-me", "GITHUB_APP_PRIVATE_KEY_PATH": str(key)})
    assert out.returncode == 1 and "example value" in out.stderr and "GitHub App key" not in out.stderr
    assert key.stat().st_mode & 0o777 == 0o644          # readable by the app's user in its container


def test_the_pieces_agree():
    setup = (ROOT / "deploy" / "server-setup.sh").read_text()
    init = (ROOT / "deploy" / "cloud-init.yaml").read_text()
    assert init.startswith("#cloud-config\n")
    assert "git clone -q https://github.com/entrylib/portal /opt/entrylib/portal" in init
    assert "bash /opt/entrylib/portal/deploy/server-setup.sh" in init and 'PORTAL="$ROOT/portal"' in setup
    compose = (ROOT / "compose.yaml").read_text()
    for name in ("POSTGRES_PASSWORD", "OPENALEX_API_KEY", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "GITHUB_APP_ID",
                 "GITHUB_APP_PRIVATE_KEY_PATH", "PORTAL_DOMAIN", "PORTAL_REGISTRY_MODE", "ORCID_BASE"):
        assert f"{name}=" in setup and name in compose, name


def test_start_updates_the_rubric_from_pypi():
    # a release has a new version number, so --upgrade installs it, as for claimset
    line = next(x for x in (ROOT / "deploy" / "start.sh").read_text().splitlines()
                if "pip install" in x and "entrylib-rubric" in x)
    assert "--upgrade" in line and "git+" not in line
