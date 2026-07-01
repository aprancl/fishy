# Execution Context

## Project Patterns
- **Language**: Python 3 (env has 3.14). Use `from __future__ import annotations` + type hints. Docstrings on public functions.
- **App factory pattern**: `fishy.create_app(config: dict | None = None) -> Flask`. NEVER use a module-level global app. Tests pass `{"TESTING": True}`.
- **Route registration**: add routes inside `fishy/__init__.py::_register_routes(app)`. Prefer Flask blueprints as features grow.
- **Templates**: Jinja2 under `fishy/templates/`; all pages extend `base.html`. Tropical-reef aesthetic; palette CSS vars live in `fishy/static/css/style.css` `:root`.
- **Actionable errors**: user-facing failures print a clear instruction + `raise SystemExit(1)`, never a stack trace.
- **Minimal deps**: default is add NO new runtime dependency. Charting is client-side Plotly.js via CDN (no Python charting lib). Config uses stdlib tomllib. Storage uses stdlib csv. Justify any new runtime dep in requirements.txt.
- **Localhost-only**: `app.py:DEFAULT_HOST = "127.0.0.1"` is the single source of truth. Overridable via env `FISHY_HOST` / `FISHY_PORT`.
- **Data layers are pure**: `fishy/storage.py` (readings) and `fishy/config.py` (config/content) import no Flask. Read reading state ONLY through `fishy.storage`; read tanks/params/content ONLY through `fishy.config`.
- **Tests**: pytest under `tests/`, one file per module (`tests/test_<module>.py`). Full suite currently 60 tests, run `python -m pytest`.

