"""Tests for friendly empty & edge states (task #15, spec §5.8 / §9.4).

This ties together the shelf (#4), parameter chart/stats (#7/#8), aggregate
cards + history (#12/#13) and the CSV layer's malformed-row tolerance (#2). It
verifies the app degrades gracefully — and *actionably* — across every empty or
malformed scenario, and that the NEW malformed-CSV notice surfaces skipped rows
without dropping the valid ones.

Layering:
  * Component   — each empty/edge state renders the right copy + affordance
                  (add a tank in config / log your first reading / edit content).
  * Integration — a malformed data file surfaces the non-fatal notice on the
                  tank, parameter and aggregate pages while valid rows still load.
  * E2E-ish     — a fresh install (no tanks, then a tank with no readings) walks
                  through without a single unhandled crash.

Tests inject a ready-made Config and point storage at a tmp readings path, so
they never touch the repo's real data file.
"""

from __future__ import annotations

import datetime as dt

from fishy import create_app
from fishy.config import (
    Config,
    Parameter,
    Tank,
    TargetRange,
)
from fishy.storage import COLUMNS, Reading, append_reading


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _params():
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
    ]


def _client(tmp_path, *, tanks=None, parameters=None):
    tanks = tanks if tanks is not None else [Tank(id="reef-a", label="Reef A")]
    parameters = parameters if parameters is not None else _params()
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


