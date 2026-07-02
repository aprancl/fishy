"""Tests for creating and deleting tanks (spec §5.1 tank management).

Two layers, mirroring the project's other test files:

  * Unit  — :mod:`fishy.tank_store` and :func:`fishy.storage.delete_tank_data`
            exercised directly as pure data layers (no Flask), so the
            comment-preserving TOML edits and the per-tank directory removal are
            verified in isolation.
  * Integration — the ``POST /tanks`` and ``POST /tank/<id>/delete`` routes via
            the Flask test client, pointed at a tmp config + tmp CSV so nothing
            touches the repo's real data.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from fishy import create_app
from fishy.config import load_config
from fishy.storage import (
    Reading,
    append_readings,
    delete_tank_data,
    load_readings,
    readings_path_for,
)
from fishy import tank_store


# A minimal, realistic config with two tanks, one parameter and a per-tank
# override — so deletion of override tables is covered too.
_BASE_CONFIG = """\
# fishy config for tests

[[tanks]]
id = "reef-a"
label = "Reef A"

[[tanks]]
id = "frag-tank"
label = "Frag Tank"


# --- parameters ---
[[parameters]]
id = "alkalinity"
display_name = "Alkalinity"
units = ["dKH"]
target_range = { min = 8.0, max = 9.0 }


[overrides.frag-tank.alkalinity]
min = 8.2
max = 8.8
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "fishy.toml"
    path.write_text(_BASE_CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def client(tmp_path, config_file):
    """A test client whose config + readings paths point at tmp files.

    FISHY_CONFIG is intentionally NOT injected so the app loads (and reloads)
    from the tmp TOML — exercising the real create/delete write path.
    """
    data_dir = tmp_path
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG_PATH": str(config_file),
            "FISHY_DATA_DIR": str(data_dir),
        }
    )
    return app.test_client(), data_dir


# --------------------------------------------------------------------------- #
# Unit: slugify / id validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "label,expected",
    [
        ("Display Reef", "display-reef"),
        ("  Nano  Cube 20 ", "nano-cube-20"),
        ("Reef!!! A", "reef-a"),
        ("SPS Dominant", "sps-dominant"),
        ("---", ""),
        ("🐠", ""),
    ],
)
def test_slugify(label, expected):
    assert tank_store.slugify(label) == expected


@pytest.mark.parametrize(
    "tank_id,ok",
    [
        ("reef-a", True),
        ("display-reef", True),
        ("nano20", True),
        ("Reef-A", False),   # uppercase
        ("-lead", False),    # leading hyphen
        ("has space", False),
        ("", False),
    ],
)
def test_is_valid_id(tank_id, ok):
    assert tank_store.is_valid_id(tank_id) is ok


# --------------------------------------------------------------------------- #
# Unit: add_tank
# --------------------------------------------------------------------------- #
def test_add_tank_appends_and_is_loadable(config_file):
    tank_store.add_tank(config_file, "display-reef", "Display Reef")

    cfg = load_config(config_file)
    ids = [t.id for t in cfg.tanks]
    assert ids == ["reef-a", "frag-tank", "display-reef"]
    assert cfg.tank("display-reef").label == "Display Reef"


def test_add_tank_preserves_parameters_and_overrides(config_file):
    tank_store.add_tank(config_file, "display-reef", "Display Reef")

    cfg = load_config(config_file)
    # The parameter and the per-tank override both survive the surgical edit.
    assert cfg.parameter("alkalinity") is not None
    frag_range = cfg.parameter("alkalinity").range_for_tank("frag-tank")
    assert (frag_range.min, frag_range.max) == (8.2, 8.8)
    # And no warnings crept in (file still parses cleanly).
    assert cfg.warnings == []


def test_add_tank_rejects_duplicate(config_file):
    with pytest.raises(tank_store.TankStoreError):
        tank_store.add_tank(config_file, "reef-a", "Another Reef A")


def test_add_tank_rejects_bad_id(config_file):
    with pytest.raises(tank_store.TankStoreError):
        tank_store.add_tank(config_file, "Bad Id", "Whatever")


def test_add_tank_escapes_quotes_in_label(config_file):
    tank_store.add_tank(config_file, "quoted", 'The "Big" Reef')
    cfg = load_config(config_file)
    assert cfg.tank("quoted").label == 'The "Big" Reef'


def test_add_tank_into_empty_config(tmp_path):
    path = tmp_path / "fishy.toml"
    path.write_text("# just a comment, no tanks yet\n", encoding="utf-8")
    tank_store.add_tank(path, "first", "First Tank")
    cfg = load_config(path)
    assert [t.id for t in cfg.tanks] == ["first"]


