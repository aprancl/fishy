"""Tests for user-defined custom parameters (task #11, spec §5.6).

A "custom" parameter is any parameter a keeper adds to ``config/fishy.toml`` that
is not part of the shipped built-in reef set. The whole pipeline is already
config-driven — a configured parameter automatically becomes a tab (#6) with a
chart (#7), stats (#8), reference (#10) and an add-reading form (#5) — so these
tests PROVE that custom parameters flow through end-to-end and lock in the
specific edge/error behaviours the spec calls out:

  * a custom parameter surfaces as a tab with chart + stats + form, and its
    reference falls back to the ``_template.md`` placeholders;
  * the parameter's unit labels the chart axis, the displayed values and the
    stat cards;
  * a custom parameter with NO target range plots its data with no band and
    never flags a reading out-of-range;
  * two parameters sharing a display name are disambiguated by their distinct
    ``id`` (the UI keys tabs/routes by id);
  * a reading whose parameter id is no longer in config is surfaced (archived),
    not fatal;
  * multi-unit parameters store values in the FIRST (canonical) declared unit —
    the add-reading form records that unit (Open Question #3).

Tests inject a ready-made :class:`Config` and a tmp readings path so they never
touch the repo's real data file, except the shipped-config test which loads the
real ``config/fishy.toml`` (read-only) to prove the example custom parameter is
wired without code changes.
"""

from __future__ import annotations

import datetime as dt

from fishy import _chart_series, _parameter_stats, create_app
from fishy.config import Config, Parameter, Tank, TargetRange, load_config
from fishy.storage import Reading, append_reading, load_readings


def _client(tmp_path, *, tanks=None, parameters=None):
    """Build a test client with an injected config and tmp readings path."""
    tanks = tanks or [Tank(id="reef-a", label="Reef A")]
    if parameters is None:
        parameters = [Parameter(id="salinity", display_name="Salinity", units=("ppt",))]
    config = Config(tanks=tanks, parameters=parameters)
    readings_path = tmp_path / "readings.csv"
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_READINGS_PATH": readings_path,
        }
    )
    return app.test_client(), readings_path


# --------------------------------------------------------------------------- #
# Functional: a custom parameter (unit, no range) flows through the whole UI
# --------------------------------------------------------------------------- #
def test_custom_parameter_renders_tab_chart_stats_form(tmp_path):
    """A configured custom param appears as a tab with chart, stats and form."""
    params = [
        Parameter(id="salinity", display_name="Salinity", units=("ppt",)),
        # Custom: has a unit, no target range.
        Parameter(id="temperature", display_name="Temperature", units=("°C", "°F")),
    ]
    client, _ = _client(tmp_path, parameters=params)

    # It appears as a tab on the tank landing and links to its own page.
    tank_body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "Temperature" in tank_body
    assert "/tank/reef-a/parameter/temperature" in tank_body

    # Its per-parameter page renders the chart, stats and add-reading seams.
    page = client.get("/tank/reef-a/parameter/temperature")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'class="reef-chart"' in body
    assert 'data-parameter-id="temperature"' in body
    assert 'class="reef-stats"' in body
    # The add-reading form posts to the custom parameter's own route.
    assert "/tank/reef-a/parameter/temperature/reading" in body


def test_custom_parameter_reference_uses_template_placeholders(tmp_path):
    """A custom param with no content/<id>.md shows the _template placeholders."""
    params = [Parameter(id="temperature", display_name="Temperature", units=("°C",))]
    config = Config(tanks=[Tank(id="reef-a", label="Reef A")], parameters=params)
    # Default content dir has no temperature.md → falls back to _template.md.
    content = config.content_for("temperature")
    assert content.source is not None and content.source.name == "_template.md"
    # Template sections are treated as placeholders, not authored content.
    assert not content.is_present("definition")
    assert not content.is_present("ideal_range")

    # And the reference accordion still renders (all seven sections present).
    client, _ = _client(tmp_path, parameters=params)
    body = client.get("/tank/reef-a/parameter/temperature").get_data(as_text=True)
    assert 'class="reef-reference"' in body


