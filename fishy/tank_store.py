"""Write-side companion to :mod:`fishy.config` for managing tanks (spec §5.1).

:mod:`fishy.config` is a **read-only** pure-data layer. This module is its
mutating counterpart for the one part of the config the UI needs to manage at
runtime: the ``[[tanks]]`` array. Creating and deleting tanks are surgical,
**comment-preserving text edits** to ``config/fishy.toml`` — hand-authored
comments, ``[[parameters]]`` blocks and ``[overrides.*]`` tables all survive an
add or delete untouched.

Why edit text instead of re-serialising? Python's stdlib ``tomllib`` is
read-only (there is no ``tomllib.dump``), and adding a TOML *writer* dependency
would violate the project's minimal-dependency rule (CLAUDE.md / spec §7.5). A
full rewrite would also flatten the file's carefully authored comments. So we
operate block-by-block on the raw lines, which keeps the file diff-friendly:
adding a tank appends four lines; deleting one removes exactly its block (and
any per-tank override tables that would otherwise dangle).

Nothing here imports Flask; like :mod:`fishy.config` it is a pure data layer so
it can be unit-tested in isolation.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "TankStoreError",
    "slugify",
    "is_valid_id",
    "tank_ids",
    "add_tank",
    "delete_tank",
]

#: A tank id must be URL- and CSV-safe: it rides in ``/tank/<id>`` paths and is
#: stored verbatim as the CSV ``tank`` key. Lowercase alphanumerics and hyphens,
#: starting with an alphanumeric.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class TankStoreError(ValueError):
    """Raised when a tank cannot be created or deleted.

    The message is written to be *actionable* (CLAUDE.md convention): it names
    the specific problem so it can be surfaced to the user verbatim.
    """


# --------------------------------------------------------------------------- #
# Id helpers
# --------------------------------------------------------------------------- #
def slugify(label: str) -> str:
    """Derive a URL/CSV-safe tank id from a human ``label``.

    Lowercases, collapses every run of non-alphanumerics to a single hyphen and
    trims stray hyphens (e.g. ``"Display Reef!"`` -> ``"display-reef"``). May
    return ``""`` if the label has no alphanumerics; callers handle that.
    """
    return re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")


def is_valid_id(tank_id: str) -> bool:
    """Whether ``tank_id`` is a well-formed tank id (see :data:`_ID_RE`)."""
    return bool(_ID_RE.match(tank_id))


# --------------------------------------------------------------------------- #
# TOML block parsing (text-level, comment-preserving)
# --------------------------------------------------------------------------- #
def _is_key_line(line: str) -> bool:
    """True for a ``key = value`` line (not blank, comment, or table header)."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith(("#", "[")) and "=" in stripped


def _block_end(lines: list[str], start: int) -> int:
    """Exclusive end index of the header block that starts at ``start``.

    A block is its header line plus the consecutive ``key = value`` lines that
    follow it, stopping at the first blank line, comment, or new table header.
    This matches how this config file is written (compact tables with no blank
    lines or comments *inside* a table), so a block never swallows the comment
    banner that introduces the next section.
    """
    i = start + 1
    while i < len(lines) and _is_key_line(lines[i]):
        i += 1
    return i


def _iter_tank_blocks(lines: list[str]):
    """Yield ``(start, end, id, label)`` for every ``[[tanks]]`` block."""
    for i, line in enumerate(lines):
        if line.strip() != "[[tanks]]":
            continue
        end = _block_end(lines, i)
        tank_id: str | None = None
        label: str | None = None
        for j in range(i + 1, end):
            id_match = re.match(r'\s*id\s*=\s*"(.*?)"\s*$', lines[j])
            if id_match:
                tank_id = id_match.group(1)
            label_match = re.match(r'\s*label\s*=\s*"(.*?)"\s*$', lines[j])
            if label_match:
                label = label_match.group(1)
        yield i, end, tank_id, label


