"""Tests for the combined Aggregate tab (task #12, spec §5.7).

Layering mirrors the rest of the suite:

  * Unit       — the Flask-free helpers: `_normalize` (min-max scaling that keeps
                 differently-scaled series legible), `_aggregate_series` (adds a
                 normalized `norm` coordinate per point) and `_aggregate_cards`
                 (reuses the `_parameter_stats` contract for the cards row).
  * Component  — the aggregate page renders one card per parameter, embeds the
                 overlay JSON list (all series + range highlighting), loads
                 Plotly + aggregate.js, marks the Aggregate tab active, and keeps
                 the #13 history-table seam.
  * Integration — log readings via the form, then GET /aggregate and confirm the
                 cards + overlay reflect the latest readings and range flags,
                 scoped to the active tank only.

Tests inject a ready-made :class:`Config` (and a tmp readings path where reads
happen) so they never touch the repo's real data file.
"""

from __future__ import annotations

import datetime as dt
import json

from fishy import (
    _aggregate_cards,
    _aggregate_series,
    _chart_series,
    _normalize,
    create_app,
)
from fishy.config import Config, Parameter, Tank, TargetRange
from fishy.storage import Reading, append_reading


def _reading(param, value, day, tank="reef-a", unit=""):
    return Reading(
        tank=tank,
        parameter=param,
        date=dt.date(2024, 1, day),
        value=value,
        unit=unit,
    )


def _default_params():
    return [
        Parameter(
            id="salinity",
            display_name="Salinity",
            units=("ppt",),
            target_range=TargetRange(min=34.0, max=36.0),
        ),
        Parameter(
            id="calcium",
            display_name="Calcium",
            units=("ppm",),
            target_range=TargetRange(min=400.0, max=450.0),
        ),
        Parameter(id="ph", display_name="pH"),  # no range
    ]


def _client(tmp_path, *, tanks=None, parameters=None):
    tanks = tanks or [Tank(id="reef-a", label="Reef A")]
    parameters = parameters if parameters is not None else _default_params()
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


def _overlay_json(body):
    """Extract the inline overlay JSON list from a rendered aggregate page."""
    marker = '<script type="application/json" class="reef-aggregate-data">'
    start = body.index(marker) + len(marker)
    end = body.index("</script>", start)
    return json.loads(body[start:end])


# --------------------------------------------------------------------------- #
# Unit: _normalize — the key "comparably scaled" helper
# --------------------------------------------------------------------------- #
def test_normalize_empty_returns_empty():
    assert _normalize([]) == []


def test_normalize_single_value_maps_to_mid():
    # A lone value has no span; a flat line through the middle stays legible.
    assert _normalize([1.026]) == [0.5]


def test_normalize_all_equal_maps_to_mid_no_divide_by_zero():
    assert _normalize([420.0, 420.0, 420.0]) == [0.5, 0.5, 0.5]


def test_normalize_min_max_scaled_to_unit_interval():
    out = _normalize([10.0, 20.0, 30.0])
    assert out == [0.0, 0.5, 1.0]


def test_normalize_makes_differing_scales_comparable():
    # Specific-gravity-scale and calcium-scale series both land on 0..1, so the
    # overlay is legible regardless of raw magnitude.
    sg = _normalize([1.020, 1.026])
    ca = _normalize([400.0, 450.0])
    assert sg == [0.0, 1.0]
    assert ca == [0.0, 1.0]


# --------------------------------------------------------------------------- #
# Unit: _aggregate_series — adds `norm` per point, per series, no mutation
# --------------------------------------------------------------------------- #
def test_aggregate_series_adds_norm_per_point():
    param = Parameter(
        id="calcium",
        display_name="Calcium",
        units=("ppm",),
        target_range=TargetRange(min=400.0, max=450.0),
    )
    series = _chart_series(
        [_reading("calcium", 400.0, 1), _reading("calcium", 450.0, 2)],
        param,
        "reef-a",
    )
    out = _aggregate_series([series])
    norms = [p["norm"] for p in out[0]["points"]]
    assert norms == [0.0, 1.0]
    # Raw value + in_range are preserved for hover + highlighting.
    assert [p["value"] for p in out[0]["points"]] == [400.0, 450.0]
    assert all("in_range" in p for p in out[0]["points"])


def test_aggregate_series_normalizes_each_series_independently():
    p_sal = Parameter(id="salinity", display_name="Salinity", units=("ppt",))
    p_ca = Parameter(id="calcium", display_name="Calcium", units=("ppm",))
    s_sal = _chart_series(
        [_reading("salinity", 34.0, 1), _reading("salinity", 36.0, 2)], p_sal, "reef-a"
    )
    s_ca = _chart_series(
        [_reading("calcium", 400.0, 1), _reading("calcium", 500.0, 2)], p_ca, "reef-a"
    )
    out = _aggregate_series([s_sal, s_ca])
    assert [p["norm"] for p in out[0]["points"]] == [0.0, 1.0]
    assert [p["norm"] for p in out[1]["points"]] == [0.0, 1.0]


def test_aggregate_series_does_not_mutate_input():
    param = Parameter(id="salinity", display_name="Salinity")
    series = _chart_series([_reading("salinity", 34.0, 1)], param, "reef-a")
    _aggregate_series([series])
    assert "norm" not in series["points"][0]


