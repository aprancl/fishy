"""Tests for the tropical-reef visual theme (task #14, spec §6.4 / §6.5 / §9.4).

This is the final polish pass — a *theme* over the functionally-complete app.
The theme must make fishy feel bright, warm, lively and wonderful WITHOUT
regressing behaviour or, crucially, accessibility (spec §6.4):

  * Component     — themed chrome (header/footer/motifs, fonts) renders across
                    the shelf, parameter tabs and aggregate views; the palette +
                    typography live in the shared stylesheet.
  * Accessibility — out-of-range status is conveyed by MORE THAN COLOUR (badge
                    glyph + "Out of range" text in the DOM, a distinct marker
                    SHAPE in the charts); a visible keyboard-focus style exists;
                    motion is disabled under prefers-reduced-motion.
  * E2E-ish       — a single visual pass loads the shelf, a parameter tab and the
                    aggregate page and finds the cohesive theme on each.

The stylesheet + client JS are asserted by reading the static assets straight
off disk (they are static files, not template output). Rendered-DOM assertions
use the app test client with an injected Config + tmp readings path, so the real
data file is never touched.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import fishy
from fishy import create_app
from fishy.config import Config, Parameter, Tank, TargetRange
from fishy.storage import Reading, append_reading

_STATIC = Path(fishy.__file__).parent / "static"
_TEMPLATES = Path(fishy.__file__).parent / "templates"


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


def _css():
    return (_STATIC / "css" / "style.css").read_text(encoding="utf-8")


def _base_html():
    return (_TEMPLATES / "base.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Component: the palette + typography live in :root and are applied
# --------------------------------------------------------------------------- #
def test_palette_custom_properties_present():
    css = _css()
    # The cohesive tropical-reef palette (ocean/teal + warm coral/sun) lives in
    # :root custom properties, as established in task #1 and refined here.
    for var in (
        "--reef-deep",
        "--reef-teal",
        "--reef-coral",
        "--reef-sand",
        "--reef-ink",
        "--reef-muted",
    ):
        assert var in css, f"missing palette variable {var}"
    # Warm accents that give the theme its bright, lively feel.
    assert "--reef-sun" in css


def test_typography_font_family_defined_and_applied():
    css = _css()
    # A refined type scale: a display face + a legible body face, both as vars
    # with a system fallback so the app still looks right offline.
    assert "--reef-font-body" in css
    assert "--reef-font-display" in css
    assert "font-family: var(--reef-font-body)" in css
    # The web fonts are pulled from a CDN in the base <head>, with a fallback
    # stack in the CSS variables.
    base = _base_html()
    assert "fonts.googleapis.com" in base
    assert "system-ui" in css  # fallback stack present


# --------------------------------------------------------------------------- #
# Component: playful marine motifs are part of the theme (waves/bubbles/shells)
# --------------------------------------------------------------------------- #
def test_marine_motifs_present():
    css = _css()
    # A wave crest rides the header bottom edge and the footer carries a tide of
    # reef glyphs — tasteful marine motifs, not noise.
    assert ".reef-header::after" in css
    assert ".reef-footer::before" in css
    # Subtle drifting-bubble background wash on the page body.
    assert "radial-gradient" in css


# --------------------------------------------------------------------------- #
# Accessibility (§6.4): a visible keyboard-focus style exists for interactives
# --------------------------------------------------------------------------- #
def test_visible_keyboard_focus_styles_exist():
    css = _css()
    assert ":focus-visible" in css
    # A dedicated, high-visibility focus ring colour that is applied via outline.
    assert "--reef-focus" in css
    assert "outline" in css


# --------------------------------------------------------------------------- #
# Accessibility (§6.4): motion is disabled under prefers-reduced-motion
# --------------------------------------------------------------------------- #
def test_reduced_motion_respected():
    css = _css()
    assert "prefers-reduced-motion" in css


# --------------------------------------------------------------------------- #
# Accessibility (§6.4): theme is responsive at mobile-width windows
# --------------------------------------------------------------------------- #
def test_responsive_mobile_breakpoint_present():
    css = _css()
    assert "@media (max-width: 640px)" in css


# --------------------------------------------------------------------------- #
# Accessibility (§6.4): out-of-range is conveyed by MORE THAN COLOUR in the DOM
# --------------------------------------------------------------------------- #
def test_out_of_range_badge_uses_non_color_cue(tmp_path):
    client, path = _client(tmp_path)
    # Salinity target is 34–36 ppt; log a clearly out-of-range value.
    append_reading(
        Reading(
            tank="reef-a",
            parameter="salinity",
            date=dt.date(2026, 1, 1),
            value=48.0,
            unit="ppt",
        ),
        path=path,
    )
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    # The out-of-range signal carries a TEXT label + a glyph badge, not colour
    # alone — a colour-blind reader can still read the status.
    assert "reef-badge--out" in body
    assert "Out of range" in body


def test_in_range_badge_uses_non_color_cue(tmp_path):
    client, path = _client(tmp_path)
    append_reading(
        Reading(
            tank="reef-a",
            parameter="salinity",
            date=dt.date(2026, 1, 1),
            value=35.0,
            unit="ppt",
        ),
        path=path,
    )
    body = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "reef-badge--in" in body
    assert "In range" in body


# --------------------------------------------------------------------------- #
# Accessibility (§6.4): charts flag out-of-range with a distinct SHAPE, not
# only colour. The client renderer maps in/out-of-range points to marker
# symbols so the cue survives colour-blindness.
# --------------------------------------------------------------------------- #
def test_chart_js_uses_distinct_shape_for_out_of_range():
    js = (_STATIC / "js" / "chart.js").read_text(encoding="utf-8")
    assert "symbol" in js  # per-point marker symbol wired into the trace
    assert "OUT_RANGE_SYMBOL" in js
    assert "IN_RANGE_SYMBOL" in js
    # The out-of-range shape must differ from the in-range one.
    assert 'IN_RANGE_SYMBOL = "circle"' in js
    assert 'OUT_RANGE_SYMBOL = "triangle-up"' in js


def test_aggregate_js_uses_distinct_shape_for_out_of_range():
    js = (_STATIC / "js" / "aggregate.js").read_text(encoding="utf-8")
    assert "symbol" in js
    assert "OUT_RANGE_SYMBOL" in js
    assert 'IN_RANGE_SYMBOL = "circle"' in js
    assert 'OUT_RANGE_SYMBOL = "triangle-up"' in js


# --------------------------------------------------------------------------- #
# E2E-ish: the cohesive themed chrome renders across every top-level view
# --------------------------------------------------------------------------- #
def test_themed_chrome_renders_across_views(tmp_path):
    client, path = _client(tmp_path)
    append_reading(
        Reading(
            tank="reef-a",
            parameter="salinity",
            date=dt.date(2026, 1, 1),
            value=35.0,
            unit="ppt",
        ),
        path=path,
    )
    pages = [
        "/",  # shelf
        "/tank/reef-a",  # tank view (parameter tabs)
        "/tank/reef-a/parameter/salinity",  # a parameter tab
        "/tank/reef-a/aggregate",  # aggregate view
    ]
    for url in pages:
        resp = client.get(url)
        assert resp.status_code == 200, url
        body = resp.get_data(as_text=True)
        # Shared themed chrome + the theme's stylesheet on every page.
        assert "reef-header" in body, url
        assert "reef-footer" in body, url
        assert "css/style.css" in body, url
        # The tropical-reef web font is requested on every page (base.html head).
        assert "fonts.googleapis.com" in body, url


def test_aggregate_dense_view_stays_readable(tmp_path):
    """The dense aggregate history table keeps its scroll frame + out-of-range
    flag under the theme, so a large history stays legible."""
    client, path = _client(tmp_path)
    for day in range(1, 13):
        append_reading(
            Reading(
                tank="reef-a",
                parameter="salinity",
                date=dt.date(2026, 1, day),
                value=35.0 if day % 2 else 48.0,  # alternate in/out of range
                unit="ppt",
            ),
            path=path,
        )
    body = client.get("/tank/reef-a/aggregate").get_data(as_text=True)
    assert "reef-history__scroll" in body  # scroll frame keeps it contained
    assert "reef-history__row--out" in body  # out-of-range rows still flagged
    assert "Out of range" in body  # non-colour cue survives in the dense view
