"""CSV persistence layer for fishy readings (spec §5.8 / §7.4).

This module is the single source of truth for *reading state*. Readings are
stored in plain-text, git-trackable CSVs in **long/tidy** form — one row per
reading — with a stable, documented column order::

    tank, parameter, date, value, unit, note

**Storage layout — one CSV per tank.** Each tank keeps its readings in its own
file under a data directory, keyed by the tank's id::

    data/<tank_id>/readings.csv

Resolve a tank's file with :func:`readings_path_for`. The low-level primitives
below (:func:`load_readings`, :func:`append_reading`, …) each operate on a single
CSV file — the caller passes the resolved per-tank path — so they stay simple and
unit-testable; the per-tank routing lives entirely in :func:`readings_path_for`.

Design goals (spec §7.5):

* **Git-friendly**: new readings are *appended* as a single row. Existing rows
  are never rewritten, so a git diff shows only the lines that actually changed.
* **Safe quoting**: notes may contain commas, quotes, or newlines. The stdlib
  :mod:`csv` module quotes them on write and unquotes them on read, so values
  round-trip losslessly.
* **Hand-editable / file-is-source-of-truth**: the file can be edited in any
  text editor. A malformed row surfaces a clear, non-fatal warning that names
  the row; the remaining valid rows still load.
* **Safe last-write semantics**: appends are made in ``"a"`` (append) mode, which
  always writes to the *current* end of the on-disk file. The whole file is
  never rewritten, so an external edit (a row added or corrected on disk while
  the app is running) can never be silently clobbered by an append.

Only the standard library is used — no new runtime dependency (spec §7.5).
"""

from __future__ import annotations

import csv
import datetime as _dt
import shutil
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "COLUMNS",
    "DEFAULT_DATA_DIR",
    "DEFAULT_READINGS_PATH",
    "READINGS_FILENAME",
    "Reading",
    "LoadResult",
    "ReadingError",
    "ensure_file",
    "load_readings",
    "append_reading",
    "append_readings",
    "readings_path_for",
    "delete_tank_data",
]

#: Stable, documented column order for ``readings.csv`` (spec §7.4). The order
#: is load-bearing for clean git diffs — do not reorder without updating the spec.
COLUMNS: tuple[str, ...] = ("tank", "parameter", "date", "value", "unit", "note")

#: Root directory holding one subdirectory per tank. Created on first write and
#: meant to be committed to git by the user. Anchored to the repo root (the
#: package's parent) — NOT the current working directory — so the app finds its
#: data no matter where it is launched from, mirroring how :mod:`fishy.config`
#: anchors ``DEFAULT_CONFIG_PATH``/``DEFAULT_CONTENT_DIR``. (Tests override this
#: via ``FISHY_DATA_DIR``.)
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR: Path = _REPO_ROOT / "data"

#: Filename of the readings CSV inside each tank's directory.
READINGS_FILENAME: str = "readings.csv"

#: Fallback single-file path used only as the default argument of the low-level
#: primitives when a caller omits an explicit path. The application never relies
#: on this — it always resolves a per-tank file via :func:`readings_path_for`.
DEFAULT_READINGS_PATH: Path = DEFAULT_DATA_DIR / READINGS_FILENAME


def readings_path_for(data_dir: Path | str, tank_id: str) -> Path:
    """Return a tank's readings CSV path: ``<data_dir>/<tank_id>/readings.csv``.

    The single seam that maps a tank id to its on-disk file. The parent
    directory is created lazily on first write (see :func:`ensure_file`), so
    this is a pure path computation with no filesystem side effects.
    """
    return Path(data_dir) / tank_id / READINGS_FILENAME


class ReadingError(ValueError):
    """Raised when a CSV row cannot be parsed into a :class:`Reading`."""


@dataclass(frozen=True)
class Reading:
    """A single water-parameter reading — one CSV row in long/tidy form.

    Attributes:
        tank: Stable tank identifier the reading belongs to.
        parameter: Stable parameter identifier (built-in or custom).
        date: The date the reading was taken.
        value: The measured value, in ``unit``.
        unit: The unit ``value`` is expressed in.
        note: Optional free-text note (safely CSV-quoted on write).
    """

    tank: str
    parameter: str
    date: _dt.date
    value: float
    unit: str
    note: str = ""

    def to_row(self) -> dict[str, str]:
        """Serialize to a ``column -> text`` mapping in the schema's key order."""
        return {
            "tank": self.tank,
            "parameter": self.parameter,
            "date": self.date.isoformat(),
            "value": _format_value(self.value),
            "unit": self.unit,
            "note": self.note,
        }

    def to_cells(self) -> list[str]:
        """Serialize to a list of cell strings in :data:`COLUMNS` order."""
        row = self.to_row()
        return [row[col] for col in COLUMNS]

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> Reading:
        """Parse a CSV row mapping into a :class:`Reading`.

        Raises:
            ReadingError: If a required column is missing/empty or ``value`` /
                ``date`` cannot be parsed. Callers that tolerate malformed rows
                (e.g. :func:`load_readings`) catch this and warn.
        """
        try:
            tank = _require(row, "tank")
            parameter = _require(row, "parameter")
            date = _parse_date(_require(row, "date"))
            value = _parse_value(_require(row, "value"))
        except ReadingError:
            raise
        except (KeyError, TypeError) as exc:  # defensive: malformed mapping
            raise ReadingError(f"malformed row: {exc}") from exc

        unit = (row.get("unit") or "").strip()
        # Note is preserved verbatim so quoted commas/quotes/newlines round-trip.
        note = row.get("note") or ""
        return cls(
            tank=tank,
            parameter=parameter,
            date=date,
            value=value,
            unit=unit,
            note=note,
        )


