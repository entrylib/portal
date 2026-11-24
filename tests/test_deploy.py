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


def test_an_update_rebuilds_the_portal_without_its_dependencies():
    """The dependencies are installed from a file that holds only them (read from pyproject.toml in a stage of its
    own), before the code is copied: a change to the code or to the version number reuses that layer."""
    lines = (ROOT / "Dockerfile").read_text().splitlines()
    deps = next(i for i, x in enumerate(lines) if x.startswith("RUN pip install -r /tmp/requirements.txt"))
    code = next(i for i, x in enumerate(lines) if x.startswith("COPY src "))
    assert deps < code
    assert "RUN pip install --no-deps ." in lines[code + 1:]
    assert "FROM python:3.12-slim AS deps" in lines


def test_an_update_removes_the_images_it_replaces():
    launch_sh = (ROOT / "deploy" / "launch.sh").read_text()
    assert launch_sh.index("docker image prune -f") > launch_sh.index("docker compose up -d --build")
    assert "builder prune" not in launch_sh and "system prune" not in launch_sh     # the build cache is kept
