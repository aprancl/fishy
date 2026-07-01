"""Config & content loader for fishy (spec §7.4 / §5.4-5.6 / §9.1).

This module is the git-tracked *configuration and content layer*. It defines:

* **Tanks**   — id + display label (spec §5.1).
* **Parameters** — built-in reef set plus user-defined ones: id, display name,
  unit(s), and a default target range (spec §5.6 / §5.5).
* **Target ranges** — a default band per parameter with optional per-tank
  overrides (spec §5.5).
* **Reference content** — per-parameter markdown files (definition, measurement
  methods, ideal range, consequences of too high/low, signs, remedies) shipped
  with sensible defaults and fully user-overridable (spec §5.4).

Design decisions (resolving spec Open Question #2):

* **Config format = TOML**, parsed with the standard-library ``tomllib`` — a
  human-editable format that adds **no runtime dependency** (Python 3.11+).
* **Content format = markdown**, with ``## Heading`` delimited sections so the
  UI phase can render them and custom parameters get a fillable template.

Nothing here imports Flask; the loader is a pure data layer so it can be unit
tested in isolation and reused by any view. Invalid-but-recoverable problems
(e.g. an inverted ``min > max`` range) are collected as *warnings* so the app
still runs; only genuinely unparseable input raises :class:`ConfigError`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Default file locations (shipped defaults live at the repo root)
# --------------------------------------------------------------------------- #
_PACKAGE_DIR = Path(__file__).resolve().parent          # .../fishy
_REPO_ROOT = _PACKAGE_DIR.parent                        # repo root

#: Path to the shipped default config file.
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "fishy.toml"

#: Directory holding the shipped default per-parameter content files.
DEFAULT_CONTENT_DIR = _REPO_ROOT / "content"

#: Filename (in a content dir) of the fillable template for custom parameters.
TEMPLATE_FILENAME = "_template.md"


# --------------------------------------------------------------------------- #
# Content section model
# --------------------------------------------------------------------------- #
# Canonical, ordered reference sections. Each tuple is (key, display heading).
# The UI renders sections in this order; missing ones become gentle placeholders
# rather than errors (spec §5.4 edge case).
SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("definition", "Definition"),
    ("measurement", "Measurement & Units"),
    ("ideal_range", "Ideal Range"),
    ("too_high", "When It's Too High"),
    ("too_low", "When It's Too Low"),
    ("signs", "Signs & Symptoms"),
    ("remedies", "Suggested Remedies"),
)

SECTION_KEYS: tuple[str, ...] = tuple(key for key, _ in SECTION_ORDER)
_SECTION_HEADINGS: dict[str, str] = {key: heading for key, heading in SECTION_ORDER}

# Map a normalised ``## heading`` string to a canonical section key. Aliases keep
# hand-edited content forgiving (e.g. "Target Range" -> ideal_range).
_HEADING_ALIASES: dict[str, str] = {
    "definition": "definition",
    "what it is": "definition",
    "measurement & units": "measurement",
    "measurement and units": "measurement",
    "measurement": "measurement",
    "measurement methods": "measurement",
    "units": "measurement",
    "ideal range": "ideal_range",
    "target range": "ideal_range",
    "safe range": "ideal_range",
    "when it's too high": "too_high",
    "when its too high": "too_high",
    "too high": "too_high",
    "consequences of too high": "too_high",
    "when it's too low": "too_low",
    "when its too low": "too_low",
    "too low": "too_low",
    "consequences of too low": "too_low",
    "signs & symptoms": "signs",
    "signs and symptoms": "signs",
    "signs": "signs",
    "symptoms": "signs",
    "suggested remedies": "remedies",
    "remedies": "remedies",
    "how to fix it": "remedies",
}

_HEADING_RE = re.compile(r"^\s{0,3}#{2,3}\s+(.*?)\s*#*\s*$")


def _placeholder_for(key: str) -> str:
    """Return the gentle placeholder shown when a section is absent."""
    heading = _SECTION_HEADINGS.get(key, key.replace("_", " ").title())
    return f"_No {heading.lower()} provided yet._"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ConfigError(Exception):
    """Raised when a config file is missing or cannot be parsed.

    The message is written to be *actionable* — it names the file and the
    specific problem so the keeper can fix it by hand (spec §5.5 error handling,
    CLAUDE.md "actionable errors" convention).
    """


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TargetRange:
    """An ideal min-max band for a parameter (spec §5.5).

    Either bound may be ``None`` — a one-sided range highlights only the bound
    that exists. A range where ``min > max`` is *invalid*; callers surface a
    warning and treat it as having no usable band.
    """

    min: float | None = None
    max: float | None = None

    @property
    def is_empty(self) -> bool:
        """True when neither bound is set (no band to draw)."""
        return self.min is None and self.max is None

    @property
    def is_valid(self) -> bool:
        """True unless both bounds exist and ``min > max``."""
        if self.min is not None and self.max is not None:
            return self.min <= self.max
        return True

    def contains(self, value: float) -> bool:
        """Return whether ``value`` falls within the (possibly one-sided) band.

        An empty or invalid range contains everything (nothing to flag).
        """
        if not self.is_valid or self.is_empty:
            return True
        if self.min is not None and value < self.min:
            return False
        if self.max is not None and value > self.max:
            return False
        return True


@dataclass(frozen=True)
class Tank:
    """A configured tank: a stable ``id`` plus a human ``label`` (spec §5.1)."""

    id: str
    label: str


@dataclass(frozen=True)
class Parameter:
    """A tracked water parameter (spec §5.6).

    Attributes:
        id: Stable identifier used as the CSV ``parameter`` key.
        display_name: Human label shown in the UI.
        units: Accepted unit strings (first is the default/canonical unit).
        target_range: Default ideal band, or ``None`` if none is configured.
        overrides: Per-tank range overrides keyed by tank id (spec §5.5).
        builtin: Whether this ships as part of the built-in reef set.
    """

    id: str
    display_name: str
    units: tuple[str, ...] = ()
    target_range: TargetRange | None = None
    overrides: dict[str, TargetRange] = field(default_factory=dict)
    builtin: bool = False

    @property
    def default_unit(self) -> str | None:
        """The canonical unit (first declared), or ``None`` if unit-less."""
        return self.units[0] if self.units else None

    def range_for_tank(self, tank_id: str | None) -> TargetRange | None:
        """Resolve the effective range for a tank.

        A per-tank override wins; otherwise the parameter default applies. A
        tank without an override falls back to the default (spec §5.5).
        """
        if tank_id is not None and tank_id in self.overrides:
            return self.overrides[tank_id]
        return self.target_range


@dataclass(frozen=True)
class ParameterContent:
    """Resolved reference content for one parameter (spec §5.4).

    ``sections`` always contains every canonical key: present sections hold the
    authored text, absent ones hold a placeholder. ``present`` records which
    keys were actually authored so the UI can style placeholders differently.
    """

    parameter_id: str
    sections: dict[str, str]
    present: frozenset[str]
    source: Path | None = None

    def is_present(self, key: str) -> bool:
        """Whether ``key`` was authored (vs. a generated placeholder)."""
        return key in self.present

    def get(self, key: str) -> str:
        """Return a section's text (placeholder if it was not authored)."""
        return self.sections.get(key, _placeholder_for(key))

    def ordered(self) -> list[tuple[str, str, str]]:
        """Return ``(key, heading, text)`` tuples in canonical render order."""
        return [
            (key, _SECTION_HEADINGS[key], self.sections.get(key, _placeholder_for(key)))
            for key in SECTION_KEYS
        ]


