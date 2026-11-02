"""``deploy/restore-test.sh`` — the restore drill (10.13 —
``Plan/10-Security-And-Deployment/test-plan.md``).

Builds a real, migrated scratch database via ``manage.py``, backs it up with the real
``deploy/backup.sh``, then drives the real ``deploy/restore-test.sh`` against that backup —
end to end, the same pipeline a production restore drill runs, just pointed at throwaway
files. See the manual restore drill performed during this task's implementation (the handoff
report) for the same script run once for real against the project's own dev database.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKUP_SCRIPT = BASE_DIR / "deploy" / "backup.sh"
RESTORE_SCRIPT = BASE_DIR / "deploy" / "restore-test.sh"
VENV_BIN = BASE_DIR / ".venv" / "bin"


def _dev_env(tmp_path: Path, db_path: Path) -> dict:
    return {
        **os.environ,
        "PATH": f"{VENV_BIN}:{os.environ.get('PATH', '')}",
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
        "DJANGO_ENV_FILE": str(tmp_path / "nonexistent.env"),
        "SECRET_KEY": "x" * 50,
        "ALLOWED_HOSTS": "localhost",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _run(cmd: list[str], env: dict, cwd: Path = BASE_DIR) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)


@pytest.fixture
def seeded_backup(tmp_path):
    """A real, migrated SQLite database with a couple of rows in it, already backed up via
    the real ``deploy/backup.sh``. Returns ``(db_path, data_dir)``.
    """
    db_path = tmp_path / "live.sqlite3"
    env = _dev_env(tmp_path, db_path)

    migrate = _run([sys.executable, "manage.py", "migrate", "--noinput"], env)
    assert migrate.returncode == 0, migrate.stdout + migrate.stderr

    create_users = _run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            "from django.contrib.auth import get_user_model\n"
            "Model = get_user_model()\n"
            "Model.objects.create_user('alice', password='x')\n"
            "Model.objects.create_user('bob', password='x')\n",
        ],
        env,
    )
    assert create_users.returncode == 0, create_users.stdout + create_users.stderr

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backup_env = {
        **env,
        "DATA_DIR": str(data_dir),
        "DB_PATH": str(db_path),
        "BACKUP_DIR": str(data_dir / "backups"),
        "APP_DIR": str(BASE_DIR),
    }
    backup = _run([str(BACKUP_SCRIPT), "--skip-dumpdata", "--skip-offbox-sync"], backup_env)
    assert backup.returncode == 0, backup.stdout + backup.stderr

    return db_path, data_dir


def test_restore_produces_matching_counts(seeded_backup, tmp_path):
    """Every real table's row count in the restored copy matches the live source — the
    actual point of the drill, not merely that the script exits 0.
    """
    db_path, data_dir = seeded_backup
    scratch_dir = tmp_path / "scratch"

    env = {
        **_dev_env(tmp_path, db_path),
        "DATA_DIR": str(data_dir),
        "DB_PATH": str(db_path),
        "BACKUP_DIR": str(data_dir / "backups"),
        "APP_DIR": str(BASE_DIR),
        "SCRATCH_DIR": str(scratch_dir),
        "KEEP_SCRATCH": "1",
    }
    result = _run([str(RESTORE_SCRIPT)], env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT PASS" in result.stdout

    restored_db = scratch_dir / "restored.sqlite3"
    assert restored_db.is_file()

    source_conn = sqlite3.connect(str(db_path))
    restored_conn = sqlite3.connect(str(restored_db))
    try:
        tables = [
            row[0]
            for row in source_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if row[0] != "django_migrations"
        ]
        assert tables, "expected at least one real table to compare"
        for table in tables:
            # Table names come from sqlite_master itself, not any external input, so this is
            # not the string-built-query-from-user-input pattern S608 flags — table names can't
            # be bind parameters in SQL, and quoting keeps them safe against a name containing
            # spaces or reserved words.
            query = f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608
            source_count = source_conn.execute(query).fetchone()[0]
            restored_count = restored_conn.execute(query).fetchone()[0]
            assert restored_count == source_count, f"{table}: {restored_count} != {source_count}"

        usernames = {row[0] for row in restored_conn.execute("SELECT username FROM accounts_user;")}
        assert usernames == {"alice", "bob"}
    finally:
        source_conn.close()
        restored_conn.close()


def test_restore_then_migrate_succeeds(seeded_backup, tmp_path):
    """Restoring a backup and then running ``manage.py migrate`` against the restored copy
    succeeds — design.md's edge case ('Restoring into a newer schema: restore, then migrate.
    Documented in that order.') is exactly what ``restore-test.sh`` does internally; this test
    additionally proves a *second*, independent ``migrate`` run against the already-restored
    database is a clean no-op, the realistic disaster path where an operator restores and then
    brings the schema the rest of the way forward by hand.
    """
    db_path, data_dir = seeded_backup
    scratch_dir = tmp_path / "scratch"

    env = {
        **_dev_env(tmp_path, db_path),
        "DATA_DIR": str(data_dir),
        "DB_PATH": str(db_path),
        "BACKUP_DIR": str(data_dir / "backups"),
        "APP_DIR": str(BASE_DIR),
        "SCRATCH_DIR": str(scratch_dir),
        "KEEP_SCRATCH": "1",
    }
    result = _run([str(RESTORE_SCRIPT)], env)
    assert result.returncode == 0, result.stdout + result.stderr

    restored_db = scratch_dir / "restored.sqlite3"
    migrate_again = _run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        _dev_env(tmp_path, restored_db),
    )
    assert migrate_again.returncode == 0, migrate_again.stdout + migrate_again.stderr
    assert "No migrations to apply" in migrate_again.stdout
