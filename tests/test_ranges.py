"""Tests for target-range defaults and per-tank overrides (task #9, spec §5.5).

Task #9 is the resolution layer that decides *which* target range applies to a
given tank+parameter and makes that resolved range drive both the chart's
shaded band and out-of-range highlighting everywhere. The building blocks were
shipped earlier:

  * ``fishy.config`` already parses default ranges + per-tank overrides and
    surfaces resolution via :meth:`Parameter.range_for_tank` (task #3).
  * ``fishy.__init__._range_for`` is the single centralized "which range
    applies" seam every chart/stats consumer flows through (task #7).

The core of task #9 is a one-line change to ``_range_for`` so it delegates to
``range_for_tank`` — these tests lock in the resulting behaviour end to end.

Layering mirrors the rest of the suite:

  * Unit        — resolution precedence (per-tank > per-parameter default) and
                  in/out-of-range classification for one-sided / missing ranges,
                  all Flask-free.
  * Error       — an inverted (min > max) override/default surfaces a config
                  warning, and the app still serves the page.
  * Integration — a per-tank override changes the serialized ``chart_data``
                  band + highlighting for that tank vs. another tank.

Tests inject a ready-made :class:`Config` (and a tmp readings path) so they
never touch the repo's real data file, except where they explicitly exercise
the shipped ``config/fishy.toml`` to prove the demonstrable override.
"""

from __future__ import annotations

import datetime as dt
import json

from fishy import _chart_series, _classify_in_range, _range_for, create_app
from fishy.config import (
    Config,
    Parameter,
    Tank,
    TargetRange,
    load_config,
)
from fishy.storage import Reading, append_reading


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _param_with_override():
    """A parameter whose ``frag-tank`` overrides the default alkalinity band."""
    return Parameter(
        id="alkalinity",
        display_name="Alkalinity",
        units=("dKH",),
        target_range=TargetRange(min=8.0, max=9.0),
        overrides={"frag-tank": TargetRange(min=8.2, max=8.8)},
    )


def _reading(param, value, day, *, tank, unit="dKH"):
    return Reading(
        tank=tank,
        parameter=param,
        date=dt.date(2024, 1, day),
        value=value,
        unit=unit,
    )


def _chart_json(body):
    """Extract the inline JSON chart contract from a rendered parameter page."""
    marker = '<script type="application/json" class="reef-chart-data">'
    start = body.index(marker) + len(marker)
    end = body.index("</script>", start)
    return json.loads(body[start:end])


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


_MINIMAL = (
    '[[tanks]]\nid = "reef-a"\nlabel = "Reef A"\n'
    '[[tanks]]\nid = "frag-tank"\nlabel = "Frag Tank"\n'
    '[[parameters]]\nid = "alkalinity"\ndisplay_name = "Alkalinity"\n'
    'units = ["dKH"]\nbuiltin = true\ntarget_range = { min = 8.0, max = 9.0 }\n'
)


# --------------------------------------------------------------------------- #
# Unit: resolution precedence (per-tank > per-parameter default)
# --------------------------------------------------------------------------- #
def test_range_for_uses_per_tank_override_when_present():
    param = _param_with_override()
    # frag-tank has a tighter override; it must win over the default band.
    assert _range_for(param, "frag-tank") == TargetRange(8.2, 8.8)


def test_range_for_falls_back_to_default_without_override():
    param = _param_with_override()
    # reef-a has no override → resolves to the parameter default.
    assert _range_for(param, "reef-a") == TargetRange(8.0, 9.0)
    # An unrelated / unknown tank id also falls back to the default.
    assert _range_for(param, "sump") == TargetRange(8.0, 9.0)
    # A None tank id (aggregate contexts) still yields the default.
    assert _range_for(param, None) == TargetRange(8.0, 9.0)


def test_range_for_none_when_no_default_and_no_override():
    # Custom parameter with no range → no band anywhere, even per-tank.
    param = Parameter(id="ph", display_name="pH")
    assert _range_for(param, "reef-a") is None
    assert _range_for(param, "frag-tank") is None