@dataclass
class Config:
    """The fully loaded configuration (spec §7.4 config layer).

    Attributes:
        tanks: Configured tanks, in file order.
        parameters: Configured parameters, in file order.
        warnings: Non-fatal problems (e.g. inverted ranges) surfaced to the
            keeper. The app still runs when this is non-empty (spec §5.5).
        content_dirs: Directories searched (in order) for content files;
            earlier entries win, enabling user overrides of shipped defaults.
    """

    tanks: list[Tank] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    content_dirs: list[Path] = field(default_factory=list)

    # -- lookups ----------------------------------------------------------- #
    @property
    def tanks_by_id(self) -> dict[str, Tank]:
        return {t.id: t for t in self.tanks}

    @property
    def parameters_by_id(self) -> dict[str, Parameter]:
        return {p.id: p for p in self.parameters}

    def tank(self, tank_id: str) -> Tank | None:
        return self.tanks_by_id.get(tank_id)

    def parameter(self, parameter_id: str) -> Parameter | None:
        return self.parameters_by_id.get(parameter_id)

    def content_for(self, parameter_id: str) -> ParameterContent:
        """Load and resolve reference content for ``parameter_id``.

        Falls back to the fillable template (then to all-placeholders) when no
        parameter-specific file exists, so custom parameters always render.
        """
        return load_content(parameter_id, self.content_dirs)


