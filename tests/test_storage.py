"""Tests for the CSV readings persistence layer (spec §5.8 / §7.4, task 2).

Layering mirrors the testing requirements for the task:
  * Unit        — Reading (de)serialization for every column, quoted notes,
                  value formatting; append preserves column order & existing rows.
  * Integration — round-trip write->read equality; malformed-row tolerance;
                  first-run file creation with header.
  * Performance — thousands of rows load without noticeable lag.
"""

from __future__ import annotations

import datetime as dt
import time

import pytest

from fishy import storage
from fishy.storage import (
    COLUMNS,
    LoadResult,
    Reading,
    ReadingError,
    append_reading,
    append_readings,
    ensure_file,
    load_readings,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def csv_path(tmp_path):
    """A readings CSV path inside a fresh temp directory (file not yet created)."""
    return tmp_path / "data" / "readings.csv"


def _reading(**overrides) -> Reading:
    base = dict(
        tank="reef-a",
        parameter="salinity",
        date=dt.date(2026, 6, 28),
        value=1.026,
        unit="sg",
        note="",
    )
    base.update(overrides)
    return Reading(**base)


# --------------------------------------------------------------------------- #
# Unit: schema / row (de)serialization
# --------------------------------------------------------------------------- #
def test_schema_column_order_is_stable():
    assert COLUMNS == ("tank", "parameter", "date", "value", "unit", "note")


def test_to_row_serializes_all_columns():
    reading = _reading(
        parameter="alkalinity", date=dt.date(2026, 6, 29), value=7.9, unit="dKH",
        note="algae starting",
    )
    row = reading.to_row()
    assert list(row.keys()) == list(COLUMNS)
    assert row == {
        "tank": "reef-a",
        "parameter": "alkalinity",
        "date": "2026-06-29",
        "value": "7.9",
        "unit": "dKH",
        "note": "algae starting",
    }


def test_to_cells_follows_column_order():
    reading = _reading(value=0.08, unit="ppm", parameter="phosphate")
    assert reading.to_cells() == ["reef-a", "phosphate", "2026-06-28", "0.08", "ppm", ""]


def test_from_row_parses_all_columns_with_correct_types():
    row = {
        "tank": "reef-a",
        "parameter": "alkalinity",
        "date": "2026-07-01",
        "value": "7.1",
        "unit": "dKH",
        "note": "dosed",
    }
    reading = Reading.from_row(row)
    assert reading.tank == "reef-a"
    assert reading.parameter == "alkalinity"
    assert reading.date == dt.date(2026, 7, 1)
    assert reading.value == pytest.approx(7.1)
    assert reading.unit == "dKH"
    assert reading.note == "dosed"


@pytest.mark.parametrize("raw,expected", [("1.026", "1.026"), (0.08, "0.08"), (8.0, "8"), (7.9, "7.9")])
def test_value_formatting_is_clean_and_stable(raw, expected):
    assert _reading(value=float(raw)).to_row()["value"] == expected


def test_serialize_deserialize_roundtrip_for_reading():
    reading = _reading(value=8.2, unit="dKH", parameter="alkalinity", note="fine")
    assert Reading.from_row(reading.to_row()) == reading


def test_from_row_rejects_missing_required_columns():
    for missing in ("tank", "parameter", "date", "value"):
        row = _reading().to_row()
        row[missing] = ""
        with pytest.raises(ReadingError):
            Reading.from_row(row)


def test_from_row_rejects_non_numeric_value_and_bad_date():
    with pytest.raises(ReadingError):
        Reading.from_row(_reading().to_row() | {"value": "abc"})
    with pytest.raises(ReadingError):
        Reading.from_row(_reading().to_row() | {"date": "not-a-date"})


# --------------------------------------------------------------------------- #
# Unit: quoted notes round-trip losslessly
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "note",
    [
        "algae starting, watch it",          # comma
        'he said "watch it"',                # embedded quotes
        "line one\nline two",                # newline
        'complex: comma, "quote", and\nnewline',
    ],
)
def test_notes_with_special_chars_roundtrip(csv_path, note):
    reading = _reading(note=note)
    append_reading(reading, csv_path)
    result = load_readings(csv_path, emit_warnings=False)
    assert result.readings == [reading]
    assert result.readings[0].note == note


# --------------------------------------------------------------------------- #
# Unit / Integration: append preserves order and existing rows verbatim
# --------------------------------------------------------------------------- #
def test_append_writes_single_row_in_column_order(csv_path):
    append_reading(_reading(value=7.9, unit="dKH", parameter="alkalinity"), csv_path)
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "tank,parameter,date,value,unit,note"
    assert lines[1] == "reef-a,alkalinity,2026-06-28,7.9,dKH,"
    assert len(lines) == 2


def test_append_preserves_existing_rows_verbatim(csv_path):
    ensure_file(csv_path)
    first_row = "reef-a,salinity,2026-06-01,1.025,sg,hand-written note\n"
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(first_row)
    before = csv_path.read_text(encoding="utf-8")

    append_reading(_reading(date=dt.date(2026, 6, 28)), csv_path)
    after = csv_path.read_text(encoding="utf-8")

    # Everything that existed before is still present, byte-for-byte, up front.
    assert after.startswith(before)
    assert after.count("\n") == before.count("\n") + 1


def test_appends_are_append_only(csv_path):
    append_reading(_reading(date=dt.date(2026, 6, 1)), csv_path)
    snapshot = csv_path.read_text(encoding="utf-8")
    append_reading(_reading(date=dt.date(2026, 6, 2)), csv_path)
    assert csv_path.read_text(encoding="utf-8").startswith(snapshot)


