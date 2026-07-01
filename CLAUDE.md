# CLAUDE.md — fishy

Guidance for AI agents and contributors working in this repository. Keep it
current as the project evolves.

## What this is

**fishy** is a personal, local-first web app for reef aquarists to log dated
water-parameter readings and visualize them. It runs on localhost; all reading
state lives in a single git-trackable CSV. No accounts, no cloud, no database
server. Scope is intentionally narrow. Full spec: `specs/fishy-SPEC.md`.

## Tech stack (Phase 1 decisions — do not change without updating the spec)

- **Language**: Python 3 (developed against 3.14; targets 3.10+ syntax).
- **Web framework**: **Flask** — minimal footprint, single-command run,
  built-in Jinja2 server-rendered templates. Chosen over FastAPI, which is
  optimised for async JSON APIs and needs a separate ASGI server.
- **Charting**: **Plotly.js** loaded from a **CDN** (client-side only). Supports
  shaded target-range bands, multi-series overlays, and legend toggling with an
  attractive default look. There is **no Python charting dependency**.
- **Storage**: plain-text **CSV** (long/tidy: one row per reading) plus
  human-editable config/content files. Git-friendly, append-only writes.
- **Tests**: **pytest**.

## Run & test commands

```bash
python -m pip install -r requirements.txt       # runtime deps (Flask)
python app.py                                    # start server on 127.0.0.1:5000

python -m pip install -r requirements-dev.txt    # dev deps (adds pytest)
python -m pytest                                 # run the test suite
```

Environment overrides: `FISHY_HOST` (default `127.0.0.1`), `FISHY_PORT`
(default `5000`).

## Project structure & conventions

```
app.py            Entry point. Thin: dependency-missing + port-in-use guards,
                  reads FISHY_HOST/FISHY_PORT, calls create_app().run().
fishy/__init__.py Application factory create_app(config=None) -> Flask.
                  Register new routes inside _register_routes(app); prefer
                  Flask blueprints as features grow.
fishy/templates/  Jinja2 templates. All pages extend base.html.
fishy/static/     CSS/JS. Tropical-reef palette lives in css/style.css :root vars.
tests/            pytest. test_app.py demonstrates the unit/integration/smoke
                  layering: factory returns app, test_client for routes,
                  subprocess launch for the localhost smoke test.
```

Conventions to follow in later tasks:

- **App factory pattern**: build everything via `create_app()`; never rely on a
  module-level global app. Tests pass `{"TESTING": True}`.
- **Localhost-only**: always bind `127.0.0.1` by default (spec §6.2 / §7.5).
  `app.py:DEFAULT_HOST` is the single source of truth.
- **Minimal dependencies** (spec §7.5): justify any new runtime dependency; the
  default is to add none. Prefer standard library and client-side CDN assets.
- **Actionable errors**: user-facing failures (missing deps, port in use, bad
  CSV rows) print a clear instruction, not a stack trace.
- **Templates**: extend `base.html`; keep the tropical-reef aesthetic; convey
  status by more than color alone (icon/badge/label) for accessibility (§6.4).
- **File is source of truth**: CSV/config/content are plain-text and
  hand-editable; writes stay append-only with stable column order (§7.4/§7.5).

## Modules & key seams (as built)

Pure data layers (no Flask import) — read state ONLY through these:

- **`fishy/storage.py`** — long/tidy CSV persistence. `Reading(tank,parameter,date,value,unit,note)`, `load_readings(path) -> LoadResult(.readings/.warnings/.first_run)`, `append_reading/append_readings`, `ensure_file`. Value formatter `_format_value` (compact `8` not `8.0`) is reused everywhere numbers render. Columns: `tank,parameter,date,value,unit,note`. Default `data/readings.csv` (created on first append).
- **`fishy/config.py`** — TOML config (`config/fishy.toml`) + markdown content (`content/<param>.md`, `content/_template.md`). `load_config() -> Config`; `Config.tank(id)`, `.parameter(id)`, `.parameters`, `.content_for(id)`, `.warnings`. `Parameter.default_unit` (first unit = canonical), `.range_for_tank(tank_id)` (per-tank override → default). `TargetRange(min,max).contains(v)` handles one-sided/None. Content section keys/order: `definition, measurement, ideal_range, too_high, too_low, signs, remedies`.
- **`fishy/markdown.py`** — `render_markdown(text)` safe subset renderer; wired as the `{{ text | markdown }}` Jinja filter (no new dep; escapes first).

Flask layer — `fishy/__init__.py`:

- **Config/storage wiring**: `create_app()` puts `Config` on `app.config["FISHY_CONFIG"]`; readings path at `app.config["FISHY_READINGS_PATH"]`. Tests inject both to use tmp data.
- **Routes**: `index` (`/` shelf), `tank_view` (`/tank/<tank_id>`), `parameter_view` (`/tank/<tank_id>/parameter/<param_id>`, GET) + `add_reading` (POST `.../reading`, PRG pattern), `aggregate_view` (`/tank/<tank_id>/aggregate`), `health`. Active tank = URL path param.
- **Reusable Flask-free helpers** (unit-tested, share these — don't re-load/re-sort readings):
  - `_range_for(parameter, tank_id)` — THE single range-resolution seam (per-tank → default → None). Change range behavior here only.
  - `_chart_series(readings, parameter, tank_id)` — canonical series `{range, unit, points:[{date,value,in_range}]}` (sorted, classified). `_classify_in_range(value, range)`.
  - `_parameter_stats(points, *, unit)` — latest/badge/trend/min/max/avg/days-since.
  - `_normalize`, `_aggregate_series`, `_aggregate_cards`, `_history_rows`, `_load_warnings` (surfaces `LoadResult.warnings` as a non-fatal notice).

Templates & CSS conventions:

- Parameter page seams (`parameter.html` panel): `.reef-chart` / `.reef-stats` / `.reef-reference` (each `data-parameter-id`). Tab nav = `_param_tabs.html` (links; `is-active` + `aria-current`). Aggregate = `aggregate.html` (`.reef-aggregate__history` holds the table).
- Status/state classes (kept stable — tests assert them): `.reef-badge--in/--out`, `.reef-history__row--out`, `.reef-empty` (+`--inline`), `.reef-notice--warn`, `.reef-stat`, `.reef-trend`.
- Charts (`static/js/chart.js`, `aggregate.js`): in-range teal `#01baef` / out-of-range coral `#e4572e`, and out-of-range also uses a distinct marker SHAPE (non-color cue per §6.4). Inline JSON contract (`{{ ... | tojson }}`), no data endpoints.

## Type hints & style

- Use `from __future__ import annotations` and standard type hints.
- Docstrings on public functions; comment the "why", not the "what".