# --------------------------------------------------------------------------- #
# Content parsing / resolution
# --------------------------------------------------------------------------- #
def parse_content(text: str) -> dict[str, str]:
    """Parse markdown into a mapping of canonical section key -> text.

    Sections are delimited by ``##`` (or ``###``) headings. A leading ``#``
    title and any preamble are ignored. Unknown headings are skipped rather
    than raising, keeping hand-edited files forgiving.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            heading = match.group(1).strip()
            # A single '#' title line won't match (regex requires >=2 '#').
            key = _HEADING_ALIASES.get(heading.lower())
            current = key
            if key is not None:
                sections.setdefault(key, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
        if "\n".join(lines).strip()
    }


def resolve_content_file(parameter_id: str, content_dirs: list[Path]) -> Path | None:
    """Return the first existing ``<parameter_id>.md`` across ``content_dirs``.

    Earlier directories take precedence, so a user content dir listed before the
    shipped-defaults dir overrides it (spec §5.4 "user override precedence").
    """
    for directory in content_dirs:
        candidate = Path(directory) / f"{parameter_id}.md"
        if candidate.is_file():
            return candidate
    return None


def load_content(parameter_id: str, content_dirs: list[Path] | None = None) -> ParameterContent:
    """Resolve reference content for a parameter with graceful fallbacks.

    Resolution order:

    1. ``<parameter_id>.md`` in the first content dir that has it (user wins).
    2. The fillable ``_template.md`` (used for custom parameters lacking a file).
    3. All-placeholder sections (nothing on disk at all).

    A missing or partially filled file never raises — absent sections become
    placeholders (spec §5.4 edge case).
    """
    dirs = [Path(d) for d in (content_dirs or [DEFAULT_CONTENT_DIR])]

    source = resolve_content_file(parameter_id, dirs)
    if source is None:
        for directory in dirs:
            template = directory / TEMPLATE_FILENAME
            if template.is_file():
                source = template
                break

    parsed: dict[str, str] = {}
    if source is not None:
        parsed = parse_content(source.read_text(encoding="utf-8"))

    sections: dict[str, str] = {}
    present: set[str] = set()
    for key in SECTION_KEYS:
        value = parsed.get(key, "").strip()
        if value:
            sections[key] = value
            present.add(key)
        else:
            sections[key] = _placeholder_for(key)

    # A template file is a source of placeholders, not authored content: only
    # count sections as "present" when a real parameter file supplied them.
    from_template = source is not None and source.name == TEMPLATE_FILENAME
    return ParameterContent(
        parameter_id=parameter_id,
        sections=sections,
        present=frozenset() if from_template else frozenset(present),
        source=source,
    )


# --------------------------------------------------------------------------- #
# Config parsing
# --------------------------------------------------------------------------- #
def _coerce_bound(raw: object) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):  # bool is an int subclass; reject explicitly.
        raise ValueError("range bound must be a number, not a boolean")
    if isinstance(raw, (int, float)):
        return float(raw)
    raise ValueError(f"range bound must be a number, got {raw!r}")


def _parse_range(raw: object, *, where: str) -> TargetRange | None:
    """Build a TargetRange from a ``{min, max}`` table; ``None`` if absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{where}: target range must be a table with 'min' and/or 'max', "
            f"got {type(raw).__name__}."
        )
    try:
        low = _coerce_bound(raw.get("min"))
        high = _coerce_bound(raw.get("max"))
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}.") from exc
    if low is None and high is None:
        return None
    return TargetRange(min=low, max=high)


def _parse_tanks(data: dict, warnings: list[str]) -> list[Tank]:
    tanks: list[Tank] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("tanks", []) or []):
        if not isinstance(raw, dict):
            raise ConfigError(f"[[tanks]] entry #{i + 1} must be a table.")
        tank_id = raw.get("id")
        if not tank_id or not isinstance(tank_id, str):
            raise ConfigError(
                f"[[tanks]] entry #{i + 1} is missing a string 'id'. "
                "Add e.g. id = \"reef-a\"."
            )
        if tank_id in seen:
            warnings.append(f"Duplicate tank id '{tank_id}' — later definition ignored.")
            continue
        seen.add(tank_id)
        label = raw.get("label") or tank_id
        tanks.append(Tank(id=tank_id, label=str(label)))
    return tanks


