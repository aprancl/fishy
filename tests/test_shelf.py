"""Tests for the tank shelf landing and the persistent tank switcher (task #4).

Covers the acceptance criteria for spec §5.1:
  * Component   — the shelf renders every configured tank; the switcher lists
                  all tanks and clearly marks the active one.
  * Integration — selecting a tank scopes the tank view to that tank; switching
                  re-scopes the downstream request to a different tank.
  * E2E-ish     — launch (shelf) -> pick a tank -> land in its Tank View.

Tests inject a ready-made :class:`Config` via ``FISHY_CONFIG`` so they never
touch disk and can exercise multi-tank, single-tank and empty configurations.
"""

from __future__ import annotations

import pytest

from fishy import create_app
from fishy.config import Config, Tank


def _make_client(tanks: list[Tank]):
    """Build a test client whose app is scoped to the given tanks."""
    config = Config(tanks=tanks)
    app = create_app({"TESTING": True, "FISHY_CONFIG": config})
    return app.test_client()


@pytest.fixture
def multi_tank_client():
    return _make_client([Tank(id="reef-a", label="Reef A"), Tank(id="frag-tank", label="Frag Tank")])


# --------------------------------------------------------------------------- #
# Shelf: lists all configured tanks by label
# --------------------------------------------------------------------------- #
def test_shelf_lists_all_tanks_by_label(multi_tank_client):
    body = multi_tank_client.get("/").get_data(as_text=True)
    assert "Reef A" in body
    assert "Frag Tank" in body


def test_shelf_links_into_each_tank_view(multi_tank_client):
    body = multi_tank_client.get("/").get_data(as_text=True)
    assert "/tank/reef-a" in body
    assert "/tank/frag-tank" in body


def test_default_app_loads_shipped_tanks():
    """create_app() with no injected config loads config/fishy.toml (2 tanks)."""
    client = create_app({"TESTING": True}).test_client()
    body = client.get("/").get_data(as_text=True)
    assert "Reef A" in body
    assert "Frag Tank" in body


# --------------------------------------------------------------------------- #
# Selecting a tank opens its Tank View scoped to that tank
# --------------------------------------------------------------------------- #
def test_tank_view_scopes_to_selected_tank(multi_tank_client):
    body = multi_tank_client.get("/tank/reef-a").get_data(as_text=True)
    assert "Reef A" in body
    # The scoping is surfaced to downstream views via a stable data attribute.
    assert 'data-tank-id="reef-a"' in body


def test_tank_view_returns_200_for_configured_tank(multi_tank_client):
    assert multi_tank_client.get("/tank/frag-tank").status_code == 200


def test_tank_view_placeholder_region_present(multi_tank_client):
    """Task #6 fills the placeholder; it must exist scoped to the active tank."""
    body = multi_tank_client.get("/tank/reef-a").get_data(as_text=True)
    assert "reef-tabs-placeholder" in body


# --------------------------------------------------------------------------- #
# Persistent switcher: lists all tanks and clearly indicates the active one
# --------------------------------------------------------------------------- #
def test_switcher_lists_all_tanks(multi_tank_client):
    body = multi_tank_client.get("/tank/reef-a").get_data(as_text=True)
    assert "reef-switcher" in body
    assert "Reef A" in body
    assert "Frag Tank" in body


def test_switcher_marks_active_tank(multi_tank_client):
    body = multi_tank_client.get("/tank/reef-a").get_data(as_text=True)
    # Active tank is indicated by both a CSS hook and an accessible attribute.
    assert "is-active" in body
    assert 'aria-current="page"' in body


def test_switching_rescopes_downstream_request(multi_tank_client):
    """Integration: switching the active tank re-scopes the tank view."""
    reef = multi_tank_client.get("/tank/reef-a").get_data(as_text=True)
    frag = multi_tank_client.get("/tank/frag-tank").get_data(as_text=True)
    assert 'data-tank-id="reef-a"' in reef
    assert 'data-tank-id="frag-tank"' in frag
    assert 'data-tank-id="frag-tank"' not in reef


# --------------------------------------------------------------------------- #
# Edge case: a single configured tank still works
# --------------------------------------------------------------------------- #
def test_single_tank_shelf_and_view():
    client = _make_client([Tank(id="only", label="Only Tank")])
    shelf = client.get("/").get_data(as_text=True)
    assert "Only Tank" in shelf
    assert "/tank/only" in shelf

    view = client.get("/tank/only")
    assert view.status_code == 200
    assert 'data-tank-id="only"' in view.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Error handling: no tanks configured -> friendly guidance
# --------------------------------------------------------------------------- #
def test_empty_shelf_shows_friendly_guidance():
    client = _make_client([])
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "No tanks configured" in body
    # Point the keeper at the config file they need to edit.
    assert "config/fishy.toml" in body


def test_unknown_tank_returns_404(multi_tank_client):
    assert multi_tank_client.get("/tank/does-not-exist").status_code == 404
