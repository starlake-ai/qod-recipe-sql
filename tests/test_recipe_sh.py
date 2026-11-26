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
    assert "./run.sh stop" in r.stderr
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
        """).replace(f"exec sleep 300 {marker}", f"exec -a \"qod serve $2 --name $4 {marker}\" sleep 300"))
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


def test_extra_preflight_runs_after_shared_checks(repo, tmp_path):
    """A recipe-specific check (recipe_extra_preflight in run.sh) runs after the
    shared checks pass, and its refusal leaves out/ alone."""
    run_sh = repo / "run.sh"
    run_sh.write_text(run_sh.read_text().replace(
        "source lib/recipe.sh",
        'recipe_extra_preflight() { die 2 "extra check refused"; }\nsource lib/recipe.sh'))
    (repo / "out").mkdir()
    (repo / "out" / "keep").write_text("x")
    r = _run(repo, qod_cmd=_stub(tmp_path, "99.0.0"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "extra check refused" in r.stderr
    assert (repo / "out" / "keep").exists()


def _sleeper(argv0):
    return subprocess.Popen(["bash", "-c", f'exec -a "{argv0}" sleep 60'])


def test_stop_ignores_other_qod_gateway(repo, tmp_path):
    """A reused pid that belongs to someone else's qod gateway is not ours."""
    other = _sleeper("uv tool uvx qod@latest serve ./sales.duckdb --name other")
    try:
        (repo / "out").mkdir()
        (repo / "out" / "qod.pid").write_text(f"{other.pid}\n")
        r = _run(repo, "stop", qod_cmd=_stub(tmp_path, "99.0.0"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert other.poll() is None, "another gateway was signalled"
        assert "stale" in (r.stdout + r.stderr)
    finally:
        other.kill()


def test_serve_drops_readers_qod_env(repo, tmp_path):
    """The gateway must not inherit the reader's QOD_* / PROXY_* settings."""
    seen = tmp_path / "env.txt"
    stub = tmp_path / "qod-stub"
    stub.write_text(f"#!/usr/bin/env bash\nenv > {seen}\nexit 3\n")
    stub.chmod(0o755)
    script = ("set -euo pipefail; source lib/recipe.sh; RECIPE_TOOL=t; SERVE_TARGET=out/x.duckdb; "
              "uv() { return 1; }; mkdir -p out; recipe_serve")
    env = dict(os.environ, QOD_CMD=str(stub), QOD_DUCKLAKE_DATA_PATH="/elsewhere",
               PROXY_PORT="1", QOD_ADMIN_USERNAME="root")
    r = subprocess.run(["bash", "-c", script], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    got = seen.read_text()
    for leaked in ("QOD_DUCKLAKE_DATA_PATH=", "PROXY_PORT=", "QOD_ADMIN_USERNAME="):
        assert leaked not in got, leaked
    assert f"QOD_DATA_DIR={repo}/out/.qod" in got
    assert "PROXY_HOST=127.0.0.1" in got


def test_interrupt_during_start_stops_gateway(repo, tmp_path):
    """Ctrl-C while waiting for the gateway stops it instead of orphaning it."""
    marker = f"intr-{tmp_path.name}"
    stub = tmp_path / "qod-stub"
    stub.write_text(f'#!/usr/bin/env bash\nexec -a "qod serve $2 --name $4 {marker}" sleep 300\n')
    stub.chmod(0o755)
    script = ("set -euo pipefail; source lib/recipe.sh; RECIPE_TOOL=t; SERVE_TARGET=out/x.duckdb; "
              "READY_TIMEOUT_S=60; uv() { return 1; }; mkdir -p out; recipe_serve")
    # Own session, like a terminal job: Ctrl-C reaches the whole foreground group.
    p = subprocess.Popen(["bash", "-c", script], cwd=repo, env=dict(os.environ, QOD_CMD=str(stub)),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    import signal
    import time
    for _ in range(50):
        if subprocess.run(["pgrep", "-f", marker], capture_output=True).returncode == 0:
            break
        time.sleep(0.1)
    started = time.monotonic()
    os.killpg(p.pid, signal.SIGINT)
    p.wait(timeout=60)
    assert time.monotonic() - started < 20, "Ctrl-C was not acted on promptly"
    time.sleep(0.5)
    alive = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.strip()
    if alive:
        subprocess.run(["pkill", "-f", marker])
    assert alive == "", "gateway left running after Ctrl-C"
    assert p.returncode != 0


def test_failed_check_prints_stop_hint(repo):
    """When the query check fails the gateway is still up: say how to stop it."""
    script = ("set -euo pipefail; source lib/recipe.sh; RECIPE_TOOL=t; RECIPE_LABEL=t; SERVE_TARGET=x; "
              "recipe_stop() { :; }; recipe_preflight() { :; }; build_pipeline() { :; }; "
              "recipe_serve() { :; }; uv() { [ \"$*\" != \"--quiet query.py --check\" ] && [ \"$*\" != \"run --quiet query.py --check\" ]; }; "
              "recipe_main")
    r = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "./run.sh stop" in (r.stdout + r.stderr)


def test_readme_states_min_version():
    lib = (ROOT / "lib" / "recipe.sh").read_text()
    version = lib.split('QOD_MIN_VERSION="', 1)[1].split('"', 1)[0]
    assert f"qod {version} or later" in (ROOT / "README.md").read_text()


def test_slow_start_reports_progress(repo, tmp_path):
    """A first run downloads QoD (hundreds of MB): the wait must say so instead
    of sitting silent, and its default must leave room for a slow link."""
    marker = f"slow-{tmp_path.name}"
    stub = tmp_path / "qod-stub"
    stub.write_text(f'#!/usr/bin/env bash\nexec -a "qod serve $2 --name $4 {marker}" sleep 300\n')
    stub.chmod(0o755)
    script = ("set -euo pipefail; source lib/recipe.sh; RECIPE_TOOL=t; SERVE_TARGET=out/x.duckdb; "
              'echo "default timeout $READY_TIMEOUT_S"; '
              "READY_TIMEOUT_S=4; PROGRESS_EVERY_S=2; uv() { return 1; }; mkdir -p out; recipe_serve")
    r = subprocess.run(["bash", "-c", script], cwd=repo, env=dict(os.environ, QOD_CMD=str(stub)),
                       capture_output=True, text=True, timeout=60)
    subprocess.run(["pkill", "-f", marker])
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "still starting" in out
    default = int(out.split("default timeout ", 1)[1].split()[0])
    assert default >= 1800


def test_stop_reports_a_gateway_that_survives(repo, tmp_path):
    """If the gateway ignores INT and TERM, stop must say so and keep the pid
    file, not print "stopped"."""
    tool = (repo / "run.sh").read_text().split("RECIPE_TOOL=", 1)[1].split()[0]
    stubborn = subprocess.Popen(
        ["bash", "-c", f"trap '' INT TERM; exec -a 'qod serve x --name recipe_{tool}' sleep 120"],
        start_new_session=True)
    try:
        (repo / "out").mkdir()
        (repo / "out" / "qod.pid").write_text(f"{stubborn.pid}\n")
        env = dict(os.environ, QOD_CMD=_stub(tmp_path, "99.0.0"), STOP_TIMEOUT_S="2")
        r = subprocess.run(["bash", "run.sh", "stop"], cwd=repo, env=env,
                           capture_output=True, text=True, timeout=60)
        out = r.stdout + r.stderr
        assert r.returncode != 0, out
        assert "still running" in out
        assert "stopped\n" not in r.stdout
        assert (repo / "out" / "qod.pid").exists()
    finally:
        stubborn.kill()


def test_refuses_when_node_port_busy(repo, tmp_path):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", 21900))
        except OSError:
            pytest.skip("port 21900 already in use on this machine")
        s.listen()
        r = _run(repo, qod_cmd=_stub(tmp_path, "99.0.0"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "21900" in r.stderr


def test_connect_hint_uses_loopback_address(repo):
    script = "source lib/recipe.sh; RECIPE_TOOL=t; recipe_connect_hint"
    out = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True).stdout
    assert "127.0.0.1:31338" in out and "quack:127.0.0.1:9494" in out
    assert "localhost" not in out