def _parse_overrides(data: dict, warnings: list[str]) -> dict[str, dict[str, TargetRange]]:
    """Return ``{tank_id: {parameter_id: TargetRange}}`` from ``[overrides]``."""
    result: dict[str, dict[str, TargetRange]] = {}
    raw_overrides = data.get("overrides") or {}
    if not isinstance(raw_overrides, dict):
        raise ConfigError("[overrides] must be a table keyed by tank id.")
    for tank_id, params in raw_overrides.items():
        if not isinstance(params, dict):
            raise ConfigError(f"[overrides.{tank_id}] must be a table keyed by parameter id.")
        for param_id, raw_range in params.items():
            where = f"[overrides.{tank_id}.{param_id}]"
            rng = _parse_range(raw_range, where=where)
            if rng is None:
                continue
            if not rng.is_valid:
                warnings.append(
                    f"{where}: invalid range min={rng.min} > max={rng.max}; "
                    "override ignored (no band applied)."
                )
                continue
            result.setdefault(tank_id, {})[param_id] = rng
    return result


def _parse_parameters(
    data: dict,
    overrides: dict[str, dict[str, TargetRange]],
    warnings: list[str],
) -> list[Parameter]:
    parameters: list[Parameter] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("parameters", []) or []):
        if not isinstance(raw, dict):
            raise ConfigError(f"[[parameters]] entry #{i + 1} must be a table.")
        param_id = raw.get("id")
        if not param_id or not isinstance(param_id, str):
            raise ConfigError(
                f"[[parameters]] entry #{i + 1} is missing a string 'id'. "
                "Add e.g. id = \"alkalinity\"."
            )
        if param_id in seen:
            warnings.append(
                f"Duplicate parameter id '{param_id}' — later definition ignored."
            )
            continue
        seen.add(param_id)

        display_name = raw.get("display_name") or raw.get("name") or param_id

        raw_units = raw.get("units", raw.get("unit"))
        if raw_units is None:
            units: tuple[str, ...] = ()
        elif isinstance(raw_units, str):
            units = (raw_units,)
        elif isinstance(raw_units, (list, tuple)):
            units = tuple(str(u) for u in raw_units)
        else:
            raise ConfigError(
                f"[[parameters]] '{param_id}': 'units' must be a string or list of strings."
            )

        where = f"[[parameters]] '{param_id}'"
        rng = _parse_range(raw.get("target_range", raw.get("range")), where=where)
        if rng is not None and not rng.is_valid:
            warnings.append(
                f"{where}: invalid target range min={rng.min} > max={rng.max}; "
                "no band will be shown. Fix so min <= max."
            )
            rng = None  # A parameter with no usable range is allowed (spec §5.5/§5.6).

        param_overrides = {
            tank_id: tank_params[param_id]
            for tank_id, tank_params in overrides.items()
            if param_id in tank_params
        }

        parameters.append(
            Parameter(
                id=param_id,
                display_name=str(display_name),
                units=units,
                target_range=rng,
                overrides=param_overrides,
                builtin=bool(raw.get("builtin", False)),
            )
        )
    return parameters


def load_config(
    config_path: str | Path | None = None,
    content_dirs: list[str | Path] | None = None,
) -> Config:
    """Load tanks, parameters, ranges and content directories from a TOML file.

    Args:
        config_path: Path to the TOML config. Defaults to the shipped
            :data:`DEFAULT_CONFIG_PATH`.
        content_dirs: Directories searched (in order) for per-parameter content
            files. Earlier entries override later ones, letting a user content
            dir take precedence over shipped defaults. Defaults to
            ``[DEFAULT_CONTENT_DIR]``.

    Returns:
        A :class:`Config`. Recoverable problems (inverted ranges, duplicate ids)
        are collected in :attr:`Config.warnings`; the app still runs.

    Raises:
        ConfigError: If the file is missing or the TOML is malformed / missing
            required fields. The message identifies the problem (spec §5.5).
    """
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH

    if not path.is_file():
        raise ConfigError(
            f"Config file not found: {path}. "
            "Create it (see config/fishy.toml) with [[tanks]] and [[parameters]] tables."
        )

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Could not parse config {path}: {exc}. "
            "Check for unclosed strings, missing '=' or mismatched brackets."
        ) from exc

    warnings: list[str] = []
    tanks = _parse_tanks(data, warnings)
    overrides = _parse_overrides(data, warnings)
    parameters = _parse_parameters(data, overrides, warnings)

    if content_dirs is not None:
        dirs = [Path(d) for d in content_dirs]
    else:
        dirs = [DEFAULT_CONTENT_DIR]

    return Config(
        tanks=tanks,
        parameters=parameters,
        warnings=warnings,
        content_dirs=dirs,
    )
