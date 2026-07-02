"""Tests for the parameter time-series chart + target-range band (task #7, §5.3).

Layering mirrors the rest of the suite:

  * Unit       — range selection (`_range_for`) and in/out-of-range
                 classification (`_classify_in_range`), plus the serialisable
                 `_chart_series` contract, all Flask-free and browser-free.
  * Component  — the parameter page emits the chart seam, the inline JSON
                 contract (points + band + out-of-range styling), and loads
                 Plotly + chart.js.
  * E2E-ish    — log a reading via the form, then GET the page and confirm the
                 chart contract updates with the correct in/out-of-range flag.

Tests inject a ready-made :class:`Config` (and a tmp readings path where reads
happen) so they never touch the repo's real data file.
"""

from __future__ import annotations

import datetime as dt
import json

from fishy import _chart_series, _classify_in_range, _range_for, create_app
from fishy.config import Config, Parameter, Tank, TargetRange
from fishy.storage import Reading, append_reading as _append_file, readings_path_for


def append_reading(reading, path):
    """Seed one reading into its per-tank CSV (``<path>/<tank>/readings.csv``).

    ``path`` is the data dir (kept named ``path`` so existing positional and
    ``path=`` call sites keep working); routing is by the reading's tank.
    """
    _append_file(reading, readings_path_for(path, reading.tank))


def _reading(param, value, day, tank="reef-a", unit="ppt"):
    return Reading(
        tank=tank,
        parameter=param,
        date=dt.date(2024, 1, day),
        value=value,
        unit=unit,
    )


def _client(tmp_path, *, tanks=None, parameters=None):
    tanks = tanks or [Tank(id="reef-a", label="Reef A")]
    parameters = parameters if parameters is not None else [
        Parameter(
            id="salinity",
            display_name="Salinity",
            units=("ppt",),
            target_range=TargetRange(min=34.0, max=36.0),
        ),
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


def _chart_json(body):
    """Extract the inline JSON contract from a rendered parameter page."""
    marker = '<script type="application/json" class="reef-chart-data">'
    start = body.index(marker) + len(marker)
    end = body.index("</script>", start)
    return json.loads(body[start:end])


# --------------------------------------------------------------------------- #
# Unit: range selection helper (the seam task #9 will extend)
# --------------------------------------------------------------------------- #
def test_range_for_returns_the_parameter_default_range():
    rng = TargetRange(min=34.0, max=36.0)
    param = Parameter(id="salinity", display_name="Salinity", target_range=rng)
    # Task #7 uses the default range regardless of tank (per-tank comes in #9).
    assert _range_for(param, "reef-a") is rng
    assert _range_for(param, "any-other-tank") is rng


def test_range_for_none_when_parameter_has_no_range():
    param = Parameter(id="ph", display_name="pH")
    assert _range_for(param, "reef-a") is None


# --------------------------------------------------------------------------- #
# Unit: in/out-of-range classification
# --------------------------------------------------------------------------- #
def test_classify_in_range_two_sided():
    rng = TargetRange(min=34.0, max=36.0)
    assert _classify_in_range(35.0, rng) is True
    assert _classify_in_range(34.0, rng) is True  # inclusive bound
    assert _classify_in_range(36.0, rng) is True  # inclusive bound
    assert _classify_in_range(33.9, rng) is False
    assert _classify_in_range(36.1, rng) is False


def test_classify_in_range_one_sided_lower():
    rng = TargetRange(min=8.0, max=None)
    assert _classify_in_range(7.9, rng) is False
    assert _classify_in_range(8.0, rng) is True
    assert _classify_in_range(1000.0, rng) is True


def test_classify_in_range_one_sided_upper():
    rng = TargetRange(min=None, max=0.03)
    assert _classify_in_range(0.02, rng) is True
    assert _classify_in_range(0.03, rng) is True
    assert _classify_in_range(0.05, rng) is False


def test_classify_in_range_no_range_flags_nothing():
    assert _classify_in_range(999.0, None) is True
    assert _classify_in_range(0.0, TargetRange()) is True  # empty band


# --------------------------------------------------------------------------- #
# Unit: _chart_series contract
# --------------------------------------------------------------------------- #
def test_chart_series_sorts_by_date_and_flags_points():
    param = Parameter(
        id="salinity",
        display_name="Salinity",
        units=("ppt",),
        target_range=TargetRange(min=34.0, max=36.0),
    )
    readings = [
        _reading("salinity", 40.0, 3),  # out of range, latest
        _reading("salinity", 35.0, 1),  # in range, oldest
        _reading("salinity", 33.0, 2),  # out of range (below), middle
    ]
    data = _chart_series(readings, param, "reef-a")

    assert data["tank_id"] == "reef-a"
    assert data["parameter_id"] == "salinity"
    assert data["display_name"] == "Salinity"
    assert data["unit"] == "ppt"
    assert data["range"] == {"min": 34.0, "max": 36.0}

    # Sorted oldest -> newest by date.
    dates = [p["date"] for p in data["points"]]
    assert dates == ["2024-01-01", "2024-01-02", "2024-01-03"]
    flags = [p["in_range"] for p in data["points"]]
    assert flags == [True, False, False]


def test_chart_series_single_reading():
    param = Parameter(
        id="salinity",
        display_name="Salinity",
        target_range=TargetRange(min=34.0, max=36.0),
    )
    data = _chart_series([_reading("salinity", 35.0, 1)], param, "reef-a")
    assert len(data["points"]) == 1
    assert data["points"][0]["in_range"] is True


def test_chart_series_one_sided_range_band():
    param = Parameter(
        id="ph",
        display_name="pH",
        target_range=TargetRange(min=8.0, max=None),
    )
    data = _chart_series([_reading("ph", 8.2, 1, unit="")], param, "reef-a")
    assert data["range"] == {"min": 8.0, "max": None}


def test_chart_series_no_range_yields_null_band_no_flags():
    param = Parameter(id="ph", display_name="pH")
    data = _chart_series(
        [_reading("ph", 8.2, 1, unit=""), _reading("ph", 99.0, 2, unit="")],
        param,
        "reef-a",
    )
    assert data["range"] == {"min": None, "max": None}
    # Nothing is flagged out of range when there is no usable band.
    assert all(p["in_range"] for p in data["points"])


def test_chart_series_invalid_range_treated_as_no_band():
    param = Parameter(
        id="salinity",
        display_name="Salinity",
        target_range=TargetRange(min=36.0, max=34.0),  # min > max = invalid
    )
    data = _chart_series([_reading("salinity", 35.0, 1)], param, "reef-a")
    assert data["range"] == {"min": None, "max": None}
    assert data["points"][0]["in_range"] is True


def test_chart_series_empty_readings():
    param = Parameter(id="salinity", display_name="Salinity")
    data = _chart_series([], param, "reef-a")
    assert data["points"] == []


# --------------------------------------------------------------------------- #
# Component: the parameter page emits the seam, contract, and chart assets
# --------------------------------------------------------------------------- #
def test_parameter_page_loads_plotly_and_chart_js(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "cdn.plot.ly" in body
    assert "js/chart.js" in body


def test_parameter_page_embeds_chart_contract(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1), readings_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert 'class="reef-chart-data"' in body
    data = _chart_json(body)
    assert data["range"] == {"min": 34.0, "max": 36.0}
    assert len(data["points"]) == 1
    assert data["points"][0]["value"] == 35.0
    assert data["points"][0]["in_range"] is True


def test_parameter_page_marks_out_of_range_point(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 30.0, 1), readings_path)  # below 34
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    data = _chart_json(body)
    assert data["points"][0]["in_range"] is False


def test_parameter_page_single_reading_does_not_break(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1), readings_path)
    resp = client.get("/tank/reef-a/parameter/salinity")
    assert resp.status_code == 200
    data = _chart_json(resp.get_data(as_text=True))
    assert len(data["points"]) == 1