def test_aggregate_series_empty_points_stays_empty():
    param = Parameter(id="salinity", display_name="Salinity")
    series = _chart_series([], param, "reef-a")
    out = _aggregate_series([series])
    assert out[0]["points"] == []


# --------------------------------------------------------------------------- #
# Unit: _aggregate_cards — reuses the stats contract, one card per parameter
# --------------------------------------------------------------------------- #
def test_aggregate_cards_one_per_parameter_with_stats():
    params = _default_params()
    series_list = [_chart_series([], p, "reef-a") for p in params]
    cards = _aggregate_cards(series_list)
    assert [c["parameter_id"] for c in cards] == ["salinity", "calcium", "ph"]
    # No readings → each card reports has_data False (a light "no data" card).
    assert all(c["stats"]["has_data"] is False for c in cards)


def test_aggregate_cards_reflect_latest_and_in_range_badge():
    param = Parameter(
        id="salinity",
        display_name="Salinity",
        units=("ppt",),
        target_range=TargetRange(min=34.0, max=36.0),
    )
    series = _chart_series(
        [_reading("salinity", 35.0, 1), _reading("salinity", 40.0, 2)], param, "reef-a"
    )
    (card,) = _aggregate_cards([series])
    assert card["stats"]["latest"]["value"] == 40.0
    assert card["stats"]["latest"]["in_range"] is False  # 40 > 36
    assert card["stats"]["trend"] == "up"
    assert card["unit"] == "ppt"


def test_aggregate_cards_no_range_never_flags_out():
    param = Parameter(id="ph", display_name="pH")  # no range
    series = _chart_series([_reading("ph", 99.0, 1)], param, "reef-a")
    (card,) = _aggregate_cards([series])
    assert card["stats"]["latest"]["in_range"] is True
    assert card["range"] == {"min": None, "max": None}


# --------------------------------------------------------------------------- #
# Component: the aggregate page renders the tab, cards, overlay, and assets
# --------------------------------------------------------------------------- #
def test_aggregate_page_loads_plotly_and_aggregate_js(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "cdn.plot.ly" in body
    assert "js/aggregate.js" in body


def test_aggregate_tab_marked_active(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert 'reef-tabs__link--aggregate is-active' in body
    assert 'aria-current="page"' in body


def test_aggregate_page_renders_a_card_per_parameter(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1, unit="ppt"), readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    # One card per configured parameter (3 default params).
    assert body.count("reef-aggregate-card") >= 3
    assert "Salinity" in body
    assert "Calcium" in body
    assert "pH" in body


def test_aggregate_overlay_embeds_all_series(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1, unit="ppt"), readings_path)
    append_reading(_reading("calcium", 420.0, 1, unit="ppm"), readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    overlay = _overlay_json(body)
    ids = [s["parameter_id"] for s in overlay]
    assert ids == ["salinity", "calcium", "ph"]
    # Each plotted point carries a normalized coordinate for the shared axis.
    sal = next(s for s in overlay if s["parameter_id"] == "salinity")
    assert all("norm" in p for p in sal["points"])
    # Legend clarity: display name + unit are present in the contract.
    assert sal["display_name"] == "Salinity"
    assert sal["unit"] == "ppt"


def test_aggregate_overlay_highlights_out_of_range(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 40.0, 1, unit="ppt"), readings_path)  # > 36
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    overlay = _overlay_json(body)
    sal = next(s for s in overlay if s["parameter_id"] == "salinity")
    assert sal["points"][0]["in_range"] is False


def test_aggregate_history_seam_present_for_task_13(tmp_path):
    # Task #13 has since filled this seam with the full reading-history table;
    # the seam region remains and now renders the history table (see
    # tests/test_history.py for its behaviour).
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1, unit="ppt"), readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "reef-aggregate__history" in body
    assert "reef-history__table" in body


def test_aggregate_empty_state_when_no_readings(tmp_path):
    client, _ = _client(tmp_path)  # readings file never created
    resp = client.get("/tank/reef-a/aggregate")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "reef-aggregate__empty" in body


def test_aggregate_unknown_tank_404(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/tank/nope/aggregate").status_code == 404


def test_parameter_tab_links_to_aggregate_route(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1, unit="ppt"), readings_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    # The Aggregate tab now points at the real route, not the "#aggregate" slot.
    assert "/tank/reef-a/aggregate" in body
    assert 'href="#aggregate"' not in body


# --------------------------------------------------------------------------- #
# Integration: log readings, then the aggregate reflects them (scoped to tank)
# --------------------------------------------------------------------------- #
def test_aggregate_reflects_logged_readings_and_is_tank_scoped(tmp_path):
    tanks = [Tank(id="reef-a", label="Reef A"), Tank(id="frag", label="Frag")]
    client, _ = _client(tmp_path, tanks=tanks)

    # Log via the add-reading form for reef-a.
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "35.0", "date": "2024-01-01"},
    )
    # Log a DIFFERENT reading for frag (should NOT leak into reef-a's aggregate).
    client.post(
        "/tank/frag/parameter/salinity/reading",
        data={"value": "20.0", "date": "2024-01-01"},
    )

    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    overlay = _overlay_json(body)
    sal = next(s for s in overlay if s["parameter_id"] == "salinity")
    # Only reef-a's reading appears (not frag's 20.0).
    assert [p["value"] for p in sal["points"]] == [35.0]
