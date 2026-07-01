"""Tests for the parameter stats panel (task #8, spec §5.3).

Layering mirrors the rest of the suite:

  * Unit       — the Flask-free `_parameter_stats` summary math: latest value +
                 badge state, trend vs. previous reading, min/max/avg over the
                 visible history, and days-since-last (incl. the single-reading
                 and all-out-of-range edges, and the empty "no data yet" state).
  * Component  — the parameter page renders stat cards with the correct badge
                 state, and shows the light empty state when there are no
                 readings.
  * Integration — logging a reading via the form updates the rendered stats.

Tests inject a ready-made :class:`Config` (and a tmp readings path where reads
happen) so they never touch the repo's real data file.
"""

from __future__ import annotations

import datetime as dt

from fishy import _chart_series, _parameter_stats, create_app
from fishy.config import Config, Parameter, Tank, TargetRange
from fishy.storage import Reading, append_reading


def _point(day, value, in_range=True):
    return {"date": dt.date(2024, 1, day).isoformat(), "value": value, "in_range": in_range}


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
# Unit: latest value + badge state
# --------------------------------------------------------------------------- #
def test_stats_latest_is_the_newest_reading():
    points = [_point(1, 35.0), _point(2, 35.5), _point(3, 40.0, in_range=False)]
    stats = _parameter_stats(points, unit="ppt", today=dt.date(2024, 1, 3))

    assert stats["has_data"] is True
    assert stats["count"] == 3
    assert stats["unit"] == "ppt"
    assert stats["latest"]["value"] == 40.0
    assert stats["latest"]["date"] == "2024-01-03"
    assert stats["latest"]["in_range"] is False


def test_stats_latest_in_range_badge_reflects_point():
    points = [_point(1, 40.0, in_range=False), _point(2, 35.0, in_range=True)]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 2))
    assert stats["latest"]["in_range"] is True


# --------------------------------------------------------------------------- #
# Unit: trend vs. previous reading(s)
# --------------------------------------------------------------------------- #
def test_stats_trend_up_when_latest_rises():
    points = [_point(1, 34.0), _point(2, 35.0)]
    assert _parameter_stats(points, today=dt.date(2024, 1, 2))["trend"] == "up"


def test_stats_trend_down_when_latest_falls():
    points = [_point(1, 36.0), _point(2, 35.0)]
    assert _parameter_stats(points, today=dt.date(2024, 1, 2))["trend"] == "down"


def test_stats_trend_flat_when_latest_equals_previous():
    points = [_point(1, 35.0), _point(2, 35.0)]
    assert _parameter_stats(points, today=dt.date(2024, 1, 2))["trend"] == "flat"


def test_stats_trend_compares_only_the_last_two_points():
    # An earlier dip should not affect the trend: only latest vs. previous.
    points = [_point(1, 35.0), _point(2, 30.0), _point(3, 36.0)]
    assert _parameter_stats(points, today=dt.date(2024, 1, 3))["trend"] == "up"


# --------------------------------------------------------------------------- #
# Unit: min / max / average over the visible history
# --------------------------------------------------------------------------- #
def test_stats_min_max_avg_over_history():
    points = [_point(1, 34.0), _point(2, 35.0), _point(3, 36.0)]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 3))
    assert stats["min"] == 34.0
    assert stats["max"] == 36.0
    assert stats["avg"] == 35.0
    # Displays reuse storage's formatter (whole numbers stay compact).
    assert stats["min_display"] == "34"
    assert stats["max_display"] == "36"
    assert stats["avg_display"] == "35"


def test_stats_avg_is_rounded_for_display():
    points = [_point(1, 34.0), _point(2, 35.0)]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 2))
    assert stats["avg"] == 34.5
    assert stats["avg_display"] == "34.5"


# --------------------------------------------------------------------------- #
# Unit: days since last reading
# --------------------------------------------------------------------------- #
def test_stats_days_since_last_counts_from_latest_date():
    points = [_point(1, 35.0), _point(10, 35.0)]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 15))
    assert stats["days_since_last"] == 5


def test_stats_days_since_last_is_zero_today():
    points = [_point(3, 35.0)]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 3))
    assert stats["days_since_last"] == 0


def test_stats_days_since_last_never_negative():
    # A back-dated future reading should clamp to 0 rather than go negative.
    points = [_point(20, 35.0)]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 10))
    assert stats["days_since_last"] == 0