def test_parameter_page_no_range_plots_without_band_no_error(tmp_path):
    params = [Parameter(id="ph", display_name="pH")]  # no target_range
    client, readings_path = _client(tmp_path, parameters=params)
    append_reading(_reading("ph", 8.2, 1, unit=""), readings_path)
    resp = client.get("/tank/reef-a/parameter/ph")
    assert resp.status_code == 200
    data = _chart_json(resp.get_data(as_text=True))
    assert data["range"] == {"min": None, "max": None}
    assert data["points"][0]["in_range"] is True


def test_parameter_page_no_readings_still_renders_empty_contract(tmp_path):
    client, _ = _client(tmp_path)  # readings file never created
    resp = client.get("/tank/reef-a/parameter/salinity")
    assert resp.status_code == 200
    data = _chart_json(resp.get_data(as_text=True))
    assert data["points"] == []


def test_chart_series_only_includes_active_tank_and_parameter(tmp_path):
    tanks = [Tank(id="reef-a", label="Reef A"), Tank(id="frag", label="Frag")]
    client, readings_path = _client(tmp_path, tanks=tanks)
    append_reading(_reading("salinity", 35.0, 1, tank="reef-a"), readings_path)
    append_reading(_reading("salinity", 20.0, 2, tank="frag"), readings_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    data = _chart_json(body)
    # Only the active tank's reading appears (not frag's).
    assert len(data["points"]) == 1
    assert data["points"][0]["value"] == 35.0


# --------------------------------------------------------------------------- #
# E2E-ish: log a reading, then the chart contract reflects it correctly
# --------------------------------------------------------------------------- #
def test_logging_a_reading_updates_the_chart_contract(tmp_path):
    client, _ = _client(tmp_path)

    # Log an in-range reading via the add-reading form (PRG → 302).
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "35.0", "date": "2024-01-01"},
    )
    assert resp.status_code == 302

    # Log an out-of-range reading.
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "40.0", "date": "2024-01-02"},
    )

    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    data = _chart_json(body)
    assert [p["value"] for p in data["points"]] == [35.0, 40.0]
    assert [p["in_range"] for p in data["points"]] == [True, False]
