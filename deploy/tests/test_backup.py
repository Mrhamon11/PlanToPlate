"""``deploy/backup.sh`` (10.11 / 10.12 — ``Plan/10-Security-And-Deployment/test-plan.md``).

Drives the real script via ``subprocess`` against scratch databases and directories rather
than parsing its source for intent — a wiring mistake (a flag that silently does nothing, a
prune window off by a factor) fails here exactly like it would in production. The one
exception is ``test_backup_uses_sqlite_backup_not_cp``, which *is* a source-text assertion by
necessity: it exists to pin the mechanism the script uses, not just its output.

Every test but ``test_dumpdata_export_loads`` builds its own scratch SQLite file directly with
the standard-library ``sqlite3`` module rather than a real (slow) ``manage.py migrate`` — the
backup script does not care what is inside the database, only that ``.backup``/gzip/checksum/
retention behave correctly against it. ``test_dumpdata_export_loads`` is the one test that
needs a real, migrated Django database, since it round-trips through ``manage.py dumpdata`` /
``loaddata``.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKUP_SCRIPT = BASE_DIR / "deploy" / "backup.sh"
VENV_BIN = BASE_DIR / ".venv" / "bin"
SHA256SUM = shutil.which("sha256sum") or "sha256sum"


def _make_source_db(path: Path, *, rows: int = 20) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
        conn.executemany(
            "INSERT INTO widgets (name) VALUES (?)", [(f"widget-{i}",) for i in range(rows)]
        )
        conn.commit()
    finally:
        conn.close()


def _run_backup(*extra_args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(BACKUP_SCRIPT), *extra_args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def scratch_env(tmp_path) -> dict:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "db.sqlite3"
    _make_source_db(db_path)

    return {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "DB_PATH": str(db_path),
        "BACKUP_DIR": str(data_dir / "backups"),
    }


def _hourly_backups(env: dict) -> list[Path]:
    hourly_dir = Path(env["BACKUP_DIR"]) / "hourly"
    return sorted(hourly_dir.glob("*.sqlite3.gz"))


def test_backup_script_produces_valid_db(scratch_env):
    """The gzipped backup, once decompressed, opens as a real SQLite database and passes
    ``PRAGMA integrity_check`` — the actual promise ``.backup`` makes that a raw ``cp`` of a
    WAL database cannot.
    """
    result = _run_backup("--skip-dumpdata", "--skip-offbox-sync", env=scratch_env)
    assert result.returncode == 0, result.stdout + result.stderr

    backups = _hourly_backups(scratch_env)
    assert len(backups) == 1

    restored = backups[0].with_suffix("")  # strip .gz
    with gzip.open(backups[0], "rb") as src, open(restored, "wb") as dst:
        shutil.copyfileobj(src, dst)

    conn = sqlite3.connect(str(restored))
    try:
        assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM widgets;").fetchone()[0] == 20
    finally:
        conn.close()


def test_backup_uses_sqlite_backup_not_cp():
    """The script uses SQLite's Online Backup API (``sqlite3.Connection.backup()`` — the
    Python stdlib equivalent of the CLI's ``.backup`` dot-command, see the script's own
    docstring for why) and never a bare ``cp``/file copy of the live database. A ``cp`` on a
    WAL database can capture a torn, inconsistent state that opens fine and fails only when you
    actually need it.
    """
    source = BACKUP_SCRIPT.read_text()

    assert ".backup(" in source

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert 'cp "$DB_PATH"' not in stripped
        assert "cp $DB_PATH" not in stripped


def test_backup_checksummed(scratch_env):
    """Every backup archive gets a ``.sha256`` sidecar that actually verifies against it."""
    result = _run_backup("--skip-dumpdata", "--skip-offbox-sync", env=scratch_env)
    assert result.returncode == 0, result.stdout + result.stderr

    backup_file = _hourly_backups(scratch_env)[0]
    checksum_file = backup_file.with_name(backup_file.name + ".sha256")
    assert checksum_file.is_file()

    recorded = checksum_file.read_text().split()[0]
    actual = hashlib.sha256(backup_file.read_bytes()).hexdigest()
    assert recorded == actual


def test_checksum_sidecar_verifies_from_a_different_directory(scratch_env, tmp_path):
    """The sidecar must hold a bare filename. An absolute path only verifies on the machine
    that wrote it, which is useless for a copy that lives off-box."""
    result = _run_backup("--skip-dumpdata", "--skip-offbox-sync", env=scratch_env)
    assert result.returncode == 0, result.stdout + result.stderr

    copied = tmp_path / "elsewhere"
    shutil.copytree(Path(scratch_env["BACKUP_DIR"]) / "hourly", copied)
    shutil.rmtree(Path(scratch_env["BACKUP_DIR"]))

    check = subprocess.run(
        [SHA256SUM, "-c", *[p.name for p in copied.glob("*.sha256")]],
        cwd=copied,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_rsync_target_really_receives_the_backups(scratch_env, tmp_path):
    destination = tmp_path / "offbox"
    destination.mkdir()
    env = {**scratch_env, "RSYNC_TARGET": f"{destination}/"}

    result = _run_backup("--skip-dumpdata", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    landed = list((destination / "hourly").glob("*.sqlite3.gz"))
    assert landed, "nothing arrived at the off-box target"
    shutil.rmtree(Path(scratch_env["BACKUP_DIR"]))
    check = subprocess.run(
        [SHA256SUM, "-c", f"{landed[0].name}.sha256"],
        cwd=destination / "hourly",
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.skipif(shutil.which("rclone") is not None, reason="rclone is installed")
def test_configured_target_with_missing_tool_fails_loudly(scratch_env):
    """A set target whose tool is absent must not report success: that is exactly how a
    container without rclone/rsync used to claim a backup that never left the machine."""
    env = {**scratch_env, "RCLONE_REMOTE": "nowhere:backups"}

    result = _run_backup("--skip-dumpdata", env=env)

    assert result.returncode != 0
    assert "RCLONE_REMOTE is set but rclone is not installed" in result.stdout + result.stderr


def test_backup_promotes_into_daily_and_weekly_tiers(scratch_env):
    """Non-vacuous companion to the retention test below: today's first backup is promoted
    into the daily and weekly tiers, not just left in hourly/, or pruning would have nothing
    long-lived to prove it keeps.
    """
    result = _run_backup("--skip-dumpdata", "--skip-offbox-sync", env=scratch_env)
    assert result.returncode == 0, result.stdout + result.stderr

    backup_dir = Path(scratch_env["BACKUP_DIR"])
    assert list((backup_dir / "daily").glob("*.sqlite3.gz"))
    assert list((backup_dir / "weekly").glob("*.sqlite3.gz"))


def test_retention_prunes_correctly(tmp_path):
    """Against a directory of dated fixtures (mtimes forged with ``os.utime``, not real wall-
    clock waiting): a file older than its tier's retention window is pruned along with its
    checksum sidecar; a file inside the window survives.
    """
    backup_dir = tmp_path / "backups"
    tiers = {
        "hourly": (backup_dir / "hourly", 25 * 3600, 1 * 3600),  # retention: 24h
        "daily": (backup_dir / "daily", 31 * 86400, 1 * 86400),  # retention: 30d
        "weekly": (backup_dir / "weekly", 366 * 86400, 1 * 86400),  # retention: 365d
    }

    now = time.time()
    for _tier_name, (tier_dir, old_age_seconds, new_age_seconds) in tiers.items():
        tier_dir.mkdir(parents=True)
        for label, age in (("old", old_age_seconds), ("new", new_age_seconds)):
            archive = tier_dir / f"plantoplate-{label}.sqlite3.gz"
            checksum = tier_dir / f"plantoplate-{label}.sqlite3.gz.sha256"
            archive.write_bytes(b"not a real backup, just retention-pruning fixture bytes")
            checksum.write_text("deadbeef  irrelevant\n")
            mtime = now - age
            os.utime(archive, (mtime, mtime))
            os.utime(checksum, (mtime, mtime))

    env = {**os.environ, "BACKUP_DIR": str(backup_dir)}
    result = _run_backup("--prune-only", env=env)
    assert result.returncode == 0, result.stdout + result.stderr

    for tier_name, (tier_dir, _old, _new) in tiers.items():
        remaining = {p.name for p in tier_dir.glob("*.sqlite3.gz")}
        assert remaining == {"plantoplate-new.sqlite3.gz"}, f"{tier_name}: {remaining}"
        assert (tier_dir / "plantoplate-new.sqlite3.gz.sha256").exists()
        assert not (tier_dir / "plantoplate-old.sqlite3.gz.sha256").exists()


def _dev_env(tmp_path, db_path: Path) -> dict:
    return {
        **os.environ,
        "PATH": f"{VENV_BIN}:{os.environ.get('PATH', '')}",
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
        "DJANGO_ENV_FILE": str(tmp_path / "nonexistent.env"),
        "SECRET_KEY": "x" * 50,
        "ALLOWED_HOSTS": "localhost",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def test_dumpdata_export_loads(tmp_path):
    """The nightly ``dumpdata`` export (10.12) round-trips into a clean, freshly migrated
    database — the actual point of an engine-independent export: it must survive a real
    ``loaddata``, not just exist on disk.
    """
    source_db = tmp_path / "source.sqlite3"
    env = _dev_env(tmp_path, source_db)

    migrate = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrate.returncode == 0, migrate.stdout + migrate.stderr

    create_user = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            "from django.contrib.auth import get_user_model; "
            "get_user_model().objects.create_user('drilluser', password='x')",
        ],
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create_user.returncode == 0, create_user.stdout + create_user.stderr

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backup_env = {
        **env,
        "DATA_DIR": str(data_dir),
        "DB_PATH": str(source_db),
        "BACKUP_DIR": str(data_dir / "backups"),
        "APP_DIR": str(BASE_DIR),
    }
    result = _run_backup("--skip-offbox-sync", env=backup_env)
    assert result.returncode == 0, result.stdout + result.stderr

    dumps = sorted((data_dir / "backups" / "dumpdata").glob("*.json.gz"))
    assert len(dumps) == 1
    # Extracted into a directory of its own: `manage.py loaddata` discovers fixtures by name
    # across every fixture directory it searches, and a `.json` sitting next to the `.json.gz`
    # it was extracted from is treated as a second fixture of the same name, not the same file
    # twice — "Multiple fixtures named ... Aborting."
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    dump_json = extracted_dir / dumps[0].with_suffix("").name
    with gzip.open(dumps[0], "rb") as src, open(dump_json, "wb") as dst:
        shutil.copyfileobj(src, dst)

    target_db = tmp_path / "target.sqlite3"
    target_env = _dev_env(tmp_path, target_db)

    target_migrate = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=str(BASE_DIR),
        env=target_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert target_migrate.returncode == 0, target_migrate.stdout + target_migrate.stderr

    loaddata = subprocess.run(
        [sys.executable, "manage.py", "loaddata", str(dump_json)],
        cwd=str(BASE_DIR),
        env=target_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert loaddata.returncode == 0, loaddata.stdout + loaddata.stderr

    conn = sqlite3.connect(str(target_db))
    try:
        usernames = [row[0] for row in conn.execute("SELECT username FROM accounts_user;")]
    finally:
        conn.close()
    assert usernames == ["drilluser"]
