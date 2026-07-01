# fishy 🐠

A personal, local-first web app for reef aquarists to log dated water-parameter
readings and see them through beautiful, useful visualizations. Data lives in a
git-trackable CSV; the app runs on localhost and reads/writes that file as its
only state.

See [`specs/fishy-SPEC.md`](specs/fishy-SPEC.md) for the full product spec.

## Quick start

```bash
# 1. Install dependencies (a virtual environment is recommended)
python -m pip install -r requirements.txt

# 2. Run the app (localhost only)
python app.py
```

Then open <http://127.0.0.1:5000> in your browser.

Optional environment overrides:

| Variable     | Default     | Purpose                          |
|--------------|-------------|----------------------------------|
| `FISHY_HOST` | `127.0.0.1` | Bind host (localhost by default) |
| `FISHY_PORT` | `5000`      | Bind port                        |

```bash
# Example: run on a different port
FISHY_PORT=8080 python app.py
```

The server binds to `127.0.0.1` by default, so it is **not** reachable from
other machines on the network (spec §6.2 / §7.5).

## Tech stack (Phase 1 decision — resolves Open Question #1)

| Choice | Selection | Rationale |
|--------|-----------|-----------|
| **Web framework** | **Flask** | Smallest footprint of the candidates, single-command run (`python app.py`), built-in Jinja2 server-rendered templates. FastAPI is optimised for async JSON APIs and needs a separate ASGI server (uvicorn) plus more moving parts — unnecessary for a single-user, server-rendered, local page. Flask best fits the minimalism constraint (§7.5). |
| **Charting** | **Plotly.js (CDN)** | Must support shaded target-range bands and multi-series overlays *attractively* (§7.2, §5.3, §5.7). Plotly.js does shaded bands (`fill`/layout `shapes`), multi-axis overlays, and per-series legend toggling out of the box with a polished default look, and it runs entirely client-side from a CDN — so there is **no** Python charting dependency to install. Chart.js is lighter but range bands + multi-axis overlays require more custom plumbing. |
| **Storage** | Plain-text **CSV** (long/tidy) + human-editable config/content files | Git-trackable, human-readable, per-reading diffs (§7.4). |
| **Infrastructure** | None | Runs locally on localhost; no DB, no cloud, no external APIs. |

## Project structure

```
fishy/
├── app.py                 # Entry point: `python app.py` (dependency + port-in-use guards)
├── fishy/                 # Application package
│   ├── __init__.py        # create_app() application factory + route registration
│   ├── storage.py         # Readings CSV persistence layer (long/tidy, append-only)
│   ├── config.py          # TOML config + markdown content loader
│   ├── templates/         # Jinja2 templates (base.html, index.html)
│   └── static/            # CSS / JS assets (tropical-reef base theme)
├── config/
│   └── fishy.toml         # Tanks, parameters, target ranges, per-tank overrides
├── content/
│   ├── <parameter>.md     # Per-parameter reference/action-guide text
│   └── _template.md       # Fillable template for custom parameters
├── data/
│   └── readings.csv       # Your readings (created on first save; commit this)
├── tests/                 # pytest suite (unit / integration / smoke)
├── requirements.txt       # Runtime dependencies (Flask only)
├── requirements-dev.txt   # Dev dependencies (adds pytest)
└── specs/                 # Product specification
```

Everything under `config/`, `content/`, and `data/` is plain text and meant to
be edited by hand and committed to git.

## Your data: the readings CSV

All reading state lives in a single file, `data/readings.csv`, stored in
**long/tidy** form — **one row per reading**. The file is created automatically
the first time you save a reading (until then the app shows an empty/first-run
state), so you don't have to create it yourself. The column order is stable and
load-bearing for clean git diffs:

| Column      | Meaning                                            | Example        |
|-------------|----------------------------------------------------|----------------|
| `tank`      | Tank `id` from `config/fishy.toml`                 | `reef-a`       |
| `parameter` | Parameter `id` from `config/fishy.toml`            | `salinity`     |
| `date`      | Date the reading was taken, ISO `YYYY-MM-DD`       | `2026-07-01`   |
| `value`     | The measured number                                | `1.026`        |
| `unit`      | The unit `value` is expressed in                   | `sg`           |
| `note`      | Optional free-text note (commas/quotes are safe)   | `after WC`     |

Example file:

```csv
tank,parameter,date,value,unit,note
reef-a,salinity,2026-07-01,1.026,sg,after water change
reef-a,alkalinity,2026-07-01,8.4,dKH,
frag-tank,calcium,2026-07-02,430,ppm,"Salifert, second test"
```

### Hand-editing readings

The CSV is the single source of truth and is safe to edit in any text editor or
spreadsheet:

- **Add** a reading by appending a new row (the app appends; it never rewrites
  existing rows, so external edits are preserved).
- **Correct** a reading by editing its row in place.
- **Delete** a reading by removing its row.
- Keep the header row and the six columns in the order above. Notes containing
  commas, quotes, or newlines should be wrapped in double quotes — the app does
  this automatically on save, and reads them back losslessly.