def _write_csv(path, data_rows):
    """Write a readings CSV with the canonical header + raw data rows.

    ``data_rows`` is a list of full-row strings (already comma-joined) so tests
    can inject deliberately malformed rows the ``csv`` reader will hand to
    ``Reading.from_row``.
    """
    header = ",".join(COLUMNS)
    body = "\n".join(data_rows)
    path.write_text(header + "\n" + body + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Functional: no-tanks state explains how to add a tank in config
# --------------------------------------------------------------------------- #
def test_no_tanks_state_explains_config(tmp_path):
    client, _ = _client(tmp_path, tanks=[])
    body = client.get("/").get_data(as_text=True)
    assert "No tanks configured" in body
    # Actionable: points at the config file and shows a copy-paste snippet.
    assert "config/fishy.toml" in body
    assert "[[tanks]]" in body
    assert "reef-empty" in body


# --------------------------------------------------------------------------- #
# Functional: no-readings prompts logging the first reading (parameter tabs)
# --------------------------------------------------------------------------- #
def test_parameter_no_readings_prompts_first_reading(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    # Stats degrade to a "no data" prompt rather than a broken chart.
    assert "reef-stats__empty" in body
    # Both the stats note and the readings table prompt logging a first reading.
    assert body.lower().count("first") >= 1
    assert "reef-empty" in body
    # The add-reading form is present so the prompt is actionable on-page.
    assert 'name="value"' in body


def test_parameter_no_readings_uses_empty_marker(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/parameter/calcium").get_data(as_text=True)
    assert "No readings logged yet" in body
    assert "reef-empty" in body


# --------------------------------------------------------------------------- #
# Functional: aggregate no-readings prompts logging the first reading
# --------------------------------------------------------------------------- #
def test_aggregate_no_readings_prompts_first_reading(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "reef-aggregate__empty" in body
    assert "reef-empty" in body
    assert "log your first reading" in body


# --------------------------------------------------------------------------- #
# Functional: malformed CSV rows surface a clear, non-fatal notice; valid data
# still displays. Checked on the parameter, tank AND aggregate pages.
# --------------------------------------------------------------------------- #
def _malformed_file(path):
    """A CSV with one valid salinity row + two malformed rows."""
    _write_csv(
        path,
        [
            "reef-a,salinity,2024-01-01,35,ppt,good row",
            "reef-a,salinity,2024-01-02,not-a-number,ppt,bad value",
            "reef-a,calcium,nope,420,ppm,bad date",
        ],
    )


def test_malformed_rows_surface_notice_on_parameter_page(tmp_path):
    client, readings_path = _client(tmp_path)
    _malformed_file(readings_path)
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    # Non-fatal notice present, identifying the skipped rows.
    assert "reef-notice" in body
    assert "skipped" in body
    assert "2 rows" in body
    # Valid row still loaded + displayed (value 35 in the readings table).
    assert "2024-01-01" in body
    assert "good row" in body


def test_malformed_rows_surface_notice_on_tank_page(tmp_path):
    client, readings_path = _client(tmp_path)
    _malformed_file(readings_path)
    body = client.get("/tank/reef-a").get_data(as_text=True)
    assert "reef-notice" in body
    assert "skipped" in body


def test_malformed_rows_surface_notice_on_aggregate_page(tmp_path):
    client, readings_path = _client(tmp_path)
    _malformed_file(readings_path)
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "reef-notice" in body
    assert "skipped" in body
    # The one valid reading still drives the cards/history (not the empty state).
    assert "reef-aggregate__empty" not in body


def test_single_malformed_row_uses_singular_copy(tmp_path):
    client, readings_path = _client(tmp_path)
    _write_csv(
        path=readings_path,
        data_rows=[
            "reef-a,salinity,2024-01-01,35,ppt,good",
            "reef-a,salinity,2024-01-02,bad,ppt,oops",
        ],
    )
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-notice" in body
    assert "1 row" in body
    assert "2 rows" not in body


def test_no_notice_when_data_is_clean(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(
        Reading(
            tank="reef-a",
            parameter="salinity",
            date=dt.date(2024, 1, 1),
            value=35.0,
            unit="ppt",
        ),
        readings_path,
    )
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-notice" not in body


def test_no_notice_on_first_run(tmp_path):
    # No CSV written at all → first-run, no warnings, no notice, no crash.
    client, _ = _client(tmp_path)
    for path in (
        "/tank/reef-a",
        "/tank/reef-a/parameter/salinity",
        "/tank/reef-a/aggregate",
    ):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "reef-notice" not in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Edge cases: single-reading + all-out-of-range render sensibly (no crash)
# --------------------------------------------------------------------------- #
def test_single_reading_renders_sensibly(tmp_path):
    client, readings_path = _client(tmp_path)
    append_reading(
        Reading(
            tank="reef-a",
            parameter="salinity",
            date=dt.date(2024, 1, 1),
            value=35.0,
            unit="ppt",
        ),
        readings_path,
    )
    resp = client.get("/tank/reef-a/parameter/salinity")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Stats show real data (not the empty prompt); a lone reading has no trend.
    assert "reef-stats__empty" not in body
    assert "Single reading" in body


def test_all_out_of_range_renders_sensibly(tmp_path):
    client, readings_path = _client(tmp_path)
    for day, value in ((1, 10.0), (2, 12.0), (3, 11.0)):
        append_reading(
            Reading(
                tank="reef-a",
                parameter="salinity",  # range 34–36, so 10–12 are all out
                date=dt.date(2024, 1, day),
                value=value,
                unit="ppt",
            ),
            readings_path,
        )
    resp = client.get("/tank/reef-a/parameter/salinity")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Out of range" in body
    # Aggregate view survives an all-out-of-range series too.
    agg = client.get("/tank/reef-a/aggregate")
    assert agg.status_code == 200
    assert "Out of range" in agg.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Edge cases: partially-configured content shows placeholders, not errors
# --------------------------------------------------------------------------- #
def test_partial_content_renders_placeholders_not_errors(tmp_path):
    # A parameter whose content file documents only ONE section: the rest degrade
    # to gentle placeholders rather than crashing or showing raw errors.
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "salinity.md").write_text(
        "# Salinity\n\n## Definition\n\nSalinity is the salt content of the water.\n",
        encoding="utf-8",
    )
    config = Config(
        tanks=[Tank(id="reef-a", label="Reef A")],
        parameters=_params(),
        content_dirs=[content_dir],
    )
    readings_path = tmp_path / "readings.csv"
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_READINGS_PATH": readings_path,
        }
    )
    client = app.test_client()
    resp = client.get("/tank/reef-a/parameter/salinity")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # The documented section shows; undocumented ones are placeholdered.
    assert "salt content" in body
    assert "is-placeholder" in body


# --------------------------------------------------------------------------- #
# Error handling: no unhandled crashes across empty/malformed scenarios
# --------------------------------------------------------------------------- #
def test_unknown_archived_param_does_not_crash(tmp_path):
    client, readings_path = _client(tmp_path)
    # A reading for a parameter no longer in config (archived/unknown).
    _write_csv(
        readings_path,
        [
            "reef-a,salinity,2024-01-01,35,ppt,good",
            "reef-a,nitrate,2024-01-02,5,ppm,archived param",
        ],
    )
    tank = client.get("/tank/reef-a")
    assert tank.status_code == 200
    assert "nitrate" in tank.get_data(as_text=True)  # surfaced, not dropped
    agg = client.get("/tank/reef-a/aggregate")
    assert agg.status_code == 200
    assert "archived" in agg.get_data(as_text=True)
    # The archived param has no configured tab → its parameter page 404s cleanly.
    assert client.get("/tank/reef-a/parameter/nitrate").status_code == 404


def test_fresh_install_walkthrough_no_crashes(tmp_path):
    # (1) No tanks configured at all.
    client, _ = _client(tmp_path, tanks=[])
    assert client.get("/").status_code == 200

    # (2) A tank exists but has no readings and no parameters configured.
    client2, _ = _client(
        tmp_path, tanks=[Tank(id="reef-a", label="Reef A")], parameters=[]
    )
    home = client2.get("/tank/reef-a")
    assert home.status_code == 200
    assert "No parameters configured" in home.get_data(as_text=True)

    # (3) A tank + params but zero readings: every page renders a friendly prompt.
    client3, _ = _client(tmp_path)
    for path in (
        "/",
        "/tank/reef-a",
        "/tank/reef-a/parameter/salinity",
        "/tank/reef-a/aggregate",
    ):
        assert client3.get(path).status_code == 200