def _escape(value: str) -> str:
    """Escape a string for a TOML basic (double-quoted) string literal."""
    # Collapse control whitespace (a single-line input should never contain it,
    # but be defensive) then escape backslashes and quotes.
    cleaned = re.sub(r"[\r\n\t]+", " ", value)
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


def _read_lines(config_path: Path) -> list[str]:
    if not config_path.is_file():
        raise TankStoreError(
            f"Config file not found: {config_path}. Cannot modify tanks."
        )
    # Split on "\n" (not splitlines) so the exact line structure round-trips.
    return config_path.read_text(encoding="utf-8").split("\n")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def tank_ids(config_path: str | Path) -> list[str]:
    """Return the tank ids currently declared in ``config_path``, in file order."""
    lines = _read_lines(Path(config_path))
    return [tid for _, _, tid, _ in _iter_tank_blocks(lines) if tid]


def add_tank(config_path: str | Path, tank_id: str, label: str) -> None:
    """Append a new ``[[tanks]]`` block for ``tank_id`` / ``label``.

    The new block is inserted directly after the last existing ``[[tanks]]``
    block (keeping tanks grouped) or, if none exist, appended at the end of the
    file — an array-of-tables entry is valid TOML anywhere. Everything else in
    the file (comments, parameters, overrides) is left byte-for-byte intact.

    Raises:
        TankStoreError: if ``tank_id`` is malformed or already exists.
    """
    path = Path(config_path)
    tank_id = tank_id.strip()
    if not is_valid_id(tank_id):
        raise TankStoreError(
            f"'{tank_id}' isn't a valid tank id — use lowercase letters, numbers "
            "and hyphens (e.g. 'display-reef')."
        )
    label = label.strip() or tank_id

    lines = _read_lines(path)
    blocks = list(_iter_tank_blocks(lines))
    if any(tid == tank_id for _, _, tid, _ in blocks):
        raise TankStoreError(f"A tank with id '{tank_id}' already exists.")

    new_block = ["", "[[tanks]]", f'id = "{tank_id}"', f'label = "{_escape(label)}"']
    if blocks:
        insert_at = blocks[-1][1]  # exclusive end of the last tank block
        lines[insert_at:insert_at] = new_block
    else:
        # No tanks yet: append at EOF, avoiding a stray trailing blank line.
        while lines and lines[-1] == "":
            lines.pop()
        lines.extend(new_block + [""])

    path.write_text("\n".join(lines), encoding="utf-8")


def delete_tank(config_path: str | Path, tank_id: str) -> None:
    """Remove the ``[[tanks]]`` block for ``tank_id`` and its override tables.

    Deletes the matching ``[[tanks]]`` block plus any ``[overrides.<tank_id>]``
    or ``[overrides.<tank_id>.*]`` tables (which would otherwise reference a tank
    that no longer exists). One trailing blank line per removed block is swallowed
    to avoid piling up blank lines. All other content is preserved.

    Raises:
        TankStoreError: if no tank with ``tank_id`` exists.
    """
    path = Path(config_path)
    lines = _read_lines(path)

    to_delete: set[int] = set()
    found = False

    for start, end, tid, _ in _iter_tank_blocks(lines):
        if tid == tank_id:
            found = True
            to_delete.update(range(start, end))
            if end < len(lines) and lines[end].strip() == "":
                to_delete.add(end)

    # Per-tank override tables: [overrides.<id>] or [overrides.<id>.<param>].
    override_prefixes = (f"[overrides.{tank_id}]", f"[overrides.{tank_id}.")
    for i, line in enumerate(lines):
        if line.strip().startswith(override_prefixes):
            end = _block_end(lines, i)
            to_delete.update(range(i, end))
            if end < len(lines) and lines[end].strip() == "":
                to_delete.add(end)

    if not found:
        raise TankStoreError(f"No tank with id '{tank_id}' to delete.")

    kept = [line for idx, line in enumerate(lines) if idx not in to_delete]
    path.write_text("\n".join(kept), encoding="utf-8")