# --------------------------------------------------------------------------- #
# Functional: the unit labels axis, values and stat cards
# --------------------------------------------------------------------------- #
def test_unit_labels_chart_axis_values_and_stats(tmp_path):
    """The parameter's canonical unit labels the chart, values and stat cards."""
    param = Parameter(id="temperature", display_name="Temperature", units=("°C", "°F"))
    readings = [Reading(tank="reef-a", parameter="temperature", date=dt.date(2024, 1, 1), value=25.0, unit="°C")]

    # Chart contract carries the canonical unit for the axis + hover labels.
    series = _chart_series(readings, param, "reef-a")
    assert series["unit"] == "°C"

    # Stats carry the same unit for the value cards.
    stats = _parameter_stats(series["points"], unit=series["unit"])
    assert stats["unit"] == "°C"

    # Rendered page shows the unit next to the logged value + in the stat card.
    client, readings_path = _client(tmp_path, parameters=[param])
    append_reading(readings[0], readings_path)
    body = client.get("/tank/reef-a/parameter/temperature").get_data(as_text=True)
    assert "°C" in body


# --------------------------------------------------------------------------- #
# Error handling: a custom parameter with NO range → no band, nothing flagged
# --------------------------------------------------------------------------- #
def test_no_range_parameter_plots_without_band_or_flags(tmp_path):
    """No target range → chart band is null and no reading is out-of-range."""
    param = Parameter(id="temperature", display_name="Temperature", units=("°C",))
    assert param.target_range is None  # custom param declares no band

    readings = [
        Reading(tank="reef-a", parameter="temperature", date=dt.date(2024, 1, 1), value=24.0, unit="°C"),
        Reading(tank="reef-a", parameter="temperature", date=dt.date(2024, 1, 2), value=999.0, unit="°C"),
    ]
    series = _chart_series(readings, param, "reef-a")
    # No usable band → both bounds null so the client draws no shaded region.
    assert series["range"] == {"min": None, "max": None}
    # Data still plots and nothing is flagged out-of-range (even an extreme).
    assert [p["in_range"] for p in series["points"]] == [True, True]
    assert len(series["points"]) == 2

    # End-to-end: the page renders and the stat badge reads "In range".
    client, readings_path = _client(tmp_path, parameters=[param])
    for r in readings:
        append_reading(r, readings_path)
    body = client.get("/tank/reef-a/parameter/temperature").get_data(as_text=True)
    assert "Out of range" not in body


# --------------------------------------------------------------------------- #
# Edge case: two parameters with the SAME display name, distinct ids
# --------------------------------------------------------------------------- #
def test_same_display_name_disambiguated_by_id(tmp_path):
    """Two params may share a display name but render as two distinct tabs."""
    params = [
        Parameter(id="nitrate", display_name="Nitrogen", units=("ppm",)),
        Parameter(id="nitrite", display_name="Nitrogen", units=("ppm",)),
    ]
    client, _ = _client(tmp_path, parameters=params)

    body = client.get("/tank/reef-a").get_data(as_text=True)
    # Two DISTINCT tab links keyed by id, even though the labels collide.
    assert 'data-param-id="nitrate"' in body
    assert 'data-param-id="nitrite"' in body
    assert "/tank/reef-a/parameter/nitrate" in body
    assert "/tank/reef-a/parameter/nitrite" in body

    # Each id routes to its own distinct page (not merged by display name).
    assert client.get("/tank/reef-a/parameter/nitrate").status_code == 200
    assert client.get("/tank/reef-a/parameter/nitrite").status_code == 200


def test_duplicate_ids_are_warned_and_deduped():
    """Two params with the SAME id (not just name) is a config warning, deduped."""
    from fishy.config import _parse_parameters

    warnings: list[str] = []
    data = {
        "parameters": [
            {"id": "nitrate", "display_name": "Nitrate A", "units": ["ppm"]},
            {"id": "nitrate", "display_name": "Nitrate B", "units": ["ppm"]},
        ]
    }
    params = _parse_parameters(data, {}, warnings)
    assert [p.id for p in params] == ["nitrate"]  # later duplicate dropped
    assert any("Duplicate parameter id 'nitrate'" in w for w in warnings)