# --------------------------------------------------------------------------- #
# Unit: delete_tank
# --------------------------------------------------------------------------- #
def test_delete_tank_removes_block(config_file):
    tank_store.delete_tank(config_file, "reef-a")
    cfg = load_config(config_file)
    assert [t.id for t in cfg.tanks] == ["frag-tank"]


def test_delete_tank_removes_its_overrides(config_file):
    tank_store.delete_tank(config_file, "frag-tank")
    text = config_file.read_text(encoding="utf-8")
    # The dangling override table for the deleted tank is gone...
    assert "overrides.frag-tank" not in text
    # ...but the parameter it referenced is untouched.
    cfg = load_config(config_file)
    assert cfg.parameter("alkalinity") is not None
    assert cfg.warnings == []


def test_delete_tank_unknown_raises(config_file):
    with pytest.raises(tank_store.TankStoreError):
        tank_store.delete_tank(config_file, "nope")


# --------------------------------------------------------------------------- #
# Unit: delete_tank_data (storage)
# --------------------------------------------------------------------------- #
def test_delete_tank_data_removes_only_that_tank(tmp_path):
    append_readings(
        [
            Reading("reef-a", "alkalinity", _dt.date(2026, 6, 1), 8.4, "dKH"),
            Reading("reef-a", "alkalinity", _dt.date(2026, 6, 2), 8.3, "dKH"),
        ],
        readings_path_for(tmp_path, "reef-a"),
    )
    append_readings(
        [Reading("frag-tank", "alkalinity", _dt.date(2026, 6, 1), 8.5, "dKH")],
        readings_path_for(tmp_path, "frag-tank"),
    )

    assert delete_tank_data("reef-a", tmp_path) is True
    # reef-a's whole directory is gone; frag-tank's file is untouched.
    assert not readings_path_for(tmp_path, "reef-a").exists()
    remaining = load_readings(readings_path_for(tmp_path, "frag-tank")).readings
    assert [r.tank for r in remaining] == ["frag-tank"]


def test_delete_tank_data_missing_dir_is_noop(tmp_path):
    assert delete_tank_data("reef-a", tmp_path) is False


# --------------------------------------------------------------------------- #
# Integration: create route
# --------------------------------------------------------------------------- #
def test_create_tank_route_creates_and_redirects(client):
    test_client, _ = client
    resp = test_client.post("/tanks", data={"label": "Display Reef"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/tank/display-reef")

    # The new tank now shows on the shelf.
    shelf = test_client.get("/").get_data(as_text=True)
    assert "Display Reef" in shelf
    assert "/tank/display-reef" in shelf


def test_create_tank_route_uses_explicit_id(client):
    test_client, _ = client
    resp = test_client.post("/tanks", data={"label": "My Reef", "id": "custom-id"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/tank/custom-id")


def test_create_tank_route_rejects_blank_name(client):
    test_client, _ = client
    resp = test_client.post("/tanks", data={"label": "   "})
    assert resp.status_code == 400
    assert "name" in resp.get_data(as_text=True).lower()


def test_create_tank_route_rejects_duplicate(client):
    test_client, _ = client
    resp = test_client.post("/tanks", data={"label": "Reef A"})  # slugs to reef-a
    assert resp.status_code == 400
    assert "already exists" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Integration: delete route
# --------------------------------------------------------------------------- #
def test_delete_tank_route_removes_tank_and_readings(client):
    test_client, data_dir = client
    append_readings(
        [Reading("reef-a", "alkalinity", _dt.date(2026, 6, 1), 8.4, "dKH")],
        readings_path_for(data_dir, "reef-a"),
    )
    append_readings(
        [Reading("frag-tank", "alkalinity", _dt.date(2026, 6, 1), 8.5, "dKH")],
        readings_path_for(data_dir, "frag-tank"),
    )

    resp = test_client.post("/tank/reef-a/delete")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")

    shelf = test_client.get("/").get_data(as_text=True)
    assert "Reef A" not in shelf
    assert "Frag Tank" in shelf

    # The deleted tank's data directory is gone; the other tank's remains.
    assert not readings_path_for(data_dir, "reef-a").exists()
    remaining = load_readings(readings_path_for(data_dir, "frag-tank")).readings
    assert [r.tank for r in remaining] == ["frag-tank"]


def test_delete_tank_route_unknown_returns_404(client):
    test_client, _ = client
    assert test_client.post("/tank/does-not-exist/delete").status_code == 404


def test_shelf_shows_delete_control_per_tank(client):
    test_client, _ = client
    body = test_client.get("/").get_data(as_text=True)
    assert "/tank/reef-a/delete" in body
    assert "/tank/frag-tank/delete" in body
