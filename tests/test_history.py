"""Tests for the Aggregate tab's full reading-history table (task #13, spec §5.7).

Layering mirrors the rest of the suite:

  * Unit       — the Flask-free `_history_rows` helper: most-recent-first
                 ordering (stable for same-date), out-of-range flagging via the
                 same per-tank ranges the charts use, tank scoping, tidy
                 value display, and graceful handling of archived/unknown
                 parameters (raw id + `is_archived`, never flagged/crashing).
  * Component  — the aggregate page renders one row per reading with the right
                 columns, highlights out-of-range rows, and tags archived rows.
  * Integration — log readings via the form, then GET /aggregate and confirm the
                 new reading shows up as its own row; a long history still
                 renders every row, newest-first.

Tests inject a ready-made :class:`Config` and a tmp readings path so they never
touch the repo's real data file.
"""

from __future__ import annotations

import datetime as dt

from fishy import _history_rows, create_app
from fishy.config import Config, Parameter, Tank, TargetRange
from fishy.storage import Reading, append_reading


def _reading(param, value, day, tank="reef-a", unit="", note=""):
    return Reading(
        tank=tank,
        parameter=param,
        date=dt.date(2024, 1, day),
        value=value,
        unit=unit,
        note=note,
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


def _config(*, tanks=None, parameters=None):
    tanks = tanks or [Tank(id="reef-a", label="Reef A")]
    parameters = parameters if parameters is not None else _default_params()
    return Config(tanks=tanks, parameters=parameters)


def _client(tmp_path, *, tanks=None, parameters=None):
    config = _config(tanks=tanks, parameters=parameters)
    readings_path = tmp_path / "readings.csv"
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_READINGS_PATH": readings_path,
        }
    )
    return app.test_client(), readings_path


def _history_section(body):
    """Slice out just the history-table section (dates also appear in the
    overlay JSON, so whole-body index checks would be ambiguous)."""
    start = body.index('class="reef-aggregate__history"')
    end = body.index("</section>", start)
    return body[start:end]


# --------------------------------------------------------------------------- #
# Unit: _history_rows — one row per reading, tidy fields
# --------------------------------------------------------------------------- #
def test_history_rows_one_row_per_reading():
    config = _config()
    readings = [
        _reading("salinity", 35.0, 1),
        _reading("calcium", 420.0, 2),
        _reading("salinity", 34.5, 3),
    ]
    rows = _history_rows(readings, config, "reef-a")
    assert len(rows) == 3


def test_history_rows_fields_populated():
    config = _config()
    rows = _history_rows(
        [_reading("salinity", 35.0, 5, unit="ppt", note="water change")],
        config,
        "reef-a",
    )
    (row,) = rows
    assert row == {
        "date": "2024-01-05",
        "parameter_id": "salinity",
        "parameter_label": "Salinity",
        "value": 35.0,
        "value_display": "35",  # tidy, not 35.0
        "unit": "ppt",
        "note": "water change",
        "in_range": True,
        "is_archived": False,
    }


# --------------------------------------------------------------------------- #
# Unit: ordering — most-recent-first, stable for same-date
# --------------------------------------------------------------------------- #
def test_history_rows_most_recent_first():
    config = _config()
    readings = [
        _reading("salinity", 35.0, 1),
        _reading("salinity", 34.0, 10),
        _reading("salinity", 36.0, 5),
    ]
    rows = _history_rows(readings, config, "reef-a")
    assert [r["date"] for r in rows] == ["2024-01-10", "2024-01-05", "2024-01-01"]


def test_history_rows_same_date_readings_each_appear_stable_order():
    config = _config()
    # Three readings on the same day (append order preserved among equal dates).
    readings = [
        _reading("salinity", 35.0, 4, note="morning"),
        _reading("calcium", 420.0, 4, note="noon"),
        _reading("ph", 8.1, 4, note="evening"),
    ]
    rows = _history_rows(readings, config, "reef-a")
    assert len(rows) == 3
    assert all(r["date"] == "2024-01-04" for r in rows)
    # Stable: original relative order preserved for the same date.
    assert [r["note"] for r in rows] == ["morning", "noon", "evening"]


# --------------------------------------------------------------------------- #
# Unit: out-of-range flagging via the same per-tank ranges as the charts
# --------------------------------------------------------------------------- #
def test_history_rows_flags_out_of_range():
    config = _config()
    rows = _history_rows(
        [
            _reading("salinity", 35.0, 1),  # in 34..36
            _reading("salinity", 40.0, 2),  # out (>36)
            _reading("calcium", 380.0, 3),  # out (<400)
        ],
        config,
        "reef-a",
    )
    by_value = {r["value"]: r["in_range"] for r in rows}
    assert by_value[35.0] is True
    assert by_value[40.0] is False
    assert by_value[380.0] is False


def test_history_rows_no_range_parameter_never_flagged():
    config = _config()
    # pH has no configured range → nothing is ever out-of-range.
    rows = _history_rows(
        [_reading("ph", 999.0, 1), _reading("ph", 0.0, 2)], config, "reef-a"
    )
    assert all(r["in_range"] is True for r in rows)
    assert all(r["is_archived"] is False for r in rows)