def test_range_resolution_precedence_matches_config_layer():
    # The centralized seam must agree with the pure config resolver it delegates
    # to (per-tank override else default).
    param = _param_with_override()
    for tank_id in ("frag-tank", "reef-a", "sump", None):
        assert _range_for(param, tank_id) == param.range_for_tank(tank_id)


# --------------------------------------------------------------------------- #
# Unit: in/out-of-range classification for one-sided and missing ranges
# --------------------------------------------------------------------------- #
def test_classification_uses_the_resolved_per_tank_range():
    param = _param_with_override()
    # 8.9 is inside the default (8.0–9.0) but OUTSIDE the frag-tank override
    # (8.2–8.8): the same value is classified differently per tank.
    assert _classify_in_range(8.9, _range_for(param, "reef-a")) is True
    assert _classify_in_range(8.9, _range_for(param, "frag-tank")) is False


def test_classification_one_sided_lower_bound_only():
    # Only a lower bound → highlighting applies to the lower side only.
    rng = TargetRange(min=8.0, max=None)
    assert _classify_in_range(7.9, rng) is False
    assert _classify_in_range(8.0, rng) is True
    assert _classify_in_range(50.0, rng) is True


def test_classification_one_sided_upper_bound_only():
    # Only an upper bound → highlighting applies to the upper side only.
    rng = TargetRange(min=None, max=0.03)
    assert _classify_in_range(0.02, rng) is True
    assert _classify_in_range(0.03, rng) is True
    assert _classify_in_range(0.04, rng) is False


def test_classification_missing_range_flags_nothing():
    # No range → nothing is ever out of range.
    assert _classify_in_range(-1000.0, None) is True
    assert _classify_in_range(1000.0, None) is True


# --------------------------------------------------------------------------- #
# Unit: the serialized chart band reflects the resolved (per-tank) range
# --------------------------------------------------------------------------- #
def test_chart_series_band_reflects_per_tank_override():
    param = _param_with_override()
    readings = [_reading("alkalinity", 8.9, 1, tank="frag-tank")]
    series = _chart_series(readings, param, "frag-tank")
    assert series["range"] == {"min": 8.2, "max": 8.8}
    # 8.9 is above the tightened frag-tank band → flagged out of range.
    assert series["points"][0]["in_range"] is False


def test_chart_series_band_reflects_default_for_tank_without_override():
    param = _param_with_override()
    readings = [_reading("alkalinity", 8.9, 1, tank="reef-a")]
    series = _chart_series(readings, param, "reef-a")
    assert series["range"] == {"min": 8.0, "max": 9.0}
    # 8.9 sits inside the default band for reef-a → in range.
    assert series["points"][0]["in_range"] is True


def test_chart_series_custom_param_no_range_still_plots():
    # Custom parameter with no range: data still plots, no band, nothing flagged.
    param = Parameter(id="ph", display_name="pH", units=("",))
    readings = [_reading("ph", 8.1, 1, tank="reef-a", unit="")]
    series = _chart_series(readings, param, "reef-a")
    assert series["range"] == {"min": None, "max": None}
    assert len(series["points"]) == 1  # data still plotted
    assert series["points"][0]["in_range"] is True  # nothing flagged


# --------------------------------------------------------------------------- #
# Error handling: invalid range (min > max) warns; app still runs
# --------------------------------------------------------------------------- #
def test_invalid_default_range_warns_and_yields_no_band(tmp_path):
    text = (
        '[[tanks]]\nid = "reef-a"\nlabel = "Reef A"\n'
        '[[parameters]]\nid = "alkalinity"\ndisplay_name = "Alkalinity"\n'
        "target_range = { min = 9.0, max = 8.0 }\n"  # inverted
    )
    conf = load_config(_write(tmp_path / "c.toml", text))
    assert any("invalid" in w.lower() for w in conf.warnings)
    # The recoverable problem drops the band but does not raise.
    assert conf.parameter("alkalinity").target_range is None


