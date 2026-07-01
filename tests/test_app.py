"""Tests for the fishy app skeleton (spec §9.1 foundation).

Covers the three testing requirements for task 1:
  * Unit        — the app factory returns a valid app instance.
  * Integration — the server responds 200 on the root route.
  * Smoke       — the base page renders on localhost via a live server.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from flask import Flask

from fishy import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Unit: app factory
# --------------------------------------------------------------------------- #
def test_create_app_returns_flask_instance():
    app = create_app()
    assert isinstance(app, Flask)
    assert app.config["APP_NAME"] == "fishy"


def test_create_app_applies_config_overrides():
    app = create_app({"TESTING": True, "APP_NAME": "override"})
    assert app.config["TESTING"] is True
    assert app.config["APP_NAME"] == "override"


def test_create_app_returns_fresh_instances():
    assert create_app() is not create_app()


# --------------------------------------------------------------------------- #
# Integration: routes respond via the test client
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    return app.test_client()


def test_root_route_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_root_route_renders_base_page(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "fishy" in body
    assert "reef" in body.lower()


def test_health_route_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


# --------------------------------------------------------------------------- #
# Smoke: single-command launch serves the page on localhost
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_single_command_launch_serves_localhost():
    port = _free_port()
    env = {"FISHY_PORT": str(port), "FISHY_HOST": "127.0.0.1"}
    import os

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{port}/"
        body = None
        deadline = time.time() + 15
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode() if proc.stdout else ""
                pytest.fail(f"server exited early:\n{out}")
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    assert resp.status == 200
                    body = resp.read().decode()
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.3)
        assert body is not None, "server did not respond in time"
        assert "fishy" in body
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_server_binds_localhost_only():
    """The default host is localhost, so the server is not exposed to LAN."""
    import app as app_module

    assert app_module.DEFAULT_HOST == "127.0.0.1"