## Key Decisions
- **Web framework = Flask**; **Charting = Plotly.js from CDN** (client-side; shaded bands via layout `shapes`/`fill`, multi-series overlays, legend toggle).
- **Storage = long/tidy CSV** at `data/readings.csv`, one row per reading, columns `tank,parameter,date,value,unit,note`. Append-only, stdlib `csv`, QUOTE_MINIMAL. File created on first append (not on load).
- **Config = TOML** (`config/fishy.toml`, stdlib `tomllib`) + **content = markdown** (`content/<param>.md`, `## Heading` sections). Zero new deps (resolves Open Question #2). Ships 2 tanks + 5 reef params with ranges + curated reference content + `content/_template.md`.
- **CONFIG NOW WIRED (task #4).** `create_app()` calls `load_config()` once and stores the `Config` on `app.config["FISHY_CONFIG"]`. In a view: `config: Config = app.config["FISHY_CONFIG"]`. Tests inject a ready-made Config to avoid disk: `create_app({"TESTING": True, "FISHY_CONFIG": Config(tanks=[Tank(...)])})`.
- **STORAGE NOW WIRED (task #5).** Readings CSV path = `app.config["FISHY_READINGS_PATH"]` (default `fishy.storage.DEFAULT_READINGS_PATH`). Read/append via pure `fishy.storage` passing that path. Tests inject a tmp path: `create_app({"TESTING": True, "FISHY_CONFIG": ..., "FISHY_READINGS_PATH": tmp_path/"readings.csv"})` — NEVER touch the real `data/readings.csv` in tests. Downstream (#7/#8/#13/#15) read this same key.
- **Form/POST conventions (task #5):** routes `parameter_view` (GET `/tank/<tank_id>/parameter/<param_id>`) and `add_reading` (POST `.../reading`). **PRG pattern**: successful POST → 302 redirect to the GET page; validation failure → re-render `parameter.html` with `error=`/`form=` at HTTP 400, nothing written. Value must be non-empty + `float()`-parseable; date optional (defaults `date.today()`, ISO override for back-dating); note free-text (storage handles CSV quoting — never re-implement). Display values via `reading.to_row()['value']` to avoid `8.0`.
- **Form embed for #6:** `{% include "_add_reading_form.html" %}` with `active_tank`, `parameter`, `today` (ISO str) in scope; optional `error`/`form` for re-render. Shared renderer `_render_parameter(active_tank, parameter, error=, form=, status=)` in `_register_routes`. `parameter.html` also has reusable readings-table markup.

## ACTIVE-TANK CONVENTION (task #4 — reuse in #5/#6/#15)
- **Active tank = URL PATH PARAM `/tank/<tank_id>`** — stateless, bookmarkable, single source of truth. Resolve via `config.tank(tank_id)`; `abort(404)` when None (route `tank_view` already does this).
- Route function names: `index` (shelf `/`), `tank_view` (`/tank/<tank_id>`), `health`. Use `url_for('tank_view', tank_id=...)` / `url_for('index')` in templates.
- Templates receive `tanks` (full list) and `active_tank` (scoped `Tank`). Common chrome merged via `_shell(**extra)` helper in `_register_routes`.
- **Tank View shell = `fishy/templates/tank.html`.** Task #6 fills the placeholder `<div class="reef-card reef-tabs-placeholder">` inside `<section class="reef-tankview" data-tank-id="{{ active_tank.id }}">` with parameter tabs. `data-tank-id` is the DOM hook. Switcher = `<nav class="reef-switcher">`, active marked `is-active` + `aria-current="page"`.
- Add-reading (#5) should link/scope using `active_tank.id`.

## Storage API (fishy/storage.py) — use verbatim
- Constants: `COLUMNS = ("tank","parameter","date","value","unit","note")`, `DEFAULT_READINGS_PATH = data/readings.csv`, `DEFAULT_DATA_DIR = Path("data")`.
- `Reading` frozen dataclass: `tank:str, parameter:str, date:datetime.date, value:float, unit:str, note:str=""`. Methods: `.to_row()`, `.to_cells()`, `Reading.from_row(mapping)` (raises `ReadingError`).
- `LoadResult`: `.readings`, `.warnings` (list of "row {n}: skipped — {reason}"), `.first_run` (bool).
- `load_readings(path=DEFAULT_READINGS_PATH, *, emit_warnings=True) -> LoadResult` (NO side effects; missing file → first_run=True, not created).
- `append_reading(reading, path=...)`, `append_readings(iterable, path=...) -> int`, `ensure_file(path) -> bool`.
- Value formatting: whole numbers compact (8 not 8.0), else shortest round-tripping repr (1.026, 0.08 exact).

## Config API (fishy/config.py) — use verbatim
- `load_config(config_path=None, content_dirs=None) -> Config`. Defaults: `DEFAULT_CONFIG_PATH`, `DEFAULT_CONTENT_DIR`. Pass `content_dirs=[user_dir, default_dir]` for override precedence (first match wins).
- `Config`: `.tank(id)`, `.parameter(id)`, `.tanks_by_id`, `.parameters_by_id`, `.content_for(param_id)`, `.warnings`. Raises `ConfigError` on missing file / malformed TOML / missing required id.
- `Tank(id, label)`.
- `Parameter(id, display_name, units, target_range, overrides, builtin)` — `.default_unit`, `.range_for_tank(tank_id)`.
- `TargetRange(min, max)` — `.is_valid`, `.is_empty`, `.contains(v)`.
- `ParameterContent` — `.get(key)`, `.is_present(key)`, `.ordered()`. Section keys/order: `definition, measurement, ideal_range, too_high, too_low, signs, remedies` (SECTION_ORDER). `_template.md` sections count as NOT present (placeholders).
- Per-tank range overrides in TOML: `[overrides.<tank-id>.<param-id>]` with min/max.

## TAB MODEL & CONTENT-REGION SEAMS (task #6 — for #7/#8/#10/#11/#12/#13)
- **Tab model = server-rendered LINKS** in `fishy/templates/_param_tabs.html`: `<nav class="reef-tabs">` with one `<a class="reef-tabs__link" data-param-id=... href="/tank/<tank_id>/parameter/<param_id>">` per configured parameter + a trailing Aggregate slot. Active tab = `is-active` + `aria-current="page"`. The **per-parameter page `parameter.html` (route `parameter_view`) IS the tab panel** — no in-page JS switching. tank_id stays in URL → switching preserves active tank.
- Partial context vars (already supplied by `tank_view` and `_render_parameter`): `active_tank`, `parameters` (= `config.parameters`), `active_param` (id or None), `active_tab` ("aggregate" or None).
- **Fill these EXACT empty seams inside `parameter.html`'s `<div class="reef-parameter__panel">` (do NOT restructure the shell):**
  - #7 chart → `<div class="reef-chart" data-tank-id=... data-parameter-id=...>` (carries BOTH ids)
  - #8 stats → `<div class="reef-stats" data-parameter-id=...>`
  - #10 reference → `<div class="reef-reference" data-parameter-id=...>`
  - Add-reading form (#5) + readings table already sit between stats and reference. Empty seams hidden via `:empty` CSS until filled.
  - Seam attr = `data-parameter-id`; TAB LINK attr = `data-param-id` (shorter). Don't confuse them.
- **Aggregate tab = SLOT ONLY**: `href="#aggregate"`, `data-tab="aggregate"`, `TODO(#12/#13)`. #12/#13 add the real aggregate route/view and swap the href; `active_tab="aggregate"` marks it active.
- **Parameters are GLOBAL across tanks** (flat `[[parameters]]` in TOML). Every tank shows a tab per configured parameter; per-tank difference is only range overrides via `Parameter.range_for_tank(tank_id)`.
- **Unknown/archived params**: `_unknown_param_ids(tank_id)` in `fishy/__init__.py` → param ids in readings but not config; `tank_view` passes `unknown_params`; `tank.html` renders `.reef-tabs__archived` note (no tab). `parameter_view` still 404s for a param not in config.
- ⚠️ Concurrency: #7/#8/#10 all edit `parameter.html` (and possibly `_render_parameter`) → run SERIALLY, not concurrently, to avoid whole-file clobber.

## RANGE-SELECTION SEAM & CHART CONTRACT (task #7 — for #8/#9/#12)
- **`fishy/__init__.py::_range_for(parameter, tank_id) -> TargetRange | None`** = the SINGLE centralized "which range applies" lookup. **DONE (task #9): now returns `parameter.range_for_tank(tank_id)`** (per-tank override → parameter default → None). Every chart/stats/highlighting consumer flows through it, so per-tank ranges apply everywhere; #12/#13 aggregate inherit this for free. Live shipped override: `[overrides.frag-tank.alkalinity]` (8.2–8.8).
- **`_chart_series(readings, parameter, tank_id)`** (Flask-free, module-level in `fishy/__init__.py`) returns canonical shape: `{ tank_id, parameter_id, display_name, unit, range:{min,max}, points:[{date:"YYYY-MM-DD", value, in_range}, ...] }`, points sorted oldest→newest; range carries usable bounds only (absent/empty/invalid → nulls, nothing flagged).
  - **#8 stats**: reuse `_chart_series(...)["points"]` (already sorted + classified) for latest/min/max/avg/trend/badge. Also `_classify_in_range(value, range)` + `_range_for(...)` are callable directly.
  - **#12 aggregate overlay**: build one such dict per parameter for the active tank; each independently renderable/toggleable.
- Data flow = **inline JSON contract** (no endpoint): template emits `{{ chart_data | tojson }}` inside `div.reef-chart > script.reef-chart-data`; `fishy/static/js/chart.js` (Plotly CDN loaded in parameter.html `{% block head %}`) parses + `Plotly.newPlot`. Out-of-range markers coral `#e4572e`, in-range teal `#01baef`, band via layout `shapes` rect.
- #7 touched ONLY `.reef-chart` seam + `{% block head %}` in parameter.html → `.reef-stats` / `.reef-reference` seams remain clean for #8/#10.

## STATS CONTRACT (task #8 — for #12 aggregate cards)
- **`fishy/__init__.py::_parameter_stats(points, *, unit="", today=None) -> dict`** (Flask-free). `points` = chart contract's `points`. Output: `{has_data, count, unit, latest:{value,value_display,date,in_range}|None, trend:"up"|"down"|"flat"|None, min/max/avg + *_display, days_since_last}`. Single reading → trend None, min==max==avg; empty → has_data False.
- Reuse `fishy/storage.py::_format_value(v)` (importable) anywhere you render a numeric value (avoids `8.0`).
- #8 touched ONLY the `.reef-stats` seam. `.reef-reference` still clean for #10.

## REFERENCE PANEL + MARKDOWN (task #10 — for #11/#14)
- All THREE parameter-panel seams now filled: `.reef-chart` (#7), `.reef-stats` (#8), `.reef-reference` (#10). `parameter.html` panel order: chart → stats → add-reading form → readings table → reference accordion (bottom, never obscures data).
- **Safe markdown = `fishy/markdown.py::render_markdown(text)->str`** (stdlib + markupsafe which ships with Flask; NO new dep). Escapes first, then paragraphs / `-`|`*` lists / `**bold**` / `_italic_`. Wired as Jinja filter `{{ text | markdown }}` (returns Markup) in `create_app`. **Reuse for any user-authored markdown (#14 theming).**
- Reference partial `fishy/templates/_param_reference.html`: `<details>` accordion over `content.ordered()` (7 SECTION_ORDER sections); context var `content` = `config.content_for(parameter.id)`. Placeholder sections get `is-placeholder` class + "Not documented yet" (custom params via `_template.md`). Editing `content/<id>.md` updates live.

## CUSTOM PARAMS + UNITS (task #11)
- Pipeline is fully CONFIG-DRIVEN: a `[[parameters]]` block auto-yields tab→chart→stats→reference(template placeholders)→form. Custom params need NO code changes. Shipped example: `temperature` (`units=["°C","°F"]`, no range) in `config/fishy.toml`.
- Unit labeling flows from `Parameter.default_unit` (first declared unit): chart y-axis, hover suffix, stat cards, readings table, and `add_reading` records it. No hardcoded units anywhere.
- **Canonical-unit rule (Open Q#3 RESOLVED):** first declared unit is canonical; all stored values use it; NO auto-conversion in v1. Documented in README + config comment.
- Duplicate display name OK (UI keys by `id`); duplicate `id` deduped w/ `config.warnings`. Archived param (readings but not in config) → `.reef-tabs__archived` note, tank view 200, `parameter_view` 404s.
- **#12 aggregate must iterate `config.parameters`** and build one `_chart_series(...)` per param — that's how custom params participate.

## AGGREGATE ROUTE + SEAMS (task #12 — for #13/#14)
- **Route `aggregate_view`** at `GET /tank/<tank_id>/aggregate` (in `fishy/__init__.py`). Builds `series_list = [_chart_series(_readings_for(tank,p.id), p, tank_id) for p in config.parameters]` ONCE → feeds `_aggregate_cards(series_list)` + `_aggregate_series(series_list)`. Renders `aggregate.html` with `cards`, `overlay`, `has_any_readings`, standard shell + `active_tab="aggregate"`. Aggregate tab in `_param_tabs.html` now links here.
- Flask-free helpers (module-level, unit-testable): `_normalize(values)` (min-max→0..1; equal/single→0.5), `_aggregate_series(series_list)` (adds `norm` per point, non-mutating), `_aggregate_cards(series_list)` (`{parameter_id,display_name,unit,range,stats}`, stats via `_parameter_stats`).
- Overlay = JSON LIST of series (each point has `norm`) inline in `div.reef-aggregate-chart > script.reef-aggregate-data`; `fishy/static/js/aggregate.js` plots `norm` on shared 0..1 axis, real value+unit in hover, coral out-of-range markers, legend-click toggles.
- **#13 HISTORY-TABLE SEAM**: fill `<section class="reef-aggregate__history">` at BOTTOM of `aggregate.html`'s `.reef-aggregate__panel` (below cards+overlay). Currently after the `{% if not has_any_readings %}` block so renders regardless; `.reef-aggregate__history:empty { display:none }`. Use `_readings_for(tank, ...)` for the tank's readings (one row per reading, most-recent-first).

## AGGREGATE HISTORY TABLE (task #13 — for #14/#15)
- Seam FILLED. `_history_rows(all_readings, config, tank_id)` (Flask-free, module-level) → most-recent-first rows incl. archived-param rows. Fields `{date, parameter_id, parameter_label, value, value_display, unit, note, in_range, is_archived}`. `aggregate_view` loads ALL readings once, passes `history` to `aggregate.html`.
- Markup `.reef-history__table` in `.reef-history__scroll` (28rem sticky-header scroll). Out-of-range rows `.reef-history__row--out` + `.reef-badge--out`; archived `.reef-history__archived` pill. No pagination (full scroll + count note). Empty → "No readings logged for <tank> yet."
- GOTCHA for aggregate-page tests: overlay JSON also contains ISO dates (oldest-first) → slice the history `<section>` before ordering asserts.

## PHASE 3 COMPLETE — app is functionally whole. Remaining: #15 empty/edge states, #14 tropical-reef theme (both touch templates+CSS → run SERIALLY).

## EMPTY/EDGE STATES + NOTICE (task #15 — classes for #14 to theme)
- **Standardized classes**: `.reef-empty` (marker on EVERY friendly empty state; state-specific `.reef-stats__empty`/`.reef-aggregate__empty` kept alongside — tests assert them, don't remove), `.reef-empty--inline` (lighter in-panel variant). Malformed-CSV banner = `.reef-notice` + `.reef-notice--warn` in `_notice.html` (`.reef-notice__lead/__icon/__list/__hint`).
- Malformed-CSV surfacing: `_load_warnings()` (in `_register_routes`) → `load_readings(path, emit_warnings=False).warnings`; template var `load_warnings`; `_notice.html` included on tank/parameter/aggregate pages (NOT shelf). Non-fatal; valid rows still display.
- #14 THEME: theme `.reef-empty*` and `.reef-notice*` uniformly; palette was intentionally left functional-only by #15.

## Known Issues
- task-executor agent context lacks the TaskUpdate tool — orchestrator marks tasks complete from the PASS result file.
- `ruff` not installed in env; agents verify via `py_compile` + full `pytest`.
- Flask installed via `python -m pip install --user flask` (network available). pytest 9.0.2, Jinja2 3.1.6 present.
- `data/readings.csv` does not exist until first append — downstream UI must handle first_run/empty state gracefully.

## File Map
- `app.py` — entry point (dep guard, port-in-use guard, FISHY_HOST/PORT, create_app().run()).
- `fishy/__init__.py` — `create_app()` factory + `_register_routes()` (routes `/`, `/health`). Not yet loading config/storage.
- `fishy/storage.py` — CSV persistence layer (see Storage API).
- `fishy/config.py` — TOML+markdown config/content loader (see Config API).
- `fishy/templates/{base,index}.html` — base layout + landing (extend base.html).
- `fishy/static/css/style.css` — tropical-reef palette (`:root` vars) + layout scaffold.
- `config/fishy.toml` — default config (2 tanks, 5 reef params + ranges + overrides example).
- `content/{salinity,alkalinity,calcium,magnesium,phosphate}.md`, `content/_template.md` — reference content.
- `tests/test_app.py` (8), `tests/test_storage.py` (28), `tests/test_config.py` (24).
- `requirements.txt` (Flask) / `requirements-dev.txt` (pytest). `CLAUDE.md`, `README.md`, `.gitignore`.

## Run / test commands
- Run: `python app.py` (serves http://127.0.0.1:5000)
- Test: `python -m pytest` (60 tests pass)

## Task History
### Task [1]: Choose stack and scaffold app skeleton - PASS
- Flask + Plotly.js CDN stack; app-factory pattern; long/tidy CSV storage planned; localhost-only. Created CLAUDE.md/README.md/.gitignore + base templates + 8 tests.

### Task [2]: Implement CSV readings schema and read/write layer - PASS
- Files: `fishy/storage.py` (new), `tests/test_storage.py` (new, 28 tests). Long/tidy CSV, stdlib-only, append-only, safe quoting, malformed-row tolerance, first_run detection, 5000-row perf test. No shared files touched (clean concurrency with #3).

### Task [3]: Implement config and content loader - PASS
- Files: `fishy/config.py` (new), `config/fishy.toml`, `content/*.md` (5 params + _template), `tests/test_config.py` (24 tests). TOML+markdown, zero new deps, override precedence, per-tank range overrides, warnings-vs-errors. Not yet wired into create_app(). No shared files touched (clean concurrency with #2).

### Task [4]: Build tank shelf landing and tank switcher - PASS
- Files: `fishy/__init__.py` (wired config, added `/` + `/tank/<tank_id>` routes), `fishy/templates/index.html` (shelf), `fishy/templates/tank.html` (NEW view + switcher + tabs placeholder), `fishy/static/css/style.css` (appended shelf/switcher styles), `tests/test_shelf.py` (NEW, 12 tests). Suite 60 → 72. Established active-tank URL convention (see above).

### Task [16]: Write README and launch documentation - PASS
- Files: `README.md` (expanded to full launch + data-format docs; all facts verified against source). Docs-only, 60/60 green at its time. `.gitignore` does NOT exclude data/config/content → readings.csv is git-tracked by default.

### Task [5]: Implement per-parameter add-reading form - PASS
- Files: `fishy/__init__.py` (wired storage via FISHY_READINGS_PATH; routes parameter_view/add_reading + helpers _readings_path/_readings_for/_render_parameter/_resolve), `fishy/templates/_add_reading_form.html` (NEW partial), `fishy/templates/parameter.html` (NEW per-parameter page: form + readings table), `fishy/static/css/style.css` (appended), `tests/test_reading_form.py` (NEW, 17 tests). Suite 72 → 89. Established storage-wiring, PRG/validation conventions, and form-embed path for #6 (see Key Decisions).

### Task [6]: Build tank view with per-parameter tab navigation - PASS
- Files: `fishy/templates/_param_tabs.html` (NEW tab nav partial), `fishy/templates/tank.html` (filled placeholder + empty/archived states), `fishy/templates/parameter.html` (embedded tab nav + chart/stats/reference seams), `fishy/__init__.py` (tab data + `_unknown_param_ids()`), CSS appended, `tests/test_tank_tabs.py` (NEW, 13 tests). Suite 89 → 102. Documented tab model + content-region seams (see section above).

### Task [7]: Build parameter time-series chart with target-range band - PASS
- Files: `fishy/__init__.py` (helpers `_range_for`/`_classify_in_range`/`_chart_series`; `chart_data` into context), `fishy/templates/parameter.html` (`{% block head %}` Plotly+chart.js; filled `.reef-chart` seam w/ inline JSON), `fishy/static/js/chart.js` (NEW render-only Plotly client), CSS appended, `tests/test_chart.py` (NEW, 20 tests). Suite 102 → 122. Range-selection + chart-contract seams documented above.

### Task [8]: Build parameter stats panel - PASS
- Files: `fishy/__init__.py` (`_parameter_stats()` helper; `stats` into context), `fishy/templates/parameter.html` (filled ONLY `.reef-stats` seam), CSS appended, `tests/test_stats.py` (NEW, 21 tests). Suite 122 → 143. Stats contract documented above.

### Task [10]: Render reference and action-guide content on parameter tabs - PASS
- Files: `fishy/markdown.py` (NEW safe renderer), `fishy/__init__.py` (`markdown` Jinja filter; `content` into context), `fishy/templates/_param_reference.html` (NEW accordion), `fishy/templates/parameter.html` (filled ONLY `.reef-reference` seam), CSS appended, `tests/test_reference.py` (NEW, 17 tests). Suite 143 → 160. Markdown + reference seams documented above.

### Task [11]: Support user-defined custom parameters - PASS
- Files: `config/fishy.toml` (example `temperature` custom param + multi-unit note), `tests/test_custom_params.py` (NEW, 10 tests). No app-code/template changes needed (pipeline already config-driven). Suite 160 → 170. Canonical-unit rule + custom-param behavior documented above.

### Task [9]: Implement target-range defaults and overrides - PASS
- Files: `fishy/__init__.py` (`_range_for` → `range_for_tank(tank_id)`, one-line), `config/fishy.toml` (live `[overrides.frag-tank.alkalinity]`), `tests/test_ranges.py` (NEW, 17 tests). Suite 170 → 187. Per-tank ranges now drive band + highlighting everywhere.

### Task [12]: Build aggregate tab cards row and overlay chart - PASS
- Files: `fishy/__init__.py` (`_normalize`/`_aggregate_series`/`_aggregate_cards` + `aggregate_view` route), `fishy/templates/aggregate.html` (NEW), `fishy/templates/_param_tabs.html` (Aggregate href → real route), `fishy/static/js/aggregate.js` (NEW overlay renderer), CSS appended, `tests/test_aggregate.py` (NEW, 22 tests). Suite 187 → 209. Aggregate route + history-table seam documented above.

### Task [13]: Build aggregate history table - PASS
- Files: `fishy/__init__.py` (`_history_rows` helper + `history` into aggregate context), `fishy/templates/aggregate.html` (filled `.reef-aggregate__history` seam), CSS appended, `tests/test_history.py` (NEW, 18 tests), `tests/test_aggregate.py` (updated stale TODO guard). Suite 209 → 227. Aggregate view + Phase 3 complete.

### Task [15]: Add friendly empty and edge states - PASS
- Files: `fishy/__init__.py` (`_load_warnings()` + `load_warnings` into contexts), `fishy/templates/_notice.html` (NEW malformed-CSV banner), `index/tank/parameter/aggregate.html` (unified `.reef-empty` states + notice include), CSS appended (functional), `tests/test_empty_states.py` (NEW, 15 tests). Suite 227 → 242. Standardized `.reef-empty`/`.reef-notice` classes for #14.

### Task [14]: Apply tropical-reef visual theme - PASS
- Files: `fishy/static/css/style.css` (evolved `:root` palette/type + cohesive theme: wave/bubble motifs, hover delight, focus ring, @640px responsive, prefers-reduced-motion), `fishy/templates/base.html` (Baloo 2 + Nunito font CDN + theme-color), `fishy/static/js/{chart,aggregate}.js` (per-point marker SHAPE = non-color out-of-range cue + themed Plotly font/grid), `tests/test_theme.py` (NEW, 12 tests). Suite 242 → 254. WCAG AA contrast verified; all structural classes/contracts preserved.

## SESSION COMPLETE — all 16 tasks PASS, 254 tests green. fishy is a functional tropical-reef water-parameter tracker (Flask + Plotly, CSV storage, config-driven params, per-tank ranges, aggregate view, themed).