# --------------------------------------------------------------------------- #
# Unit: edge cases
# --------------------------------------------------------------------------- #
def test_stats_single_reading_has_no_trend_and_flat_min_max_avg():
    stats = _parameter_stats([_point(1, 35.0)], today=dt.date(2024, 1, 1))
    assert stats["trend"] is None
    assert stats["min"] == stats["max"] == stats["avg"] == 35.0
    assert stats["latest"]["value"] == 35.0


def test_stats_all_out_of_range_still_correct():
    points = [
        _point(1, 40.0, in_range=False),
        _point(2, 41.0, in_range=False),
        _point(3, 42.0, in_range=False),
    ]
    stats = _parameter_stats(points, today=dt.date(2024, 1, 3))
    assert stats["latest"]["in_range"] is False
    assert stats["min"] == 40.0
    assert stats["max"] == 42.0
    assert stats["avg"] == 41.0
    assert stats["trend"] == "up"


def test_stats_empty_history_degrades_gracefully():
    stats = _parameter_stats([], unit="ppt")
    assert stats["has_data"] is False
    assert stats["count"] == 0
    assert stats["latest"] is None
    assert stats["trend"] is None
    assert stats["min"] is None
    assert stats["max"] is None
    assert stats["avg"] is None
    assert stats["days_since_last"] is None


def test_stats_defaults_today_to_current_date():
    # Without an injected `today`, days-since-last is computed from date.today().
    today = dt.date.today()
    points = [{"date": today.isoformat(), "value": 35.0, "in_range": True}]
    assert _parameter_stats(points)["days_since_last"] == 0


def test_stats_consumes_chart_series_points():
    # The stats helper is designed to eat _chart_series' output directly.
    param = Parameter(
        id="salinity",
        display_name="Salinity",
        units=("ppt",),
        target_range=TargetRange(min=34.0, max=36.0),
    )
    readings = [
        _reading("salinity", 40.0, 3),  # out of range, latest
        _reading("salinity", 35.0, 1),
        _reading("salinity", 35.5, 2),
    ]
    data = _chart_series(readings, param, "reef-a")
    stats = _parameter_stats(data["points"], unit=data["unit"], today=dt.date(2024, 1, 3))
    assert stats["latest"]["value"] == 40.0
    assert stats["latest"]["in_range"] is False
    assert stats["trend"] == "up"
    assert stats["min"] == 35.0
    assert stats["max"] == 40.0


# --------------------------------------------------------------------------- #
# Component: stat cards render with the correct badge state
# --------------------------------------------------------------------------- #
def test_page_renders_stat_cards_with_in_range_badge(tmp_path):
    client, path = _client(tmp_path)
    append_reading(_reading("salinity", 34.0, 1), path)
    append_reading(_reading("salinity", 35.0, 2), path)

    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert 'class="reef-stats"' in body
    assert "reef-stat--latest" in body
    assert "reef-badge--in" in body
    assert "reef-badge--out" not in body
    # Latest value + min/max/avg surfaced.
    assert "35" in body
    assert "Min / Max / Avg" in body


def test_page_renders_out_of_range_badge(tmp_path):
    client, path = _client(tmp_path)
    append_reading(_reading("salinity", 40.0, 1), path)  # above the 34-36 band

    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-badge--out" in body
    assert "reef-badge--in" not in body


def test_page_single_reading_shows_no_trend(tmp_path):
    client, path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1), path)

    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "Single reading" in body


def test_page_empty_history_shows_no_data_state(tmp_path):
    client, _path = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-stats__empty" in body
    assert "No data yet" in body
    assert "reef-stat--latest" not in body


# --------------------------------------------------------------------------- #
# Integration: stats update after a new reading
# --------------------------------------------------------------------------- #
def test_stats_update_after_logging_a_reading(tmp_path):
    client, _path = _client(tmp_path)

    # Empty → no-data state.
    before = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "No data yet" in before

    # Log a first (in-range) reading via the form → stats appear.
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "35", "date": "2024-01-01"},
        follow_redirects=True,
    )
    after_one = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "No data yet" not in after_one
    assert "reef-badge--in" in after_one
    assert "Single reading" in after_one

    # Log a second, higher (out-of-range) reading → latest badge + trend update.
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "40", "date": "2024-01-02"},
        follow_redirects=True,
    )
    after_two = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-badge--out" in after_two
    assert "Single reading" not in after_two
    assert "Rising" in after_two