# --------------------------------------------------------------------------- #
# Integration: first-run file creation with header
# --------------------------------------------------------------------------- #
def test_load_missing_file_returns_first_run_state_without_creating(csv_path):
    result = load_readings(csv_path)
    assert isinstance(result, LoadResult)
    assert result.first_run is True
    assert result.readings == []
    assert not csv_path.exists()  # loading has no side effects


def test_ensure_file_creates_header_only_file(csv_path):
    created = ensure_file(csv_path)
    assert created is True
    assert csv_path.exists()
    assert csv_path.read_text(encoding="utf-8").splitlines() == [
        "tank,parameter,date,value,unit,note"
    ]
    # Second call is a no-op that does not overwrite.
    assert ensure_file(csv_path) is False


def test_append_creates_file_with_header_on_first_run(csv_path):
    assert not csv_path.exists()
    append_reading(_reading(), csv_path)
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "tank,parameter,date,value,unit,note"
    assert len(lines) == 2


# --------------------------------------------------------------------------- #
# Integration: round-trip write -> read equality
# --------------------------------------------------------------------------- #
def test_write_read_roundtrip_equality(csv_path):
    readings = [
        _reading(parameter="salinity", value=1.026, unit="sg", date=dt.date(2026, 6, 28)),
        _reading(parameter="alkalinity", value=7.9, unit="dKH",
                 date=dt.date(2026, 6, 29), note="algae starting, watch it"),
        _reading(parameter="phosphate", value=0.08, unit="ppm", date=dt.date(2026, 6, 29)),
        _reading(parameter="alkalinity", value=7.1, unit="dKH",
                 date=dt.date(2026, 7, 1), note='dosed, "10% water change"'),
    ]
    append_readings(readings, csv_path)
    result = load_readings(csv_path, emit_warnings=False)
    assert result.readings == readings
    assert result.first_run is False
    assert result.warnings == []


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_partial_readings_no_forced_grid(csv_path):
    # Only some parameters logged on a given day — represented naturally.
    append_reading(_reading(parameter="salinity", value=1.026, unit="sg"), csv_path)
    append_reading(_reading(parameter="alkalinity", value=7.9, unit="dKH"), csv_path)
    result = load_readings(csv_path, emit_warnings=False)
    params = [r.parameter for r in result.readings]
    assert params == ["salinity", "alkalinity"]
    assert len(result.readings) == 2  # no filler rows for un-logged parameters


def test_multiple_readings_same_parameter_same_day_all_preserved(csv_path):
    day = dt.date(2026, 6, 29)
    append_reading(_reading(parameter="alkalinity", value=7.9, unit="dKH", date=day), csv_path)
    append_reading(_reading(parameter="alkalinity", value=7.6, unit="dKH", date=day), csv_path)
    result = load_readings(csv_path, emit_warnings=False)
    assert [r.value for r in result.readings] == [pytest.approx(7.9), pytest.approx(7.6)]


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
def test_malformed_row_is_skipped_with_identifying_warning(csv_path):
    ensure_file(csv_path)
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("reef-a,salinity,2026-06-28,1.026,sg,good\n")
        handle.write("reef-a,alkalinity,NOT-A-DATE,7.9,dKH,bad date\n")
        handle.write("reef-a,calcium,2026-06-30,not-a-number,ppm,bad value\n")
        handle.write("reef-a,magnesium,2026-07-01,1300,ppm,good\n")

    result = load_readings(csv_path, emit_warnings=False)

    # Valid rows still load...
    assert [r.parameter for r in result.readings] == ["salinity", "magnesium"]
    # ...and each bad row is flagged with a clear, row-identifying warning.
    assert len(result.warnings) == 2
    assert any("row 3" in w for w in result.warnings)  # bad date (line 3)
    assert any("row 4" in w for w in result.warnings)  # bad value (line 4)


def test_load_emits_python_warning_when_enabled(csv_path):
    ensure_file(csv_path)
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("reef-a,alkalinity,bad,7.9,dKH,\n")
    with pytest.warns(UserWarning):
        result = load_readings(csv_path, emit_warnings=True)
    assert result.readings == []
    assert result.warnings


def test_external_edit_not_clobbered_by_append(csv_path):
    """Defined last-write semantics: append never rewrites existing rows.

    Simulates the file changing on disk (a row added externally) after an
    initial load; a subsequent append must preserve that external row.
    """
    append_reading(_reading(parameter="salinity", value=1.026, unit="sg"), csv_path)
    load_readings(csv_path, emit_warnings=False)  # app has its in-memory view

    # External edit lands on disk after the app loaded.
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("reef-b,calcium,2026-06-30,420,ppm,external add\n")

    # App appends its own new reading.
    append_reading(_reading(parameter="alkalinity", value=7.9, unit="dKH"), csv_path)

    result = load_readings(csv_path, emit_warnings=False)
    tanks_params = [(r.tank, r.parameter) for r in result.readings]
    assert ("reef-b", "calcium") in tanks_params  # external row not lost
    assert tanks_params == [
        ("reef-a", "salinity"),
        ("reef-b", "calcium"),
        ("reef-a", "alkalinity"),
    ]


# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #
def test_loads_thousands_of_rows_quickly(csv_path):
    rows = [
        _reading(
            parameter="alkalinity",
            value=7.0 + (i % 20) / 10,
            unit="dKH",
            date=dt.date(2026, 1, 1) + dt.timedelta(days=i % 365),
            note="",
        )
        for i in range(5000)
    ]
    append_readings(rows, csv_path)

    start = time.perf_counter()
    result = load_readings(csv_path, emit_warnings=False)
    elapsed = time.perf_counter() - start

    assert len(result.readings) == 5000
    assert elapsed < 2.0  # generous bound; loading 5k rows is near-instant