def test_history_rows_honors_per_tank_range_override():
    # frag-tank overrides alkalinity to a tighter band; reef-a uses the default.
    params = [
        Parameter(
            id="alkalinity",
            display_name="Alkalinity",
            units=("dKH",),
            target_range=TargetRange(min=7.5, max=9.5),
            overrides={"frag-tank": TargetRange(min=8.2, max=8.8)},
        )
    ]
    config = _config(
        tanks=[Tank(id="reef-a", label="Reef A"), Tank(id="frag-tank", label="Frag")],
        parameters=params,
    )
    # 9.0 is in-range for reef-a (7.5..9.5) but out-of-range for frag-tank (8.2..8.8).
    reef_rows = _history_rows(
        [_reading("alkalinity", 9.0, 1, tank="reef-a")], config, "reef-a"
    )
    frag_rows = _history_rows(
        [_reading("alkalinity", 9.0, 1, tank="frag-tank")], config, "frag-tank"
    )
    assert reef_rows[0]["in_range"] is True
    assert frag_rows[0]["in_range"] is False


# --------------------------------------------------------------------------- #
# Unit: tank scoping — only the active tank's readings
# --------------------------------------------------------------------------- #
def test_history_rows_scoped_to_tank():
    config = _config(
        tanks=[Tank(id="reef-a", label="Reef A"), Tank(id="reef-b", label="Reef B")]
    )
    readings = [
        _reading("salinity", 35.0, 1, tank="reef-a"),
        _reading("salinity", 35.0, 2, tank="reef-b"),
    ]
    rows = _history_rows(readings, config, "reef-a")
    assert len(rows) == 1
    assert rows[0]["date"] == "2024-01-01"


def test_history_rows_empty_when_no_readings():
    assert _history_rows([], _config(), "reef-a") == []


# --------------------------------------------------------------------------- #
# Unit / Error handling: archived / unknown parameters render, never crash
# --------------------------------------------------------------------------- #
def test_history_rows_archived_parameter_renders_without_crashing():
    config = _config()  # no "nitrate" parameter configured
    rows = _history_rows(
        [_reading("nitrate", 5.0, 1, unit="ppm", note="legacy")], config, "reef-a"
    )
    (row,) = rows
    assert row["is_archived"] is True
    assert row["parameter_id"] == "nitrate"
    assert row["parameter_label"] == "nitrate"  # raw id shown
    assert row["in_range"] is True  # no range → never flagged
    assert row["value_display"] == "5"


def test_history_rows_mixed_known_and_archived():
    config = _config()
    rows = _history_rows(
        [
            _reading("salinity", 35.0, 1),
            _reading("nitrate", 10.0, 2),
        ],
        config,
        "reef-a",
    )
    labels = {r["parameter_id"]: r["is_archived"] for r in rows}
    assert labels["salinity"] is False
    assert labels["nitrate"] is True


# --------------------------------------------------------------------------- #
# Component: the aggregate page renders history rows + highlighting
# --------------------------------------------------------------------------- #
def test_aggregate_page_renders_history_rows(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1, unit="ppt", note="ok"), readings_path)
    append_reading(_reading("calcium", 420.0, 2, unit="ppm"), readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "reef-aggregate__history" in body
    assert "reef-history__table" in body
    # Column headers present.
    for col in ("Date", "Parameter", "Value", "Note"):
        assert col in body
    # Both readings appear as rows.
    assert "Salinity" in body
    assert "Calcium" in body
    assert "2024-01-01" in body
    assert "2024-01-02" in body


def test_aggregate_page_highlights_out_of_range_history_row(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 40.0, 3), readings_path)  # out (>36)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "reef-history__row--out" in body
    assert "Out of range" in body


def test_aggregate_page_history_in_range_not_highlighted(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 3), readings_path)  # in range
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    # A single in-range reading should not carry the out-of-range row class.
    assert "reef-history__row--out" not in body


def test_aggregate_page_history_orders_newest_first(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(_reading("salinity", 35.0, 1), readings_path)
    append_reading(_reading("salinity", 34.5, 10), readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    section = _history_section(body)
    assert section.index("2024-01-10") < section.index("2024-01-01")


def test_aggregate_page_history_tags_archived_parameter(tmp_path):
    client, readings_path = _client(tmp_path)
    # A reading for a parameter that is NOT configured must still render.
    append_reading(_reading("nitrate", 5.0, 1, unit="ppm"), readings_path)
    resp = client.get("/tank/reef-a/aggregate")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "reef-history__archived" in body
    assert "nitrate" in body


# --------------------------------------------------------------------------- #
# Integration: new reading appears; long history stays usable
# --------------------------------------------------------------------------- #
def test_new_reading_appears_in_history(tmp_path):
    client, _ = _client(tmp_path)
    # Log via the real POST form, then confirm it shows in the aggregate history.
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "35.2", "date": "2024-02-01", "note": "topped off"},
    )
    assert resp.status_code == 302
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "2024-02-01" in body
    assert "35.2" in body
    assert "topped off" in body


def test_long_history_renders_every_row(tmp_path):
    client, readings_path = _client(tmp_path)
    for day in range(1, 29):
        append_reading(_reading("salinity", 34.0 + (day % 3), day), readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    section = _history_section(body)
    # Every one of the 28 readings is present as its own row, newest first.
    row_count = section.count("reef-history__row ") + section.count('reef-history__row"')
    assert row_count == 28
    # Newest (day 28) appears before oldest (day 1).
    assert section.index("2024-01-28") < section.index("2024-01-01")
