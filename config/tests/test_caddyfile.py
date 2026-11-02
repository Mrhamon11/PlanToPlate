"""Guard the reverse proxy's configuration file.

Nothing else in the suite can reach ``Caddyfile`` — it is consumed by a separate container,
not by Django — so a syntax error in it stays invisible to a green test run while taking the
entire production site down (ports 80/443 never bind, and ``compose.yaml`` sets ``restart:
unless-stopped``, making it a crash-loop rather than a one-off failure). That is exactly how a
site-level ``header_up`` shipped once already: ``header_up`` is a ``reverse_proxy``
subdirective, and Caddy rejects the whole file when it appears anywhere else.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CADDYFILE = BASE_DIR / "Caddyfile"
COMPOSE_FILE = BASE_DIR / "compose.yaml"
PROD_COMPOSE_FILE = BASE_DIR / "compose.prod.yaml"


def _caddy_image() -> str:
    """The image tag ``compose.yaml`` pins for the caddy service.

    Read from compose rather than hardcoded so this test always validates against the image
    that is actually deployed, including after a version bump.
    """
    for line in COMPOSE_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("image: caddy:"):
            return stripped.split("image: ", 1)[1]
    raise AssertionError(f"No caddy image pinned in {COMPOSE_FILE}")


def _enclosing_blocks(text: str) -> dict[int, tuple[str, ...]]:
    """Map each line number (1-based) to the chain of directives whose blocks enclose it.

    A deliberately small Caddyfile reader: enough to know *where* a directive sits, which is
    the property that was broken, without pretending to be a parser. Comments and quoted
    strings are not interpreted, so keep braces out of both in this file.
    """
    stack: list[str] = []
    enclosing: dict[int, tuple[str, ...]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("}"):
            stack.pop()
        enclosing[number] = tuple(stack)
        if stripped.endswith("{"):
            stack.append(stripped.removesuffix("{").strip())
    return enclosing


def test_header_up_is_nested_inside_the_reverse_proxy_block():
    """``header_up X-Forwarded-For`` is what makes the login throttle's IP key trustworthy
    (design.md, "Login throttling"), and ``config/settings/prod.py`` documents depending on it
    — but at site-block level it does not merely fail to apply, it stops Caddy from starting
    at all.
    """
    text = CADDYFILE.read_text()
    enclosing = _enclosing_blocks(text)

    header_up_lines = [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip().startswith("header_up ")
    ]
    assert header_up_lines, "Caddyfile no longer overwrites X-Forwarded-For"

    for number in header_up_lines:
        innermost = enclosing[number][-1] if enclosing[number] else ""
        assert innermost.startswith("reverse_proxy"), (
            f"Caddyfile:{number}: header_up is a reverse_proxy subdirective, but here it sits "
            f"in {innermost or 'no'} block"
        )


def test_header_up_forwarded_for_argument_is_remote_host():
    """10.8 (task 10 review, 2026-09-17): the previous version of this test only checked that
    *some* ``header_up`` line sat inside *some* ``reverse_proxy`` block, so a Caddyfile shipping
    ``header_up X-Forwarded-For {http.request.header.X-Forwarded-For}`` — echoing the client's
    own header straight back, a total throttle bypass, and a trivial DoS for a client that sends
    none at all, since ``NUM_PROXIES=1`` would then key every request on the empty string —
    passed both that test and ``caddy validate``. The argument itself has to be pinned to the
    one value that is not client-influenced.
    """
    for line in CADDYFILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("header_up X-Forwarded-For"):
            assert stripped == "header_up X-Forwarded-For {remote_host}", (
                f"header_up must forward exactly {{remote_host}} (the real TCP peer), got "
                f"{stripped!r} — anything client-influenced defeats NUM_PROXIES=1."
            )
            return
    raise AssertionError("No 'header_up X-Forwarded-For' line found in Caddyfile")


def test_header_up_targets_the_app_upstream():
    """10.8 (task 10 review, 2026-09-17): the previous version never checked *which*
    ``reverse_proxy`` block carried the directive — a decoy ``handle /unused/*`` block holding
    a correct ``header_up`` while the real proxy fronting ``app:8000`` had none would also pass
    both the old test and ``caddy validate``, and every real request would still arrive at
    Django with an untrusted ``X-Forwarded-For``.
    """
    text = CADDYFILE.read_text()
    enclosing = _enclosing_blocks(text)

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("header_up X-Forwarded-For"):
            block = enclosing[number][-1] if enclosing[number] else ""
            assert block.startswith("reverse_proxy app:8000"), (
                f"Caddyfile:{number}: header_up X-Forwarded-For sits inside {block!r}, not the "
                "reverse_proxy block fronting app:8000 — it does nothing for real traffic there."
            )
            return
    raise AssertionError("No 'header_up X-Forwarded-For' line found in Caddyfile")


def test_active_health_check_targets_healthz():
    """design.md, "Caddy" — "Health check pointed at /healthz/ from task 00": Caddy must stop
    routing to the upstream itself, not merely rely on Compose's container-level healthcheck
    (which only gates startup, via ``depends_on: condition: service_healthy``).
    """
    text = CADDYFILE.read_text()
    enclosing = _enclosing_blocks(text)

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("health_uri "):
            assert stripped == "health_uri /healthz/"
            block = enclosing[number][-1] if enclosing[number] else ""
            assert block.startswith("reverse_proxy app:8000"), (
                f"Caddyfile:{number}: health_uri sits inside {block!r}, not the reverse_proxy "
                "block fronting app:8000"
            )
            return
    raise AssertionError("No 'health_uri' active health check found in Caddyfile")


def test_caddyfile_is_valid_for_the_pinned_caddy_image():
    """The real check: adapt the file with the exact Caddy build ``compose.yaml`` deploys.

    Skipped rather than failed when Docker or the pinned image is unavailable — this must not
    turn the suite red on a machine that simply has no local copy of the image, and it
    deliberately never pulls (no network in a test run).
    """
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    image = _caddy_image()
    if subprocess.run([docker, "image", "inspect", image], capture_output=True).returncode != 0:
        pytest.skip(f"{image} is not present locally")

    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{CADDYFILE}:/etc/caddy/Caddyfile:ro,z",
            image,
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Valid configuration" in result.stderr + result.stdout


def test_health_probe_sends_the_public_host_header():
    """Caddy's probe otherwise carries ``Host: app:8000``, which Django's ALLOWED_HOSTS rejects
    with a 400 - so Caddy would mark the only upstream permanently down."""
    text = CADDYFILE.read_text()
    enclosing = _enclosing_blocks(text)

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("Host "):
            assert "{$SITE_ADDRESS" in line
            assert any(b.startswith("health_headers") for b in enclosing[number])
            return
    raise AssertionError("No 'Host' entry under health_headers found in Caddyfile")


def test_prod_compose_has_selinux_relabel_and_ipv4_caddy_healthcheck():
    """The bind-mounted Caddyfile needs ``,z`` or an enforcing host (Fedora) denies the read and
    Caddy crash-loops; the healthcheck must use 127.0.0.1 because Alpine resolves localhost to
    ::1, where Caddy's admin API does not listen."""
    text = PROD_COMPOSE_FILE.read_text()

    assert "./Caddyfile:/etc/caddy/Caddyfile:ro,z" in text
    assert "http://127.0.0.1:2019/config/" in text
    assert "http://localhost:2019" not in text


def test_tailscale_override_is_opt_in_and_carries_the_socket_and_label():
    """The socket mount lives only in the override: a base file that mounted a socket which does
    not exist on the host would make Docker create a directory in its place (D60)."""
    socket_path = "/var/run/tailscale/tailscaled.sock"
    base = yaml.safe_load(PROD_COMPOSE_FILE.read_text())
    override = yaml.safe_load((BASE_DIR / "compose.tailscale.yaml").read_text())

    assert not any(socket_path in volume for volume in base["services"]["caddy"]["volumes"])
    assert "label=disable" in override["services"]["caddy"]["security_opt"]
    assert any(socket_path in volume for volume in override["services"]["caddy"]["volumes"])
