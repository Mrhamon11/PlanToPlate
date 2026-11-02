"""Guards the production WSGI server's own configuration (10.9, design.md "Deployment" —
"Gunicorn — 2 workers x 4 gthread threads").

``gunicorn.conf.py`` is consumed by a separate process (``gunicorn --config gunicorn.conf.py``,
started from ``docker-entrypoint.sh``), not imported by the app itself, so nothing else in the
suite would notice a regression here — loaded by path with ``runpy`` rather than a normal
import since it sits outside every Django app package.
"""

import runpy
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONF_PATH = BASE_DIR / "gunicorn.conf.py"


def _load_conf() -> dict:
    return runpy.run_path(str(CONF_PATH))


def test_two_workers_four_threads_gthread():
    conf = _load_conf()
    assert conf["workers"] == 2
    assert conf["threads"] == 4
    assert conf["worker_class"] == "gthread"


def test_timeouts_configured():
    conf = _load_conf()
    assert conf["timeout"] > 0
    assert conf["graceful_timeout"] > 0
    # The worker watchdog must outlast SQLite's own busy_timeout (config/settings/base.py's
    # SQLITE_OPTIONS, 5000ms) or a healthy worker waiting on a lock gets killed as if it were
    # wedged.
    assert conf["timeout"] >= 60


def test_access_logging_to_stdout():
    conf = _load_conf()
    assert conf["accesslog"] == "-"
    assert conf["errorlog"] == "-"


def test_preload_app_disabled():
    """preload_app=True would fork every worker from a parent that already holds an open
    SQLite connection — a connection object shared across a fork is not something SQLite
    supports safely. Must stay off.
    """
    conf = _load_conf()
    assert conf["preload_app"] is False


def test_binds_to_container_port_8000():
    conf = _load_conf()
    assert conf["bind"] == "0.0.0.0:8000"  # noqa: S104 -- inside a container, not the host


def test_worker_recycling_is_jittered():
    """Sharing one restart instant across both workers would drop capacity to zero for a
    moment; the jitter must be non-zero so that cannot happen.
    """
    conf = _load_conf()
    assert conf["max_requests"] > 0
    assert conf["max_requests_jitter"] > 0