# --------------------------------------------------------------------------- #
# Edge case: a removed parameter that still has readings is archived, not fatal
# --------------------------------------------------------------------------- #
def test_removed_parameter_with_readings_is_archived_not_crashing(tmp_path):
    """Readings for a param no longer in config → tank view still renders."""
    # Config only knows salinity; 'temperature' was removed but has readings.
    client, readings_path = _client(
        tmp_path, parameters=[Parameter(id="salinity", display_name="Salinity", units=("ppt",))]
    )
    append_reading(
        Reading(tank="reef-a", parameter="temperature", date=dt.date(2024, 1, 1), value=25.0, unit="°C"),
        readings_path,
    )

    resp = client.get("/tank/reef-a")
    assert resp.status_code == 200  # no 500 crash
    body = resp.get_data(as_text=True)
    # The archived note surfaces the orphaned id, but it gets no real tab/route.
    assert "reef-tabs__archived" in body
    assert "temperature" in body
    assert "/tank/reef-a/parameter/temperature" not in body

    # Directly visiting the removed parameter's page 404s (not in config).
    assert client.get("/tank/reef-a/parameter/temperature").status_code == 404


# --------------------------------------------------------------------------- #
# Multi-unit / Open Question #3: the FIRST declared unit is canonical
# --------------------------------------------------------------------------- #
def test_multi_unit_parameter_records_canonical_unit(tmp_path):
    """Add-reading stores the FIRST declared unit for a multi-unit parameter."""
    param = Parameter(id="temperature", display_name="Temperature", units=("°C", "°F"))
    assert param.default_unit == "°C"  # first declared unit is canonical

    client, readings_path = _client(tmp_path, parameters=[param])
    resp = client.post(
        "/tank/reef-a/parameter/temperature/reading",
        data={"value": "25.5", "date": "2024-01-01"},
    )
    assert resp.status_code == 302  # PRG redirect on success

    rows = load_readings(readings_path, emit_warnings=False).readings
    assert len(rows) == 1
    # The reading is stored in the canonical unit, not the alternate one.
    assert rows[0].unit == "°C"
    assert rows[0].parameter == "temperature"


# --------------------------------------------------------------------------- #
# Integration: the SHIPPED config surfaces the example custom parameter with no
# code change (proves "add a parameter in config and it appears").
# --------------------------------------------------------------------------- #
def test_shipped_config_ships_example_custom_parameter():
    """The shipped fishy.toml carries a non-builtin example param, no warnings."""
    conf = load_config()
    temp = conf.parameter("temperature")
    assert temp is not None
    assert temp.builtin is False  # it's a custom, not a built-in reef param
    assert temp.default_unit == "°C"  # first declared unit is canonical
    assert temp.target_range is None  # demonstrates the no-band case
    assert conf.warnings == []  # the example must not introduce config warnings


def test_shipped_custom_parameter_flows_through_ui_end_to_end(tmp_path):
    """E2E: with the real config, add a reading for the custom param and see it."""
    # No injected FISHY_CONFIG → loads the real config/fishy.toml (temperature).
    readings_path = tmp_path / "readings.csv"
    app = create_app({"TESTING": True, "FISHY_READINGS_PATH": readings_path})
    client = app.test_client()

    # The temperature tab is present on a real shipped tank.
    tank_body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "Temperature" in tank_body
    assert "/tank/reef-a/parameter/temperature" in tank_body

    # Log a reading and confirm it persists + shows on the page.
    resp = client.post(
        "/tank/reef-a/parameter/temperature/reading",
        data={"value": "25", "date": "2024-06-01"},
    )
    assert resp.status_code == 302
    body = client.get("/tank/reef-a/parameter/temperature").get_data(as_text=True)
    assert "2024-06-01" in body
    assert "°C" in body  # canonical unit labels the logged value