Malformed rows never crash the app: a row with a missing required field, a bad
date, or a non-numeric value is **skipped with a warning** that names the row
number, and all the other rows still load (see [Troubleshooting](#troubleshooting)).

## Configuration: `config/fishy.toml`

Tanks, parameters, and target ranges are defined in `config/fishy.toml`
([TOML](https://toml.io), parsed with Python's standard-library `tomllib` — no
extra dependency). Editing this file changes what the app shows; **no code
changes are needed**.

### Adding a tank

Each tank is a `[[tanks]]` table with a stable `id` (used as the CSV `tank` key)
and a human `label`:

```toml
[[tanks]]
id = "reef-a"
label = "Reef A"

[[tanks]]
id = "nano"
label = "Nano Cube"
```

### Adding / defining a parameter

Each parameter is a `[[parameters]]` table:

```toml
[[parameters]]
id = "salinity"                              # stable key: CSV `parameter` + content filename
display_name = "Salinity / Specific Gravity" # human label shown in the UI
units = ["sg", "ppt"]                        # accepted units; the FIRST is canonical/stored
target_range = { min = 1.024, max = 1.026 }  # default ideal band
```

Field notes:

- `id` is required and must be unique. It ties together the config, the CSV
  `parameter` column, and the `content/<id>.md` reference file.
- `display_name` is optional (falls back to `id`).
- `units` may be a single string (`units = "dKH"`) or a list. The **first** unit
  is the canonical one — see [Units](#units-multi-unit-handling) below.
- `target_range` is an inline table with `min` and/or `max`; either bound may be
  omitted for a one-sided band, and the whole key may be omitted for no band.

### Setting default target ranges & per-tank overrides

The `target_range` on a parameter is the default band for every tank. To tighten
or loosen a band for one specific tank, add an `[overrides.<tank-id>.<param-id>]`
table:

```toml
# Tighten alkalinity just for the frag tank; every other tank keeps 8.0–9.0.
[overrides.frag-tank.alkalinity]
min = 8.2
max = 8.8
```

A tank without an override falls back to the parameter's default range. An
inverted range (`min > max`) is ignored with a warning rather than crashing the
app.

## Reference content: `content/<parameter>.md`

Each parameter can have a markdown reference file at `content/<parameter-id>.md`
(matching the parameter `id`) providing the action-guide text the app shows.
Sections are delimited by `## ` headings; the app looks for these seven
(in this render order):

| Heading                | Section key   | What to write                          |
|------------------------|---------------|----------------------------------------|
| `## Definition`        | `definition`  | What the parameter is                  |
| `## Measurement & Units` | `measurement` | How it's measured and in what units  |
| `## Ideal Range`       | `ideal_range` | The healthy target band                |
| `## When It's Too High`| `too_high`    | Effects when the value runs high       |
| `## When It's Too Low` | `too_low`     | Effects when the value runs low        |
| `## Signs & Symptoms`  | `signs`       | Visible signs the parameter is off     |
| `## Suggested Remedies`| `remedies`    | How to bring it back into range        |

Any heading you leave out simply renders as a gentle placeholder — nothing
breaks. Keep the `## ` headings intact so the app can find each section; write
freely (markdown) underneath them. A `# Title` line and any preamble are ignored.

## Adding a custom parameter

1. **Add a `[[parameters]]` block** to `config/fishy.toml` with a new `id`,
   `display_name`, `units`, and optional `target_range` (see above).
2. **(Optional) Add reference content.** Copy the fillable template and fill it
   in:

   ```bash
   cp content/_template.md content/<your-parameter-id>.md
   ```

   The filename must match the parameter `id`. Fill in the `## ` sections; leave
   any you don't have blank. If you skip this step entirely, the parameter still
   works — its content just shows placeholders.
3. **Start logging** readings for it (the `parameter` column in the CSV uses the
   new `id`).

## Units (multi-unit handling)

*(Open Question #3 — how multiple units are recorded.)*

Every reading stores its own `unit` in the CSV `unit` column, so you can record
what your test kit actually reports. A parameter's `units` list in the config
declares which units are accepted, and **the first entry is the canonical
unit** — the recommended one to record consistently so a parameter's history
compares cleanly on a single scale.

The clearest example is **salinity**, which is commonly read as either specific
gravity (`sg`, e.g. `1.026`) or parts-per-thousand (`ppt`, e.g. `35`). The
shipped config lists `units = ["sg", "ppt"]`, making **`sg` the canonical
unit**. Guidance: pick one unit per parameter and stick with it (record salinity
in `sg`); if you occasionally log an alternate unit, note it so you don't compare
`1.026` against `35` on the same axis. Automatic unit conversion is intentionally
out of scope — the `unit` column keeps every reading honest about how it was
measured.

## Versioning your data with git

Your reading log *is* the data, so committing it to git gives you a full,
diffable history and a backup:

```bash
git add data/readings.csv          # after logging readings
git commit -m "Log readings for the week"
```

Because writes are **append-only**, each new reading shows up as a single added
line in `git diff` — clean, reviewable history with no churn on existing rows.
Commit `config/fishy.toml` and your `content/*.md` edits the same way so your
tanks, ranges, and reference notes are versioned alongside the data:

```bash
git add config/fishy.toml content/
git commit -m "Add nano tank; tighten frag-tank alkalinity"
```

Nothing under `data/`, `config/`, or `content/` is git-ignored, so these files
are tracked by default.

## Troubleshooting

**Port already in use.** If another program (or a previous fishy instance) holds
port 5000, startup fails with an actionable message. Close the other program, or
pick another port:

```bash
FISHY_PORT=8080 python app.py
```

**Missing dependency on startup.** If you see `missing dependency 'flask'`,
install the requirements:

```bash
python -m pip install -r requirements.txt
```

**Malformed `config/fishy.toml`.** A missing file, a TOML syntax error, or a
missing required `id` raises a clear `ConfigError` naming the file and the
problem (e.g. an unclosed string or a `[[tanks]]` entry without an `id`). Fix
the named issue and restart. Recoverable problems — a duplicate id or an
inverted `min > max` range — don't stop the app; they're surfaced as warnings
and the offending entry is skipped.

**Malformed rows in `readings.csv`.** Bad rows (missing a required field, an
unparseable date, or a non-numeric `value`) are **skipped with a warning** that
names the row number; every valid row still loads. Fix the named row in your
editor — check that the six columns are present and the `date` is `YYYY-MM-DD`
and `value` is numeric — then reload.

## Development

```bash
python -m pip install -r requirements-dev.txt   # adds pytest
python -m pytest                                 # run the test suite
```
