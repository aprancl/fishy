"""Tests for the per-parameter add-reading form (task #5, spec §5.2).

Layering mirrors the rest of the suite:

  * Component   — form renders scoped to ONE parameter; value validation
                  (numeric required, optional note); the date defaults to today
                  but is an editable/overridable field (back-dating).
  * Integration — a valid submit appends exactly one correct row and the view
                  refreshes to include it; invalid input writes nothing.
  * E2E-ish     — log a reading and see it appear on the parameter page.

The readings CSV path is injected via ``FISHY_READINGS_PATH`` so tests write to
a pytest tmp file and never touch the repo's real ``data/readings.csv``.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from fishy import create_app
from fishy.config import Config, Parameter, Tank
from fishy.storage import load_readings


def _make_client(tmp_path, *, tanks=None, parameters=None):
    """Build a test client with an injected config and a tmp readings path."""
    tanks = tanks or [Tank(id="reef-a", label="Reef A")]
    parameters = parameters or [
        Parameter(id="salinity", display_name="Salinity", units=("ppt",), builtin=True)
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
# Component: the form is scoped to a single parameter, not a grid
# --------------------------------------------------------------------------- #
def test_form_is_scoped_to_single_parameter(tmp_path):
    client, _ = _make_client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "Add Salinity reading" in body
    assert 'name="value"' in body
    assert 'name="note"' in body
    # The form posts to the per-parameter endpoint, not a multi-parameter grid.
    assert "/tank/reef-a/parameter/salinity/reading" in body
    assert 'data-parameter-id="salinity"' in body


def test_form_records_parameter_unit_hint(tmp_path):
    client, _ = _make_client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "ppt" in body


def test_date_defaults_to_today_and_is_editable(tmp_path):
    client, _ = _make_client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    today = _dt.date.today().isoformat()
    # Editable date input pre-filled with today (auto-captured, overridable).
    assert 'type="date"' in body
    assert f'value="{today}"' in body


# --------------------------------------------------------------------------- #
# Integration: a valid submit appends exactly one correct row
# --------------------------------------------------------------------------- #
def test_submit_appends_exactly_one_correct_row(tmp_path):
    client, readings_path = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "8.2", "note": "morning check"},
    )
    # Post/Redirect/Get: a successful save redirects back to the GET page.
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/tank/reef-a/parameter/salinity")

    readings = load_readings(readings_path, emit_warnings=False).readings
    assert len(readings) == 1
    r = readings[0]
    assert r.tank == "reef-a"
    assert r.parameter == "salinity"
    assert r.value == 8.2
    assert r.unit == "ppt"
    assert r.note == "morning check"
    assert r.date == _dt.date.today()


def test_view_refreshes_to_include_new_reading(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "8.2", "note": "morning check"},
    )
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "8.2" in body
    assert "morning check" in body


def test_backdated_reading_uses_overridden_date(tmp_path):
    client, readings_path = _make_client(tmp_path)
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "9", "date": "2020-01-15"},
    )
    readings = load_readings(readings_path, emit_warnings=False).readings
    assert len(readings) == 1
    assert readings[0].date == _dt.date(2020, 1, 15)


def test_note_is_optional(tmp_path):
    client, readings_path = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "35"},
    )
    assert resp.status_code == 302
    readings = load_readings(readings_path, emit_warnings=False).readings
    assert len(readings) == 1
    assert readings[0].note == ""


def test_partial_logging_one_param_never_requires_others(tmp_path):
    """Logging salinity must not require any other parameter's value."""
    params = [
        Parameter(id="salinity", display_name="Salinity", units=("ppt",)),
        Parameter(id="alkalinity", display_name="Alkalinity", units=("dKH",)),
    ]
    client, readings_path = _make_client(tmp_path, parameters=params)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "35"},
    )
    assert resp.status_code == 302
    readings = load_readings(readings_path, emit_warnings=False).readings
    assert len(readings) == 1
    assert readings[0].parameter == "salinity"


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_multiple_same_day_readings_are_all_stored(tmp_path):
    client, readings_path = _make_client(tmp_path)
    for value in ("8.1", "8.3", "8.2"):
        client.post(
            "/tank/reef-a/parameter/salinity/reading",
            data={"value": value},
        )
    readings = load_readings(readings_path, emit_warnings=False).readings
    assert len(readings) == 3
    assert {r.value for r in readings} == {8.1, 8.3, 8.2}
    # And all three are shown on the refreshed view.
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    for value in ("8.1", "8.3", "8.2"):
        assert value in body


def test_note_with_commas_quotes_newlines_roundtrips(tmp_path):
    client, readings_path = _make_client(tmp_path)
    tricky = 'dosed 2ml, "topped off"\nchecked again'
    client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "8.2", "note": tricky},
    )
    readings = load_readings(readings_path, emit_warnings=False).readings
    assert len(readings) == 1
    assert readings[0].note == tricky


# --------------------------------------------------------------------------- #
# Error handling: bad value is rejected with a friendly message, nothing written
# --------------------------------------------------------------------------- #
def test_non_numeric_value_is_rejected_and_nothing_written(tmp_path):
    client, readings_path = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "not-a-number", "note": "oops"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "number" in body.lower()
    # Nothing is written on a rejected submit.
    assert load_readings(readings_path, emit_warnings=False).readings == []


def test_empty_value_is_rejected_and_nothing_written(tmp_path):
    client, readings_path = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "", "note": "still nothing"},
    )
    assert resp.status_code == 400
    assert "value" in resp.get_data(as_text=True).lower()
    assert load_readings(readings_path, emit_warnings=False).readings == []


def test_rejected_submit_repopulates_the_note(tmp_path):
    client, _ = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "bad", "note": "keep me"},
    )
    assert "keep me" in resp.get_data(as_text=True)


def test_invalid_date_is_rejected_and_nothing_written(tmp_path):
    client, readings_path = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/salinity/reading",
        data={"value": "8.2", "date": "13/13/2020"},
    )
    assert resp.status_code == 400
    assert load_readings(readings_path, emit_warnings=False).readings == []


# --------------------------------------------------------------------------- #
# 404s: unknown tank or parameter
# --------------------------------------------------------------------------- #
def test_unknown_tank_returns_404(tmp_path):
    client, _ = _make_client(tmp_path)
    assert client.get("/tank/nope/parameter/salinity").status_code == 404


def test_unknown_parameter_returns_404(tmp_path):
    client, _ = _make_client(tmp_path)
    assert client.get("/tank/reef-a/parameter/nope").status_code == 404


def test_post_to_unknown_parameter_returns_404(tmp_path):
    client, readings_path = _make_client(tmp_path)
    resp = client.post(
        "/tank/reef-a/parameter/nope/reading",
        data={"value": "8.2"},
    )
    assert resp.status_code == 404
    assert load_readings(readings_path, emit_warnings=False).readings == []
