#!/usr/bin/env python3
"""fishy entry point.

Run the app on localhost with a single command:

    python app.py

Environment overrides (optional):
    FISHY_HOST  bind host  (default: 127.0.0.1 — localhost only)
    FISHY_PORT  bind port  (default: 5000)

This module is deliberately thin: it wires up dependency and port-in-use error
handling around the application factory in the :mod:`fishy` package.
"""

from __future__ import annotations

import errno
import os
import sys

# Default to localhost only so the server is not reachable from other machines
# (see spec §6.2 / §7.5 — localhost-only, no network exposure).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def _fail_missing_dependency(exc: ModuleNotFoundError) -> None:
    """Print an actionable message and exit when a dependency is missing."""
    sys.stderr.write(
        f"\nfishy could not start: missing dependency '{exc.name}'.\n\n"
        "Install the project's dependencies first:\n\n"
        "    python -m pip install -r requirements.txt\n\n"
    )
    raise SystemExit(1)


def _fail_port_in_use(host: str, port: int) -> None:
    """Print a friendly message and exit when the port is already in use."""
    sys.stderr.write(
        f"\nfishy could not start: port {port} on {host} is already in use.\n\n"
        "Close the program using it, or choose another port:\n\n"
        f"    FISHY_PORT=8080 python app.py\n\n"
    )
    raise SystemExit(1)


def _resolve_port() -> int:
    """Read the port from the environment, falling back to the default."""
    raw = os.environ.get("FISHY_PORT")
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        sys.stderr.write(
            f"\nfishy: FISHY_PORT must be a number, got {raw!r}. "
            f"Using default {DEFAULT_PORT}.\n"
        )
        return DEFAULT_PORT


def main() -> None:
    """Start the fishy web server on localhost."""
    try:
        from fishy import create_app
    except ModuleNotFoundError as exc:
        _fail_missing_dependency(exc)
        return  # unreachable; keeps type checkers happy

    host = os.environ.get("FISHY_HOST", DEFAULT_HOST)
    port = _resolve_port()

    app = create_app()

    try:
        app.run(host=host, port=port, debug=False)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES):
            _fail_port_in_use(host, port)
        raise


if __name__ == "__main__":
    main()
