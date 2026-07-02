"""Tests for the Tank View parameter-tab navigation (task #6, spec §5.3 / §4.3).

Layering mirrors the rest of the suite:

  * Component   — the tab nav renders one link per configured parameter plus an
                  Aggregate slot; the active parameter's tab is clearly marked.
  * Integration — tabs reflect the ACTIVE tank's configured parameters and are
                  driven by config (adding a parameter adds a tab, no code
                  change); switching tabs keeps the active tank in the URL.
  * E2E-ish     — navigate across parameter tabs within one tank.

Tests inject a ready-made :class:`Config` (and a tmp readings path where reads
happen) so they never touch disk and can exercise empty / large / archived
parameter sets.
"""

from __future__ import annotations

from fishy import create_app
from fishy.config import Config, Parameter, Tank
from fishy.storage import Reading, append_reading as _append_file, readings_path_for


def append_reading(reading, path):
    """Seed one reading into its per-tank CSV (``<path>/<tank>/readings.csv``).

    ``path`` is the data dir (kept named ``path`` so existing positional and
    ``path=`` call sites keep working); routing is by the reading's tank.
    """
    _append_file(reading, readings_path_for(path, reading.tank))


def _client(tmp_path, *, tanks=None, parameters=None):
    """Build a test client with an injected config and tmp readings path."""
    tanks = tanks or [Tank(id="reef-a", label="Reef A")]
    parameters = parameters if parameters is not None else [
        Parameter(id="salinity", display_name="Salinity", units=("ppt",)),
        Parameter(id="alkalinity", display_name="Alkalinity", units=("dKH",)),
        Parameter(id="calcium", display_name="Calcium", units=("ppm",)),
    ]
    config = Config(tanks=tanks, parameters=parameters)
    readings_path = tmp_path  # data dir; append_reading() routes per-tank
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_DATA_DIR": readings_path,
        }
    )
    return app.test_client(), readings_path


# --------------------------------------------------------------------------- #
# Component: a tab per configured parameter, plus an Aggregate tab entry
# --------------------------------------------------------------------------- #
def test_tank_view_renders_a_tab_per_parameter(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "reef-tabs" in body
    for display in ("Salinity", "Alkalinity", "Calcium"):
        assert display in body
    # Each tab is a link to that parameter's page (scoped to the active tank).
    for pid in ("salinity", "alkalinity", "calcium"):
        assert f"/tank/reef-a/parameter/{pid}" in body


def test_tank_view_has_an_aggregate_tab_entry(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "Aggregate" in body
    assert 'data-tab="aggregate"' in body


def test_parameter_page_shows_the_tab_nav(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-tabs" in body
    assert "Alkalinity" in body  # sibling tabs are present on a parameter page


def test_active_parameter_tab_is_marked(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    # The active tab carries both a CSS hook and an accessible attribute.
    assert "is-active" in body
    assert 'aria-current="page"' in body
    # It is the salinity link that is active, marked via its data attribute.
    assert 'data-param-id="salinity"' in body


# --------------------------------------------------------------------------- #
# Integration: tabs derive from config (adding a param adds a tab, no code)
# --------------------------------------------------------------------------- #
def test_tabs_derive_from_config_adding_a_parameter_adds_a_tab(tmp_path):
    params = [
        Parameter(id="salinity", display_name="Salinity"),
        Parameter(id="nitrate", display_name="Nitrate"),  # a freshly added one
    ]
    client, _ = _client(tmp_path, parameters=params)
    body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "Nitrate" in body
    assert "/tank/reef-a/parameter/nitrate" in body


def test_tabs_reflect_the_active_tank_in_their_links(tmp_path):
    tanks = [Tank(id="reef-a", label="Reef A"), Tank(id="frag-tank", label="Frag Tank")]
    client, _ = _client(tmp_path, tanks=tanks)
    reef = client.get("/tank/reef-a").get_data(as_text=True)
    frag = client.get("/tank/frag-tank").get_data(as_text=True)
    assert "/tank/reef-a/parameter/salinity" in reef
    assert "/tank/frag-tank/parameter/salinity" in frag
    # Tabs on one tank never point at another tank.
    assert "/tank/frag-tank/parameter/" not in reef


def test_switching_tabs_preserves_the_active_tank(tmp_path):
    """Flipping between parameter tabs keeps tank_id in the URL path."""
    client, _ = _client(tmp_path)
    for pid in ("salinity", "alkalinity", "calcium"):
        resp = client.get(f"/tank/reef-a/parameter/{pid}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Scope hook stays on the active tank across every tab.
        assert 'data-tank-id="reef-a"' in body


# --------------------------------------------------------------------------- #
# Content-region seams for downstream tasks (#7 chart, #8 stats, #10 reference)
# --------------------------------------------------------------------------- #
def test_parameter_panel_exposes_downstream_content_regions(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert 'class="reef-chart"' in body
    assert 'class="reef-stats"' in body
    assert 'class="reef-reference"' in body
    # The chart seam carries both scope hooks so #7 can target it precisely.
    assert 'data-tank-id="reef-a"' in body
    assert 'data-parameter-id="salinity"' in body
    # The add-reading form (task #5) is still present in the panel.
    assert "Add Salinity reading" in body


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_tank_with_no_readings_still_renders_all_tabs(tmp_path):
    """No readings on disk must not suppress any parameter tab."""
    client, _ = _client(tmp_path)  # readings file never created
    body = client.get("/tank/reef-a").get_data(as_text=True)
    for display in ("Salinity", "Alkalinity", "Calcium"):
        assert display in body


def test_large_parameter_set_renders_every_tab(tmp_path):
    params = [Parameter(id=f"p{i}", display_name=f"Param {i}") for i in range(30)]
    client, _ = _client(tmp_path, parameters=params)
    body = client.get("/tank/reef-a").get_data(as_text=True)
    for i in range(30):
        assert f"/tank/reef-a/parameter/p{i}" in body


def test_no_parameters_configured_shows_friendly_guidance(tmp_path):
    client, _ = _client(tmp_path, parameters=[])
    resp = client.get("/tank/reef-a")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "No parameters configured" in body
    assert "config/fishy.toml" in body


# --------------------------------------------------------------------------- #
# Error handling: an archived/unknown parameter in the data (not in config)
# --------------------------------------------------------------------------- #
def test_archived_parameter_in_data_is_surfaced_not_crashing(tmp_path):
    """A reading for a param absent from config is surfaced, not fatal."""
    client, readings_path = _client(tmp_path)
    # 'nitrite' is logged but NOT in the injected config's parameters.
    append_reading(
        Reading(tank="reef-a", parameter="nitrite", date=__import__("datetime").date(2024, 1, 1), value=0.0, unit="ppm"),
        readings_path,
    )
    resp = client.get("/tank/reef-a")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # The unknown parameter is surfaced by id, and the page still renders tabs.
    assert "nitrite" in body
    assert "reef-tabs" in body
    # It does not get a real tab/link (only configured params do).
    assert "/tank/reef-a/parameter/nitrite" not in body


def test_archived_parameter_note_absent_when_all_data_is_known(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(
        Reading(tank="reef-a", parameter="salinity", date=__import__("datetime").date(2024, 1, 1), value=35.0, unit="ppt"),
        readings_path,
    )
    body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "reef-tabs__archived" not in body