def test_invalid_override_range_warns_and_falls_back(tmp_path):
    text = _MINIMAL + "\n[overrides.frag-tank.alkalinity]\nmin = 9.0\nmax = 8.0\n"
    conf = load_config(_write(tmp_path / "c.toml", text))
    assert any("invalid range" in w.lower() for w in conf.warnings)
    alk = conf.parameter("alkalinity")
    # Invalid override is ignored → frag-tank falls back to the valid default.
    assert alk.range_for_tank("frag-tank") == TargetRange(8.0, 9.0)


def test_app_still_serves_page_with_invalid_range_config(tmp_path):
    # An inverted default range must not stop the app from serving the page.
    param = Parameter(
        id="alkalinity",
        display_name="Alkalinity",
        units=("dKH",),
        target_range=None,  # loader drops an inverted range to None + warns
    )
    config = Config(
        tanks=[Tank(id="reef-a", label="Reef A")],
        parameters=[param],
        warnings=["[[parameters]] 'alkalinity': invalid target range ..."],
    )
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_READINGS_PATH": tmp_path / "readings.csv",
        }
    )
    resp = app.test_client().get("/tank/reef-a/parameter/alkalinity")
    assert resp.status_code == 200
    contract = _chart_json(resp.get_data(as_text=True))
    assert contract["range"] == {"min": None, "max": None}


# --------------------------------------------------------------------------- #
# Integration: an override changes chart band + highlighting for that tank only
# --------------------------------------------------------------------------- #
def _override_client(tmp_path):
    config = Config(
        tanks=[Tank(id="reef-a", label="Reef A"), Tank(id="frag-tank", label="Frag Tank")],
        parameters=[_param_with_override()],
    )
    readings_path = tmp_path / "readings.csv"
    app = create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_READINGS_PATH": readings_path,
        }
    )
    return app.test_client(), readings_path


def test_override_changes_serialized_band_between_tanks(tmp_path):
    client, readings_path = _override_client(tmp_path)
    # Same value logged in both tanks; only the band differs by tank.
    append_reading(_reading("alkalinity", 8.9, 1, tank="reef-a"), readings_path)
    append_reading(_reading("alkalinity", 8.9, 1, tank="frag-tank"), readings_path)

    reef = _chart_json(
        client.get("/tank/reef-a/parameter/alkalinity").get_data(as_text=True)
    )
    frag = _chart_json(
        client.get("/tank/frag-tank/parameter/alkalinity").get_data(as_text=True)
    )

    # Band differs: default for reef-a, tightened override for frag-tank.
    assert reef["range"] == {"min": 8.0, "max": 9.0}
    assert frag["range"] == {"min": 8.2, "max": 8.8}

    # Highlighting differs consistently with the band: 8.9 is in range for
    # reef-a but out of range for frag-tank.
    assert reef["points"][0]["in_range"] is True
    assert frag["points"][0]["in_range"] is False


def test_override_reflected_in_latest_value_badge(tmp_path):
    # The stats/latest badge consumes the same classified points, so the badge
    # must reflect the per-tank range too.
    client, readings_path = _override_client(tmp_path)
    append_reading(_reading("alkalinity", 8.9, 1, tank="frag-tank"), readings_path)

    body = client.get("/tank/frag-tank/parameter/alkalinity").get_data(as_text=True)
    contract = _chart_json(body)
    # The latest point (fed to the stats badge) is out of range for frag-tank.
    assert contract["points"][-1]["in_range"] is False


def test_shipped_config_demonstrates_per_tank_override(tmp_path):
    # The shipped config must make precedence demonstrable: frag-tank tightens
    # alkalinity while reef-a keeps the default — and it introduces no warnings.
    conf = load_config()  # real config/fishy.toml
    assert conf.warnings == []
    alk = conf.parameter("alkalinity")
    assert alk is not None
    frag = alk.range_for_tank("frag-tank")
    reef = alk.range_for_tank("reef-a")
    assert frag != reef, "shipped config should demonstrate a per-tank override"
    assert frag.min >= reef.min and frag.max <= reef.max  # a tighter band
