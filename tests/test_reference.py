"""Tests for the reference & action-guide panel (task #10, spec §5.4).

Layering mirrors the rest of the suite:

  * Unit        — the Flask-free `render_markdown` helper (paragraphs, lists,
                  bold/italic, HTML-escaping of untrusted input) and the config
                  content-section parsing / placeholder fallback.
  * Component   — the parameter page renders all seven reference sections with
                  friendly labels, shows authored content, degrades unauthored
                  sections to gentle placeholders, and keeps the reference panel
                  *below* the chart + stats so it never obscures them.
  * Integration — editing a content file changes what the rendered tab shows.

Tests inject a ready-made :class:`Config` pointed at a tmp content dir (and a
tmp readings path) so they never touch the repo's real content/data files.
"""

from __future__ import annotations

from fishy import create_app
from fishy.config import Config, Parameter, Tank
from fishy.markdown import render_markdown


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _app(tmp_path, *, content=None, param_id="salinity", display="Salinity"):
    """Build an app whose content is read from a tmp dir (no real files)."""
    content_dir = tmp_path / "content"
    content_dir.mkdir(exist_ok=True)
    if content is not None:
        (content_dir / f"{param_id}.md").write_text(content, encoding="utf-8")
    config = Config(
        tanks=[Tank(id="reef-a", label="Reef A")],
        parameters=[Parameter(id=param_id, display_name=display, units=("ppt",))],
        content_dirs=[content_dir],
    )
    return create_app(
        {
            "TESTING": True,
            "FISHY_CONFIG": config,
            "FISHY_DATA_DIR": tmp_path,
        }
    )


def _get(tmp_path, **kw):
    param_id = kw.get("param_id", "salinity")
    app = _app(tmp_path, **kw)
    return app.test_client().get(f"/tank/reef-a/parameter/{param_id}")


# --------------------------------------------------------------------------- #
# Unit — markdown renderer
# --------------------------------------------------------------------------- #
def test_markdown_renders_bold():
    assert "<strong>salt</strong>" in render_markdown("The **salt** content.")


def test_markdown_renders_italic():
    assert "<em>stable</em>" in render_markdown("Keep it _stable_ over time.")


def test_markdown_renders_paragraphs():
    out = render_markdown("First para.\n\nSecond para.")
    assert out.count("<p>") == 2
    assert "<p>First para.</p>" in out


def test_markdown_renders_bullet_list():
    out = render_markdown("- one\n- two")
    assert "<ul>" in out and out.count("<li>") == 2
    assert "<li>one</li>" in out


def test_markdown_joins_wrapped_bullet_continuation():
    out = render_markdown("- add RO/DI water\n  slowly over hours")
    # The wrapped continuation line stays inside the same <li>, not a new block.
    assert out.count("<li>") == 1
    assert "add RO/DI water slowly over hours" in out


def test_markdown_escapes_untrusted_html():
    out = render_markdown("<script>alert('x')</script> and <b>raw</b>")
    assert "<script>" not in out
    assert "<b>raw</b>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_empty_input_is_empty_string():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


# --------------------------------------------------------------------------- #
# Unit — content parsing / placeholder fallback (config content layer)
# --------------------------------------------------------------------------- #
def test_content_for_authored_file_marks_sections_present(tmp_path):
    app = _app(
        tmp_path,
        content="## Definition\nSalt content of the water.\n",
    )
    content = app.config["FISHY_CONFIG"].content_for("salinity")
    assert content.is_present("definition")
    assert "Salt content" in content.get("definition")
    # ordered() always yields all seven canonical sections.
    assert len(content.ordered()) == 7


def test_content_for_missing_file_falls_back_to_placeholders(tmp_path):
    # No file and no _template.md in the dir → every section is a placeholder.
    app = _app(tmp_path, content=None, param_id="custom-thing")
    content = app.config["FISHY_CONFIG"].content_for("custom-thing")
    assert not any(content.is_present(key) for key, _, _ in content.ordered())
    assert len(content.ordered()) == 7


