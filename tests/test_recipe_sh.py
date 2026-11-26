"""Drive run.sh / lib/recipe.sh in a temporary copy of the repo, with a stub
QOD_CMD so no real gateway is started."""

import os
import shutil
import socket
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("out", ".venv", ".git", "__pycache__"))
    return dst


def _stub(tmp_path, version):
    stub = tmp_path / "qod-stub"
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [ "$1" = "--version" ]; then echo "qod {version}"; exit 0; fi
        echo "stub must not serve" >&2; exit 99
        """))
    stub.chmod(0o755)
    return str(stub)


def _run(repo, *args, qod_cmd):
    env = dict(os.environ, QOD_CMD=qod_cmd)
    return subprocess.run(["bash", "run.sh", *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=120)


def test_refuses_when_port_busy(repo, tmp_path):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", 31338))
        except OSError:
            pytest.skip("port 31338 already in use on this machine")
        s.listen()
        r = _run(repo, qod_cmd=_stub(tmp_path, "99.0.0"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "31338" in r.stderr
    assert not (repo / "out").exists()


def test_refuses_old_qod(repo, tmp_path):
    r = _run(repo, qod_cmd=_stub(tmp_path, "0.0.1"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "uvx qod@latest" in r.stderr
    assert not (repo / "out").exists()


def test_stop_ignores_foreign_pid(repo, tmp_path):
    sleeper = subprocess.Popen(["sleep", "60"])
    try:
        (repo / "out").mkdir()
        (repo / "out" / "qod.pid").write_text(f"{sleeper.pid}\n")
        r = _run(repo, "stop", qod_cmd=_stub(tmp_path, "99.0.0"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert sleeper.poll() is None, "an unrelated process was signalled"
        assert not (repo / "out" / "qod.pid").exists()
        assert "stale" in (r.stdout + r.stderr)
    finally:
        sleeper.kill()


def test_stop_without_gateway(repo, tmp_path):
    r = _run(repo, "stop", qod_cmd=_stub(tmp_path, "99.0.0"))
    assert r.returncode == 0, r.stdout + r.stderr


def test_failed_start_stops_the_gateway(repo, tmp_path):
    """recipe_serve must record the gateway's own pid (not a wrapper subshell),
    so that a start that never becomes ready is stopped, not orphaned."""
    marker = f"marker-{tmp_path.name}"
    stub = tmp_path / "qod-stub"
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [ "$1" = "--version" ]; then echo "qod 99.0.0"; exit 0; fi
        exec sleep 300 {marker}
        """).replace(f"exec sleep 300 {marker}", f"exec -a 'qod serve {marker}' sleep 300"))
    stub.chmod(0o755)
    script = (
        "set -euo pipefail; source lib/recipe.sh; "
        "RECIPE_TOOL=t; SERVE_TARGET=out/x.duckdb; READY_TIMEOUT_S=2; "
        "uv() { return 1; }; mkdir -p out; recipe_serve"
    )
    r = subprocess.run(["bash", "-c", script], cwd=repo, env=dict(os.environ, QOD_CMD=str(stub)),
                       capture_output=True, text=True, timeout=120)
    alive = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.strip()
    if alive:
        subprocess.run(["pkill", "-f", marker])
    assert r.returncode == 1, r.stdout + r.stderr
    assert alive == "", f"gateway left running after a failed start: {alive}"
