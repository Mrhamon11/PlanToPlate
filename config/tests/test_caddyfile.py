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

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CADDYFILE = BASE_DIR / "Caddyfile"
COMPOSE_FILE = BASE_DIR / "compose.yaml"


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
            f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
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