def test_content_for_partial_file_renders_present_and_placeholders(tmp_path):
    app = _app(tmp_path, content="## Definition\nOnly this section is filled.\n")
    content = app.config["FISHY_CONFIG"].content_for("salinity")
    assert content.is_present("definition")
    assert not content.is_present("remedies")  # absent → placeholder, no crash


# --------------------------------------------------------------------------- #
# Component — rendered reference panel
# --------------------------------------------------------------------------- #
FULL_CONTENT = """# Salinity

## Definition
Salinity is the **salt content** of the water.

## Measurement & Units
Measured as _specific gravity_ or ppt.

## Ideal Range
1.024–1.026 SG.

## When It's Too High
Dehydrates livestock.

## When It's Too Low
Swells cells and stresses osmoregulation.

## Signs & Symptoms
- Corals not extending polyps.
- Fish breathing hard.

## Suggested Remedies
- Add RO/DI water slowly.
"""

_FRIENDLY_LABELS = [
    "What it is",
    "How it&#39;s measured",  # apostrophe is HTML-escaped by Jinja autoescape
    "Ideal range",
    "Too high",
    "Too low",
    "Signs to watch for",
    "How to fix it",
]


def test_reference_panel_shows_all_seven_sections(tmp_path):
    html = _get(tmp_path, content=FULL_CONTENT).get_data(as_text=True)
    assert "Reference &amp; action guide" in html
    for label in _FRIENDLY_LABELS:
        assert label in html, f"missing reference label: {label}"


def test_reference_panel_renders_authored_markdown(tmp_path):
    html = _get(tmp_path, content=FULL_CONTENT).get_data(as_text=True)
    assert "<strong>salt content</strong>" in html
    assert "<em>specific gravity</em>" in html
    assert "<li>Corals not extending polyps.</li>" in html


def test_reference_panel_sits_below_chart_and_stats(tmp_path):
    """Layout must not obscure the data views — reference comes after them."""
    html = _get(tmp_path, content=FULL_CONTENT).get_data(as_text=True)
    chart_at = html.index('class="reef-chart"')
    stats_at = html.index('class="reef-stats"')
    ref_at = html.index('class="reef-reference"')
    assert chart_at < ref_at
    assert stats_at < ref_at


def test_reference_placeholder_for_undocumented_section(tmp_path):
    # Only definition authored → remedies etc. render as gentle placeholders.
    html = _get(tmp_path, content="## Definition\nJust a definition.\n").get_data(
        as_text=True
    )
    assert "Not documented yet" in html
    assert "content/salinity.md" in html
    # The panel still renders (no crash) and shows the authored section too.
    assert "Just a definition." in html


def test_custom_parameter_shows_fillable_placeholders(tmp_path):
    html = _get(tmp_path, content=None, param_id="nitrate", display="Nitrate").get_data(
        as_text=True
    )
    assert "Not documented yet" in html
    assert "content/nitrate.md" in html
    # All seven friendly labels still present for the custom parameter.
    for label in _FRIENDLY_LABELS:
        assert label in html


def test_reference_panel_escapes_untrusted_content(tmp_path):
    evil = "## Definition\n<script>alert('pwn')</script>\n"
    html = _get(tmp_path, content=evil).get_data(as_text=True)
    assert "<script>alert('pwn')</script>" not in html
    assert "&lt;script&gt;" in html


# --------------------------------------------------------------------------- #
# Integration — editing a content file changes the rendered tab
# --------------------------------------------------------------------------- #
def test_editing_content_file_changes_rendered_tab(tmp_path):
    app = _app(tmp_path, content="## Definition\nFirst version of the text.\n")
    client = app.test_client()

    first = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "First version of the text." in first

    # Edit the underlying content file (user override) and re-render.
    (tmp_path / "content" / "salinity.md").write_text(
        "## Definition\nSecond, edited version.\n", encoding="utf-8"
    )
    second = client.get("/tank/reef-a/parameter/salinity").get_data(as_text=True)
    assert "Second, edited version." in second
    assert "First version of the text." not in second
