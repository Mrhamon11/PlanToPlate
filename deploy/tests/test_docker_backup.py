"""``deploy/docker-backup.sh`` - the host-side off-box sync for the Docker Compose path.

``docker`` is replaced by a stub on ``PATH`` so the script's own logic is what runs: the stub
records nothing about a real container, it only makes ``compose cp`` produce backup tiers (or
fail on request).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPT = BASE_DIR / "deploy" / "docker-backup.sh"
BASH = shutil.which("bash") or "bash"

STUB_DOCKER = """#!/bin/sh
case " $* " in
  *" exec "*) exit 0 ;;
  *" cp "*)
    [ -n "$STUB_CP_FAIL" ] && exit 1
    for last; do :; done
    mkdir -p "$last/hourly"
    echo backup > "$last/hourly/plantoplate-1.sqlite3.gz"
    exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def run(tmp_path):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "docker"
    stub.write_text(STUB_DOCKER)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "work"
    workdir.mkdir()

    def _run(**extra_env: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
            "STAGING_DIR": str(tmp_path / "staging"),
            "LOCK_FILE": str(tmp_path / "lock"),
            "RSYNC_TARGET": "",
            "RCLONE_REMOTE": "",
            **extra_env,
        }
        return subprocess.run(
            [BASH, str(SCRIPT)],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    _run.workdir = workdir
    _run.tmp_path = tmp_path
    return _run


def test_without_a_target_it_says_nothing_left_the_machine(run):
    result = run()

    assert result.returncode == 0, result.stderr
    assert "backups exist only on this machine" in result.stdout
    assert not (run.tmp_path / "staging").exists()


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_backups_reach_the_target_and_the_staging_copy_is_private(run):
    destination = run.tmp_path / "offbox"
    destination.mkdir()

    result = run(RSYNC_TARGET=f"{destination}/")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "hourly" / "plantoplate-1.sqlite3.gz").is_file()
    assert stat.S_IMODE((run.tmp_path / "staging").stat().st_mode) == 0o700


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_target_is_read_from_dot_env(run):
    destination = run.tmp_path / "from-env"
    destination.mkdir()
    (run.workdir / ".env").write_text(f'RSYNC_TARGET="{destination}/"\n')

    result = run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "hourly" / "plantoplate-1.sqlite3.gz").is_file()


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_failed_copy_out_of_the_container_never_reaches_the_sync(run):
    """With ``--delete`` a half-copied staging directory would erase good off-box backups."""
    destination = run.tmp_path / "offbox"
    (destination / "hourly").mkdir(parents=True)
    keep = destination / "hourly" / "precious.sqlite3.gz"
    keep.write_text("existing off-box backup")

    result = run(RSYNC_TARGET=f"{destination}/", STUB_CP_FAIL="1")

    assert result.returncode != 0
    assert keep.read_text() == "existing off-box backup"


def test_it_refuses_to_delete_a_directory_that_is_not_a_staging_copy(run):
    staging = run.tmp_path / "staging"
    staging.mkdir()
    (staging / "important.txt").write_text("not a backup")

    result = run(RSYNC_TARGET=f"{run.tmp_path / 'offbox'}/")

    assert result.returncode != 0
    assert "not a backup tier" in result.stdout + result.stderr
    assert (staging / "important.txt").read_text() == "not a backup"


@pytest.mark.skipif(shutil.which("rclone") is not None, reason="rclone is installed")
def test_configured_target_with_missing_tool_fails_loudly(run):
    result = run(RCLONE_REMOTE="nowhere:backups")

    assert result.returncode != 0
    assert "rclone is not installed" in result.stdout + result.stderr
