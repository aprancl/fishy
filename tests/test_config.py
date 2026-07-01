"""Tests for the config & content loader (spec §9.1 / §5.4-5.6 / §7.4).

Covers the task-3 testing requirements:
  * Unit        — parse tanks, parameters, ranges, and content-file resolution.
  * Unit        — default fallback + user override precedence for content.
  * Integration — end-to-end load of the shipped config + content set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fishy import config as cfg
from fishy.config import (
    Config,
    ConfigError,
    Parameter,
    ParameterContent,
    TargetRange,
    load_config,
    load_content,
    parse_content,
)

BUILTIN_PARAM_IDS = {"salinity", "alkalinity", "calcium", "magnesium", "phosphate"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


MINIMAL_CONFIG = """
[[tanks]]
id = "reef-a"
label = "Reef A"

[[tanks]]
id = "nano"
label = "Nano Cube"

[[parameters]]
id = "alkalinity"
display_name = "Alkalinity"
units = ["dKH"]
target_range = { min = 8.0, max = 9.0 }

[[parameters]]
id = "salinity"
display_name = "Salinity / Specific Gravity"
units = ["sg", "ppt"]
target_range = { min = 1.024, max = 1.026 }
"""


# --------------------------------------------------------------------------- #
# Unit: parse tanks
# --------------------------------------------------------------------------- #
def test_loads_tank_list_with_id_and_label(tmp_path):
    conf = load_config(write(tmp_path / "c.toml", MINIMAL_CONFIG))
    assert [t.id for t in conf.tanks] == ["reef-a", "nano"]
    assert conf.tank("reef-a").label == "Reef A"
    assert conf.tank("nano").label == "Nano Cube"


def test_tank_label_defaults_to_id_when_omitted(tmp_path):
    text = '[[tanks]]\nid = "solo"\n\n[[parameters]]\nid = "ph"\n'
    conf = load_config(write(tmp_path / "c.toml", text))
    assert conf.tank("solo").label == "solo"


# --------------------------------------------------------------------------- #
# Unit: parse parameters, units, ranges
# --------------------------------------------------------------------------- #
def test_loads_parameters_with_units_and_range(tmp_path):
    conf = load_config(write(tmp_path / "c.toml", MINIMAL_CONFIG))
    alk = conf.parameter("alkalinity")
    assert alk.display_name == "Alkalinity"
    assert alk.units == ("dKH",)
    assert alk.default_unit == "dKH"
    assert alk.target_range == TargetRange(8.0, 9.0)

    sal = conf.parameter("salinity")
    assert sal.units == ("sg", "ppt")
    assert sal.default_unit == "sg"


def test_single_unit_string_is_accepted(tmp_path):
    text = '[[parameters]]\nid = "temp"\nunit = "C"\n'
    conf = load_config(write(tmp_path / "c.toml", text))
    assert conf.parameter("temp").units == ("C",)


def test_parameter_without_range_is_allowed(tmp_path):
    # Edge case: a parameter with no target range is valid (no band later).
    text = '[[parameters]]\nid = "nitrate"\ndisplay_name = "Nitrate"\nunits = ["ppm"]\n'
    conf = load_config(write(tmp_path / "c.toml", text))
    param = conf.parameter("nitrate")
    assert param.target_range is None
    assert conf.warnings == []


def test_one_sided_range_supported(tmp_path):
    text = '[[parameters]]\nid = "phosphate"\ntarget_range = { max = 0.1 }\n'
    conf = load_config(write(tmp_path / "c.toml", text))
    rng = conf.parameter("phosphate").target_range
    assert rng.min is None and rng.max == 0.1
    assert rng.contains(0.05) and not rng.contains(0.2)


# --------------------------------------------------------------------------- #
# Unit: adding a tank/parameter surfaces it without code changes
# --------------------------------------------------------------------------- #
def test_adding_tank_and_parameter_surfaces_without_code_change(tmp_path):
    base = load_config(write(tmp_path / "c.toml", MINIMAL_CONFIG))
    assert base.parameter("iron") is None

    extended = MINIMAL_CONFIG + (
        '\n[[tanks]]\nid = "sump"\nlabel = "Sump"\n'
        '\n[[parameters]]\nid = "iron"\ndisplay_name = "Iron"\nunits = ["ppb"]\n'
    )
    conf = load_config(write(tmp_path / "c.toml", extended))
    assert conf.tank("sump").label == "Sump"
    assert conf.parameter("iron").display_name == "Iron"


# --------------------------------------------------------------------------- #
# Unit: per-tank override precedence (spec §5.5)
# --------------------------------------------------------------------------- #
def test_per_tank_override_takes_precedence_over_default(tmp_path):
    text = MINIMAL_CONFIG + (
        "\n[overrides.reef-a.alkalinity]\nmin = 8.2\nmax = 8.8\n"
    )
    conf = load_config(write(tmp_path / "c.toml", text))
    alk = conf.parameter("alkalinity")
    # reef-a has an override; nano and unknown tanks fall back to the default.
    assert alk.range_for_tank("reef-a") == TargetRange(8.2, 8.8)
    assert alk.range_for_tank("nano") == TargetRange(8.0, 9.0)
    assert alk.range_for_tank(None) == TargetRange(8.0, 9.0)


# --------------------------------------------------------------------------- #
# TargetRange behavior
# --------------------------------------------------------------------------- #
def test_target_range_validity_and_containment():
    good = TargetRange(1.0, 2.0)
    assert good.is_valid and not good.is_empty
    assert good.contains(1.5) and not good.contains(2.5)

    inverted = TargetRange(9.0, 8.0)
    assert not inverted.is_valid
    # An invalid range flags nothing (contains everything).
    assert inverted.contains(100)

    empty = TargetRange()
    assert empty.is_empty and empty.is_valid and empty.contains(42)


# --------------------------------------------------------------------------- #
# Error handling: invalid range -> warning, app still runs
# --------------------------------------------------------------------------- #
def test_invalid_range_min_gt_max_surfaces_warning_not_error(tmp_path):
    text = (
        '[[parameters]]\nid = "alkalinity"\n'
        "target_range = { min = 9.0, max = 8.0 }\n"
    )
    conf = load_config(write(tmp_path / "c.toml", text))
    # App still runs: a Config is returned with a clear warning.
    assert isinstance(conf, Config)
    assert conf.warnings, "expected a warning about the inverted range"
    assert "invalid" in conf.warnings[0].lower()
    # The offending parameter loses its band but still loads.
    assert conf.parameter("alkalinity").target_range is None


def test_invalid_override_range_warns_and_is_ignored(tmp_path):
    text = MINIMAL_CONFIG + (
        "\n[overrides.reef-a.alkalinity]\nmin = 10\nmax = 9\n"
    )
    conf = load_config(write(tmp_path / "c.toml", text))
    assert any("invalid range" in w.lower() for w in conf.warnings)
    # Override ignored -> falls back to the parameter default.
    assert conf.parameter("alkalinity").range_for_tank("reef-a") == TargetRange(8.0, 9.0)


# --------------------------------------------------------------------------- #
# Error handling: malformed / missing config -> actionable ConfigError
# --------------------------------------------------------------------------- #
def test_missing_config_file_raises_actionable_error(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "does-not-exist.toml")
    assert "not found" in str(exc.value).lower()


def test_malformed_toml_raises_actionable_error(tmp_path):
    bad = write(tmp_path / "c.toml", '[[tanks]]\nid = "reef-a"\nlabel = "oops\n')
    with pytest.raises(ConfigError) as exc:
        load_config(bad)
    msg = str(exc.value)
    assert str(bad) in msg  # identifies the file
    assert "parse" in msg.lower()


def test_parameter_missing_id_raises_actionable_error(tmp_path):
    bad = write(tmp_path / "c.toml", '[[parameters]]\ndisplay_name = "No Id"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(bad)
    assert "id" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# Content parsing
# --------------------------------------------------------------------------- #
def test_parse_content_splits_named_sections():
    md = (
        "# Title\n\nintro\n\n"
        "## Definition\nsalt content\n\n"
        "## Ideal Range\n1.025 SG\n"
    )
    parsed = parse_content(md)
    assert parsed["definition"] == "salt content"
    assert parsed["ideal_range"] == "1.025 SG"


def test_parse_content_accepts_heading_aliases():
    md = "## What It Is\na thing\n\n## Target Range\nsome band\n"
    parsed = parse_content(md)
    assert parsed["definition"] == "a thing"
    assert parsed["ideal_range"] == "some band"


# --------------------------------------------------------------------------- #
# Content resolution: present sections load, absent -> placeholders
# --------------------------------------------------------------------------- #
def test_partial_content_file_yields_placeholders_not_errors(tmp_path):
    write(tmp_path / "calcium.md", "## Definition\nca is a thing\n")
    content = load_content("calcium", [tmp_path])
    assert isinstance(content, ParameterContent)
    # Present section loads verbatim...
    assert content.get("definition") == "ca is a thing"
    assert content.is_present("definition")
    # ...absent sections become gentle placeholders, not errors.
    assert not content.is_present("remedies")
    assert "provided yet" in content.get("remedies").lower()


def test_missing_content_file_falls_back_to_template(tmp_path):
    write(tmp_path / "_template.md", "## Definition\n_fill me in_\n")
    content = load_content("mystery", [tmp_path])
    # Template supplies structure but counts as unauthored (all placeholders).
    assert content.present == frozenset()
    assert content.source.name == "_template.md"


def test_missing_file_and_no_template_still_returns_placeholders(tmp_path):
    content = load_content("ghost", [tmp_path])
    assert content.source is None
    for key, _heading, text in content.ordered():
        assert not content.is_present(key)
        assert "provided yet" in text.lower()


# --------------------------------------------------------------------------- #
# Content precedence: user dir overrides shipped defaults
# --------------------------------------------------------------------------- #
def test_user_content_dir_overrides_default(tmp_path):
    default_dir = tmp_path / "default"
    user_dir = tmp_path / "user"
    write(default_dir / "salinity.md", "## Definition\nshipped default text\n")
    write(user_dir / "salinity.md", "## Definition\nmy custom text\n")

    # user_dir listed first -> it wins.
    content = load_content("salinity", [user_dir, default_dir])
    assert content.get("definition") == "my custom text"
    assert content.source == user_dir / "salinity.md"


def test_falls_back_to_default_when_user_file_absent(tmp_path):
    default_dir = tmp_path / "default"
    user_dir = tmp_path / "user"
    write(default_dir / "salinity.md", "## Definition\nshipped default text\n")
    user_dir.mkdir()

    content = load_content("salinity", [user_dir, default_dir])
    assert content.get("definition") == "shipped default text"
    assert content.source == default_dir / "salinity.md"


# --------------------------------------------------------------------------- #
# Integration: end-to-end load of the shipped config + content set
# --------------------------------------------------------------------------- #
def test_shipped_config_loads_builtin_reef_set():
    conf = load_config()  # uses shipped DEFAULT_CONFIG_PATH
    ids = {p.id for p in conf.parameters}
    assert BUILTIN_PARAM_IDS <= ids
    assert conf.warnings == []
    assert conf.tanks, "shipped config should define at least one tank"
    # Every built-in ships a usable default range.
    for pid in BUILTIN_PARAM_IDS:
        param = conf.parameter(pid)
        assert param.builtin is True
        assert param.target_range is not None
        assert param.target_range.is_valid


def test_shipped_content_resolves_for_every_builtin_parameter():
    conf = load_config()
    for pid in BUILTIN_PARAM_IDS:
        content = conf.content_for(pid)
        # Curated shipped content authors the core sections.
        assert content.is_present("definition"), f"{pid} missing definition"
        assert content.is_present("ideal_range"), f"{pid} missing ideal range"
        assert content.is_present("remedies"), f"{pid} missing remedies"
        assert content.source is not None


def test_shipped_default_paths_exist():
    assert cfg.DEFAULT_CONFIG_PATH.is_file()
    assert cfg.DEFAULT_CONTENT_DIR.is_dir()
    assert (cfg.DEFAULT_CONTENT_DIR / cfg.TEMPLATE_FILENAME).is_file()