@dataclass
class LoadResult:
    """Outcome of :func:`load_readings`.

    Attributes:
        readings: All successfully-parsed readings, in file order.
        warnings: Human-readable, row-identifying warnings for skipped rows.
        first_run: ``True`` when the data file did not exist (no CSV yet).
    """

    readings: list[Reading] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    first_run: bool = False


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def ensure_file(path: Path | str = DEFAULT_READINGS_PATH) -> bool:
    """Create the CSV (with header) and its parent directory if missing.

    Returns:
        ``True`` if the file was created by this call, ``False`` if it already
        existed. Existing files (and their rows) are left untouched.
    """
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(COLUMNS)
    return True


def load_readings(
    path: Path | str = DEFAULT_READINGS_PATH,
    *,
    emit_warnings: bool = True,
) -> LoadResult:
    """Read every reading from the CSV into memory.

    The CSV is the single source of truth: this reflects the *current* on-disk
    file state, including any hand-edits, as long as the schema is followed.

    A missing file is a clear first-run state (``LoadResult.first_run == True``
    with no readings); it is *not* created as a side effect of loading. Use
    :func:`ensure_file` or :func:`append_reading` to create it.

    Malformed rows are skipped with a clear, non-fatal warning identifying the
    row; valid rows still load.

    Args:
        path: Path to the readings CSV.
        emit_warnings: When ``True``, also emit each warning via
            :func:`warnings.warn` so it is visible on the console. The warnings
            are always returned in :attr:`LoadResult.warnings` regardless.
    """
    path = Path(path)
    result = LoadResult()

    if not path.exists():
        result.first_run = True
        return result

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)

        header = reader.fieldnames
        if header is None:
            # Completely empty file (not even a header row).
            return result
        if list(header) != list(COLUMNS):
            result.warnings.append(
                f"unexpected CSV header {header!r}; expected {list(COLUMNS)!r}"
            )

        # DictReader's line_num counts the header, so the first data row is 2.
        for row in reader:
            line_no = reader.line_num
            try:
                result.readings.append(Reading.from_row(row))
            except ReadingError as exc:
                result.warnings.append(f"row {line_no}: skipped — {exc}")

    if emit_warnings:
        for message in result.warnings:
            warnings.warn(message, stacklevel=2)

    return result


def append_reading(
    reading: Reading,
    path: Path | str = DEFAULT_READINGS_PATH,
) -> None:
    """Append a single reading as one CSV row (append-only, clean git diffs).

    Creates the file (with header) and parent directory if they do not exist.
    The write is made in append mode against the current on-disk file, so
    existing rows — including any added externally since load — are preserved.
    """
    append_readings([reading], path)


def append_readings(
    readings: Iterable[Reading],
    path: Path | str = DEFAULT_READINGS_PATH,
) -> int:
    """Append multiple readings; returns the number of rows written.

    Each reading becomes exactly one row in :data:`COLUMNS` order, with the
    stdlib :mod:`csv` writer handling minimal quoting for commas/quotes/newlines.
    """
    path = Path(path)
    ensure_file(path)
    count = 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for reading in readings:
            writer.writerow(reading.to_cells())
            count += 1
    return count


def delete_tank_data(
    tank_id: str,
    data_dir: Path | str = DEFAULT_DATA_DIR,
) -> bool:
    """Delete a tank's entire data directory (``<data_dir>/<tank_id>/``).

    With one CSV per tank, removing a tank is simply removing its directory —
    no rewriting of other tanks' files is involved, and nothing else can be
    affected. Returns ``True`` if a directory existed and was removed, ``False``
    if there was nothing to delete (a tank that was never logged).
    """
    tank_dir = Path(data_dir) / tank_id
    if not tank_dir.exists():
        return False
    shutil.rmtree(tank_dir)
    return True


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require(row: Mapping[str, str], column: str) -> str:
    """Return a stripped, non-empty required cell or raise :class:`ReadingError`."""
    raw = row.get(column)
    if raw is None:
        raise ReadingError(f"missing required column {column!r}")
    text = raw.strip()
    if not text:
        raise ReadingError(f"empty required column {column!r}")
    return text


def _parse_date(text: str) -> _dt.date:
    """Parse an ISO ``YYYY-MM-DD`` date (accepting an ISO datetime prefix)."""
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        # Tolerate an ISO datetime (e.g. "2026-07-01T08:00") by taking the date.
        try:
            return _dt.datetime.fromisoformat(text).date()
        except ValueError as exc:
            raise ReadingError(f"invalid date {text!r} (expected YYYY-MM-DD)") from exc


def _parse_value(text: str) -> float:
    """Parse a numeric ``value`` cell into a float."""
    try:
        return float(text)
    except ValueError as exc:
        raise ReadingError(f"invalid numeric value {text!r}") from exc


def _format_value(value: float) -> str:
    """Format a numeric value with a stable, round-tripping representation.

    Uses Python's shortest round-tripping float repr so that, for example,
    ``1.026`` and ``0.08`` are written back exactly rather than with float noise.
    """
    number = float(value)
    if number.is_integer():
        # Keep whole numbers compact (e.g. 8 rather than 8.0) for readable diffs.
        return str(int(number))
    return repr(number)
