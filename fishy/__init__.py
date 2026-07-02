"""fishy — a local-first reef water-parameter notebook.

This package exposes an application factory, :func:`create_app`, which builds
and configures the Flask application. Keeping construction in a factory makes
the app easy to test (each test gets a fresh instance) and lets later phases
layer in configuration, the CSV read/write layer, and additional blueprints
without touching the entry point.

Configuration wiring
---------------------
The pure-data config loader (:mod:`fishy.config`) is loaded once at app
construction and stashed on ``app.config["FISHY_CONFIG"]`` so routes and
templates can read the configured tanks/parameters without re-parsing TOML per
request. Tests may inject a ready-made :class:`~fishy.config.Config` via the
same key to avoid touching disk.

Active-tank scoping convention (source of truth for later phases)
-----------------------------------------------------------------
The active tank is carried in the **URL path** as ``/tank/<tank_id>``. This
keeps scoping stateless, shareable and bookmarkable — no server-side session is
needed. Downstream views (add-reading form #5, parameter-tab shell #6, aggregate
view #15) should treat ``tank_id`` from the path as the single source of truth
for the active tank and resolve it via ``config.tank(tank_id)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Flask

from .config import DEFAULT_CONFIG_PATH, Config, load_config
from .storage import DEFAULT_DATA_DIR, _format_value

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from .config import Parameter, TargetRange
    from .storage import Reading

__version__ = "0.1.0"


# --------------------------------------------------------------------------- #
# Chart data helpers (task #7, spec §5.3) — kept at module level and Flask-free
# so the range-selection + in/out-of-range classification is unit-testable
# without a browser. The template + fishy/static/js/chart.js only *render* the
# contract these produce.
# --------------------------------------------------------------------------- #
def _range_for(parameter: Parameter, tank_id: str | None) -> TargetRange | None:
    """Resolve which target range the chart should shade for ``parameter``.

    CENTRALIZED range-selection seam. Every chart/band lookup goes through this
    one function so the "which range applies" policy lives in exactly one place.

    Resolution precedence (task #9, spec §5.5): a per-tank override wins,
    otherwise the parameter's default range applies, otherwise ``None`` (no
    band). Delegating to :meth:`Parameter.range_for_tank` keeps that precedence
    in the pure config layer, and because every chart/stats consumer flows
    through this helper (the serialized ``chart_data`` contract, the stats
    badge, and — later — the aggregate overlay in #12/#13), the resolved range
    feeds the chart band AND in/out-of-range highlighting consistently
    everywhere with no caller change.
    """
    return parameter.range_for_tank(tank_id)


def _classify_in_range(value: float, target_range: TargetRange | None) -> bool:
    """Return whether ``value`` sits inside ``target_range``.

    Delegates to :meth:`TargetRange.contains`, which treats a missing, empty or
    invalid range (and one-sided bounds) correctly — so a parameter with no
    usable band never flags any reading as out-of-range.
    """
    if target_range is None:
        return True
    return target_range.contains(value)


def _chart_series(
    readings: Iterable[Reading], parameter: Parameter, tank_id: str | None
) -> dict:
    """Build the JSON-serialisable chart contract for one tank+parameter.

    This is the single source of truth for what the client chart renders and is
    the contract task #12's aggregate overlay reuses (per-parameter series +
    resolved band + per-point in/out-of-range classification).

    Contract shape::

        {
          "tank_id":       str,
          "parameter_id":  str,
          "display_name":  str,
          "unit":          str,                 # "" when unit-less
          "range":         {"min": float|None, "max": float|None},
          "points": [ {"date": "YYYY-MM-DD",
                       "value": float,
                       "in_range": bool}, ... ] # sorted oldest → newest
        }

    ``range`` carries usable bounds only: an absent, empty or invalid band
    yields ``{"min": None, "max": None}`` so the client draws no shaded region
    and (via :func:`_classify_in_range`) flags nothing as out-of-range.
    """
    rng = _range_for(parameter, tank_id)
    ordered = sorted(readings, key=lambda r: r.date)
    points = [
        {
            "date": r.date.isoformat(),
            "value": r.value,
            "in_range": _classify_in_range(r.value, rng),
        }
        for r in ordered
    ]
    if rng is not None and rng.is_valid and not rng.is_empty:
        band = {"min": rng.min, "max": rng.max}
    else:
        band = {"min": None, "max": None}
    return {
        "tank_id": tank_id,
        "parameter_id": parameter.id,
        "display_name": parameter.display_name,
        "unit": parameter.default_unit or "",
        "range": band,
        "points": points,
    }


# --------------------------------------------------------------------------- #
# Parameter stats helper (task #8, spec §5.3) — Flask-free + browser-free so the
# summary math (latest/trend/min/max/avg/days-since) is unit-testable in
# isolation. It consumes the SAME points the chart contract (`_chart_series`)
# already produced (sorted oldest→newest, each classified `in_range`), so the
# stats panel and the chart never disagree about ordering or range membership.
# Task #12's aggregate stat cards reuse this exact output shape.
# --------------------------------------------------------------------------- #
def _parameter_stats(
    points: list[dict],
    *,
    unit: str = "",
    today: object | None = None,
) -> dict:
    """Summarise a parameter's visible history for the stats panel.

    Args:
        points: The chart contract's ``points`` list — dicts with ``date``
            (``"YYYY-MM-DD"``), ``value`` (float) and ``in_range`` (bool),
            **sorted oldest→newest** (as :func:`_chart_series` returns them).
        unit: Display unit for the values (``""`` when unit-less). Carried into
            the result so callers/templates need not thread it separately.
        today: Reference date for ``days_since_last`` (defaults to
            :meth:`datetime.date.today`). Injectable so tests are deterministic.

    Returns:
        A JSON-friendly dict::

            {
              "has_data":        bool,   # False → render a "no data yet" state
              "count":           int,
              "unit":            str,
              "latest":          {"value": float, "value_display": str,
                                  "date": "YYYY-MM-DD", "in_range": bool} | None,
              "trend":           "up" | "down" | "flat" | None,  # None if <2 pts
              "min": float|None,         "min_display": str|None,
              "max": float|None,         "max_display": str|None,
              "avg": float|None,         "avg_display": str|None,
              "days_since_last": int | None,   # 0 when the latest reading is today
            }

    Edge behaviour: a single reading yields ``trend=None`` and
    ``min == max == avg == value``; an empty history yields ``has_data=False``
    with every stat ``None``. In/out-of-range membership is taken verbatim from
    each point, so an all-out-of-range history still reports correct values.
    """
    import datetime as _dt

    if not points:
        return {
            "has_data": False,
            "count": 0,
            "unit": unit,
            "latest": None,
            "trend": None,
            "min": None,
            "max": None,
            "avg": None,
            "min_display": None,
            "max_display": None,
            "avg_display": None,
            "days_since_last": None,
        }

    values = [p["value"] for p in points]
    latest_point = points[-1]
    lo = min(values)
    hi = max(values)
    avg = sum(values) / len(values)

    # Trend compares the latest reading to the immediately preceding one. A lone
    # reading has nothing to compare against, so it has no trend.
    trend: str | None
    if len(points) < 2:
        trend = None
    else:
        prev_value = points[-2]["value"]
        if latest_point["value"] > prev_value:
            trend = "up"
        elif latest_point["value"] < prev_value:
            trend = "down"
        else:
            trend = "flat"

    reference = today if today is not None else _dt.date.today()
    latest_date = _dt.date.fromisoformat(latest_point["date"])
    days_since_last = max((reference - latest_date).days, 0)

    return {
        "has_data": True,
        "count": len(points),
        "unit": unit,
        "latest": {
            "value": latest_point["value"],
            "value_display": _format_value(latest_point["value"]),
            "date": latest_point["date"],
            "in_range": latest_point["in_range"],
        },
        "trend": trend,
        "min": lo,
        "max": hi,
        # Average rarely round-trips cleanly, so round before formatting to keep
        # the card readable (e.g. 34.333 rather than 34.33333333333333).
        "avg": avg,
        "min_display": _format_value(lo),
        "max_display": _format_value(hi),
        "avg_display": _format_value(round(avg, 3)),
        "days_since_last": days_since_last,
    }


# --------------------------------------------------------------------------- #
# Aggregate tab helpers (task #12, spec §5.7) — Flask-free + browser-free so the
# normalization and card/overlay assembly are unit-testable in isolation. The
# combined Aggregate tab shows every parameter for the active tank at once:
#   * a cards row (latest / trend / in-range badge per parameter), reusing the
#     same `_parameter_stats` contract the per-parameter panel uses, and
#   * an all-parameter overlay chart on a shared timeline.
# Reef parameters live on wildly different scales (specific gravity ~1.02 vs
# calcium ~420 ppm), so plotting raw values on one axis would flatten the small
# ones into a line. We therefore min-max NORMALISE each series to a common 0..1
# axis; the raw value + unit still ride along for the hover label. Keeping the
# maths here (not in JS) makes the "comparably scaled" requirement testable.
# --------------------------------------------------------------------------- #
def _normalize(values: list[float]) -> list[float]:
    """Min-max scale ``values`` onto a common ``0..1`` axis.

    This is what makes an overlay of differently-scaled parameters legible: each
    series is squashed into the same ``0..1`` band so a 1.026 specific-gravity
    line and a 420 ppm calcium line are visually comparable.

    Edge behaviour:
        * empty input → ``[]``.
        * a single value, or an all-equal series (min == max, so the span is
          zero and a raw ``(v-lo)/span`` would divide by zero) → every value maps
          to ``0.5`` (a legible flat line through the middle of the band).
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [0.5 for _ in values]
    span = hi - lo
    return [(v - lo) / span for v in values]


def _aggregate_series(series_list: list[dict]) -> list[dict]:
    """Add a normalized ``norm`` coordinate to every point of every series.

    Args:
        series_list: One :func:`_chart_series` contract dict per parameter (for
            the active tank). Not mutated — fresh dicts are returned.

    Returns:
        The same series shape with each point gaining a ``"norm"`` key (its
        value min-max scaled within its OWN series via :func:`_normalize`). The
        client plots ``norm`` on the shared 0..1 y-axis but shows the raw
        ``value`` + ``unit`` in the hover, and colours out-of-range points using
        the untouched per-point ``in_range`` flag — so highlighting and legend
        toggling work over the overlay exactly as on the single-parameter chart.
    """
    overlay: list[dict] = []
    for series in series_list:
        points = series["points"]
        norms = _normalize([p["value"] for p in points])
        new_points = [{**p, "norm": norms[i]} for i, p in enumerate(points)]
        overlay.append({**series, "points": new_points})
    return overlay


def _aggregate_cards(series_list: list[dict]) -> list[dict]:
    """Assemble the one-card-per-parameter data for the aggregate cards row.

    Reuses the exact :func:`_parameter_stats` contract the per-parameter panel
    renders, so a card's latest value, trend arrow and in/out-of-range badge can
    never disagree with the dedicated parameter tab. A parameter with no
    readings yields ``stats.has_data == False`` (the template shows a light "no
    data" card); a parameter with no usable range never flags out-of-range.

    Args:
        series_list: One :func:`_chart_series` contract dict per parameter.

    Returns:
        A list of ``{parameter_id, display_name, unit, range, stats}`` dicts,
        one per parameter, in the same order as ``series_list``.
    """
    cards: list[dict] = []
    for series in series_list:
        cards.append(
            {
                "parameter_id": series["parameter_id"],
                "display_name": series["display_name"],
                "unit": series["unit"],
                "range": series["range"],
                "stats": _parameter_stats(series["points"], unit=series["unit"]),
            }
        )
    return cards


# --------------------------------------------------------------------------- #
# Aggregate history table helper (task #13, spec §5.7) — Flask-free + browser-
# free so ordering and out-of-range flagging are unit-testable in isolation. The
# bottom of the Aggregate tab lists the active tank's FULL reading history, one
# tidy row per reading (date, parameter, value, note), most-recent-first. This
# is deliberately a long/tidy list — NOT a date×parameter grid — so partial
# logging (a reading only where it was actually logged) is represented naturally
# and multiple same-day readings each keep their own row.
# --------------------------------------------------------------------------- #
def _history_rows(
    readings: Iterable[Reading], config: Config, tank_id: str
) -> list[dict]:
    """Build the most-recent-first history rows for one tank's readings.

    Every reading logged against ``tank_id`` becomes exactly one row — the table
    never forces an all-parameter grid, so partial logging and multiple same-day
    readings are both first-class.

    Out-of-range flagging reuses the SAME per-tank range resolution the charts
    use (:func:`_range_for` → :func:`_classify_in_range`), so a value the overlay
    marks out-of-range is highlighted here too. A reading for a parameter that is
    no longer configured (archived/unknown) has no resolvable range, so it is
    never flagged and is tagged ``is_archived`` with its raw id shown as the
    label — ``config.parameter`` is called guarded, so such rows never crash.

    Args:
        readings: Readings to consider (typically the whole CSV). Only rows whose
            ``tank`` equals ``tank_id`` are kept; others are ignored.
        config: The loaded config, used to resolve each parameter's display name
            and target range (guarded — unknown ids degrade gracefully).
        tank_id: The active tank to scope to.

    Returns:
        A list of JSON-friendly dicts, most-recent-first (stable for equal
        dates — original relative order is preserved), each::

            {
              "date":            "YYYY-MM-DD",
              "parameter_id":    str,
              "parameter_label": str,   # display name, or the raw id if archived
              "value":           float,
              "value_display":   str,   # via _format_value (avoids 8.0)
              "unit":            str,
              "note":            str,
              "in_range":        bool,  # True when not flagged (incl. no range)
              "is_archived":     bool,  # parameter no longer in config
            }
    """
    scoped = [r for r in readings if r.tank == tank_id]
    # Stable sort by date descending: Python's sort is stable, so readings that
    # share a date keep their original relative order (append order in the CSV).
    ordered = sorted(scoped, key=lambda r: r.date, reverse=True)

    rows: list[dict] = []
    for reading in ordered:
        parameter = config.parameter(reading.parameter)
        if parameter is None:
            # Archived/unknown parameter: no config entry → no range, never
            # flagged. Show the raw id so the reading is still legible.
            rows.append(
                {
                    "date": reading.date.isoformat(),
                    "parameter_id": reading.parameter,
                    "parameter_label": reading.parameter,
                    "value": reading.value,
                    "value_display": _format_value(reading.value),
                    "unit": reading.unit,
                    "note": reading.note,
                    "in_range": True,
                    "is_archived": True,
                }
            )
            continue
        target_range = _range_for(parameter, tank_id)
        rows.append(
            {
                "date": reading.date.isoformat(),
                "parameter_id": parameter.id,
                "parameter_label": parameter.display_name,
                "value": reading.value,
                "value_display": _format_value(reading.value),
                "unit": reading.unit,
                "note": reading.note,
                "in_range": _classify_in_range(reading.value, target_range),
                "is_archived": False,
            }
        )
    return rows


def create_app(config: dict | None = None) -> Flask:
    """Build and return a configured :class:`~flask.Flask` application.

    Args:
        config: Optional mapping of configuration overrides applied on top of
            the defaults. Useful for tests (e.g. ``{"TESTING": True}``). Pass a
            ready-made :class:`~fishy.config.Config` under the ``"FISHY_CONFIG"``
            key to skip loading the on-disk TOML (handy for tests).

    Returns:
        A ready-to-serve Flask application instance.
    """
    app = Flask(__name__)

    # Sensible defaults. The readings CSV path is injectable so tests can point
    # storage at a tmp file instead of writing into the repo's real data file.
    app.config.update(
        APP_NAME="fishy",
        TAGLINE="a local-first reef water-parameter notebook",
        # Readings live under this data directory, one CSV per tank at
        # ``<FISHY_DATA_DIR>/<tank_id>/readings.csv``. Injectable so tests point
        # it at a tmp dir instead of the repo's real data.
        FISHY_DATA_DIR=DEFAULT_DATA_DIR,
        # The TOML config path is injectable (like the data dir) so tests — and
        # the create/delete-tank routes — can point at a tmp file instead of the
        # repo's real config. It is also the source used to RELOAD config after a
        # tank is created or deleted.
        FISHY_CONFIG_PATH=DEFAULT_CONFIG_PATH,
    )
    if config:
        app.config.update(config)

    # Load the tank/parameter config once, unless a test injected one. The
    # loader is a pure data layer; we surface it on app.config so views and
    # templates can scope to the active tank without re-parsing per request.
    if not isinstance(app.config.get("FISHY_CONFIG"), Config):
        app.config["FISHY_CONFIG"] = load_config(app.config["FISHY_CONFIG_PATH"])

    # Render the (user-editable, untrusted) reference markdown safely in
    # templates via a `| markdown` filter. The renderer escapes first, so we
    # wrap its output in Markup to opt out of Jinja's re-escaping (task #10).
    from markupsafe import Markup

    from .markdown import render_markdown

    app.jinja_env.filters["markdown"] = lambda text: Markup(render_markdown(text))

    _register_routes(app)
    return app


def _register_routes(app: Flask) -> None:
    """Register the application's routes.

    Foundation routes plus the tank shelf (``/``) and per-tank view
    (``/tank/<tank_id>``). The shelf lists every configured tank; the tank view
    scopes downstream content to the tank named in the path and carries a
    persistent switcher. Later feature phases add parameter tabs and the
    aggregate view here (or via blueprints).
    """
    import datetime as _dt

    from flask import abort, jsonify, redirect, render_template, request, url_for

    from . import storage
    from .storage import Reading

    def _shell(**extra):
        """Common template context (app chrome) merged with view-specific keys."""
        return {
            "app_name": app.config["APP_NAME"],
            "tagline": app.config["TAGLINE"],
            **extra,
        }

    def _data_dir():
        """The configured data directory (injectable for tests)."""
        return app.config["FISHY_DATA_DIR"]

    def _readings_path_for(tank_id: str):
        """Resolve one tank's readings CSV: ``<data_dir>/<tank_id>/readings.csv``."""
        return storage.readings_path_for(_data_dir(), tank_id)

    def _config_path():
        """The configured TOML config path (injectable for tests)."""
        return app.config["FISHY_CONFIG_PATH"]

    def _reload_config():
        """Re-read the TOML config after a tank is created or deleted.

        Config is otherwise loaded once at app construction and cached on
        ``app.config["FISHY_CONFIG"]``; a create/delete mutates the file on disk,
        so we reload from the same path to reflect the change immediately.
        """
        app.config["FISHY_CONFIG"] = load_config(_config_path())

    def _readings_for(tank_id: str, param_id: str):
        """Load readings for one tank+parameter, oldest first, from its CSV."""
        result = storage.load_readings(_readings_path_for(tank_id), emit_warnings=False)
        return [
            r
            for r in result.readings
            if r.tank == tank_id and r.parameter == param_id
        ]

    def _load_warnings(tank_id: str):
        """Non-fatal warnings for malformed/skipped rows in a tank's readings CSV.

        The storage layer (task #2) tolerates malformed rows: it skips each one
        with a clear, row-identifying warning (``"row N: skipped — reason"``)
        and still returns every valid reading. This helper surfaces those
        warnings (``LoadResult.warnings``) so the tank, parameter and aggregate
        views can show a single, consistent, NON-FATAL in-app notice
        (``_notice.html``) at the top of the page — the user learns exactly which
        rows were dropped while their good data keeps rendering below.

        A first-run/missing file has no warnings, so this returns ``[]`` and no
        notice shows. This is the ONE place the app reads ``LoadResult.warnings``,
        keeping the "surface skipped rows" policy centralized (task #15).
        """
        return storage.load_readings(
            _readings_path_for(tank_id), emit_warnings=False
        ).warnings

    def _unknown_param_ids(tank_id: str) -> list[str]:
        """Distinct parameter ids logged for a tank but absent from config.

        Readings referencing a parameter that is no longer configured (archived
        or unknown) are still valid rows — they just have no tab. We collect them
        so the Tank View can surface them gracefully rather than dropping them
        silently or crashing (spec §5.3 error handling). Order is first-seen.
        """
        config: Config = app.config["FISHY_CONFIG"]
        known = config.parameters_by_id
        result = storage.load_readings(_readings_path_for(tank_id), emit_warnings=False)
        seen: list[str] = []
        for reading in result.readings:
            if (
                reading.tank == tank_id
                and reading.parameter not in known
                and reading.parameter not in seen
            ):
                seen.append(reading.parameter)
        return seen

    def _render_parameter(active_tank, parameter, *, error=None, form=None, status=200):
        """Render the per-parameter page (tab nav + content seams + readings)."""
        config: Config = app.config["FISHY_CONFIG"]
        readings = _readings_for(active_tank.id, parameter.id)
        # Serialisable time-series contract for the client chart (#7); the stats
        # panel (#8) reuses its already-sorted, already-classified points so the
        # two views can never disagree about ordering or in/out-of-range status.
        chart_data = _chart_series(readings, parameter, active_tank.id)
        html = render_template(
            "parameter.html",
            **_shell(
                tanks=config.tanks,
                active_tank=active_tank,
                # Tab data: one tab per configured parameter, this one active.
                parameters=config.parameters,
                active_param=parameter.id,
                active_tab=None,
                parameter=parameter,
                readings=readings,
                chart_data=chart_data,
                stats=_parameter_stats(chart_data["points"], unit=chart_data["unit"]),
                # Curated reference & action-guide content (#10), read from the
                # editable content files (defaults shipped, user-overridable).
                # Missing/partial files degrade to placeholders, never raise.
                content=config.content_for(parameter.id),
                today=_dt.date.today().isoformat(),
                error=error,
                form=form or {},
                # Non-fatal malformed-row notice (task #15): valid readings
                # above still render; this lists any rows storage had to skip.
                load_warnings=_load_warnings(active_tank.id),
            ),
        )
        return (html, status) if status != 200 else html

    def _render_index(*, error=None, form=None, status=200):
        """Render the tank shelf, optionally with an add-tank error/form state."""
        config: Config = app.config["FISHY_CONFIG"]
        html = render_template(
            "index.html",
            **_shell(tanks=config.tanks, error=error, tank_form=form or {}),
        )
        return (html, status) if status != 200 else html

    @app.route("/")
    def index():  # pragma: no cover - exercised via test client
        """The launch shelf: every configured tank, listed by label."""
        return _render_index()

    @app.route("/tanks", methods=["POST"])
    def create_tank():  # pragma: no cover - exercised via test client
        """Create a new tank from the shelf's add-tank form (Post/Redirect/Get).

        The name is required; the id is either supplied explicitly or slugified
        from the name. On any validation failure the shelf is re-rendered with a
        friendly message and *nothing* is written. On success the new
        ``[[tanks]]`` block is appended to the TOML config, the config is
        reloaded, and we redirect straight into the new tank's view.
        """
        from . import tank_store

        config: Config = app.config["FISHY_CONFIG"]
        raw_label = (request.form.get("label") or "").strip()
        raw_id = (request.form.get("id") or "").strip()
        form = {"label": raw_label, "id": raw_id}

        if not raw_label and not raw_id:
            return _render_index(
                error="Give your tank a name before adding it.", form=form, status=400
            )

        tank_id = raw_id or tank_store.slugify(raw_label)
        if not tank_id:
            return _render_index(
                error=(
                    f"“{raw_label}” has no letters or numbers to build an id from — "
                    "add some, or set an explicit id."
                ),
                form=form,
                status=400,
            )
        label = raw_label or tank_id

        if config.tank(tank_id) is not None:
            return _render_index(
                error=f"A tank with id “{tank_id}” already exists.",
                form=form,
                status=400,
            )

        try:
            tank_store.add_tank(_config_path(), tank_id, label)
        except tank_store.TankStoreError as exc:
            return _render_index(error=str(exc), form=form, status=400)

        _reload_config()
        return redirect(url_for("tank_view", tank_id=tank_id))

    @app.route("/tank/<tank_id>/delete", methods=["POST"])
    def delete_tank(tank_id: str):  # pragma: no cover - exercised via test client
        """Delete a tank and all its readings (Post/Redirect/Get back to shelf).

        Removes the tank's ``[[tanks]]`` block (and any per-tank overrides) from
        the TOML config and deletes its data directory (``<data_dir>/<tank_id>/``),
        then reloads config and returns to the shelf. An unknown tank id is a 404.
        """
        from . import tank_store

        config: Config = app.config["FISHY_CONFIG"]
        if config.tank(tank_id) is None:
            abort(404, description=f"No tank configured with id '{tank_id}'.")

        try:
            tank_store.delete_tank(_config_path(), tank_id)
        except tank_store.TankStoreError as exc:
            return _render_index(error=str(exc), status=400)

        storage.delete_tank_data(tank_id, _data_dir())
        _reload_config()
        return redirect(url_for("index"))

    @app.route("/tank/<tank_id>")
    def tank_view(tank_id: str):  # pragma: no cover - exercised via test client
        """Tank View — selecting a tank opens straight into its Aggregate
        overview (cards + overlay + history) with the parameter tabs above for
        drilling into a single metric. ``/tank/<id>`` and ``/tank/<id>/aggregate``
        render the same page (no redundant re-selection of the tank)."""
        return _render_aggregate(tank_id)

    def _resolve(tank_id: str, param_id: str):
        """Resolve (active_tank, parameter) from the path or ``abort(404)``."""
        config: Config = app.config["FISHY_CONFIG"]
        active_tank = config.tank(tank_id)
        if active_tank is None:
            abort(404, description=f"No tank configured with id '{tank_id}'.")
        parameter = config.parameter(param_id)
        if parameter is None:
            abort(404, description=f"No parameter configured with id '{param_id}'.")
        return active_tank, parameter

    @app.route("/tank/<tank_id>/parameter/<param_id>")
    def parameter_view(tank_id: str, param_id: str):  # pragma: no cover - test client
        """Per-parameter page: the scoped add-reading form and logged readings.

        Scoped to a single parameter (not a grid) so partial logging is
        first-class — logging one parameter never requires entering others.
        Task #6 embeds the same add-reading form partial into its tab shell via
        ``{% include "_add_reading_form.html" %}`` (see context notes).
        """
        active_tank, parameter = _resolve(tank_id, param_id)
        return _render_parameter(active_tank, parameter)

    @app.route("/tank/<tank_id>/parameter/<param_id>/reading", methods=["POST"])
    def add_reading(tank_id: str, param_id: str):  # pragma: no cover - test client
        """Append one reading for this tank+parameter (Post/Redirect/Get).

        The value must be numeric and non-empty; on failure the form is
        re-rendered with a friendly message and *nothing* is written. On
        success exactly one row is appended and we redirect back to the GET
        page so the new reading shows and a refresh is safe.
        """
        active_tank, parameter = _resolve(tank_id, param_id)

        raw_value = (request.form.get("value") or "").strip()
        raw_date = (request.form.get("date") or "").strip()
        note = request.form.get("note") or ""
        form = {"value": raw_value, "date": raw_date, "note": note}

        if not raw_value:
            return _render_parameter(
                active_tank, parameter,
                error="Please enter a value before saving.",
                form=form, status=400,
            )
        try:
            value = float(raw_value)
        except ValueError:
            return _render_parameter(
                active_tank, parameter,
                error=f"“{raw_value}” isn't a number — enter a numeric value (e.g. 8.2).",
                form=form, status=400,
            )

        # Date auto-captured at save time; an override from the form wins so
        # back-dating is supported.
        if raw_date:
            try:
                date = _dt.date.fromisoformat(raw_date)
            except ValueError:
                return _render_parameter(
                    active_tank, parameter,
                    error=f"“{raw_date}” isn't a valid date — use YYYY-MM-DD.",
                    form=form, status=400,
                )
        else:
            date = _dt.date.today()

        reading = Reading(
            tank=active_tank.id,
            parameter=parameter.id,
            date=date,
            value=value,
            unit=parameter.default_unit or "",
            note=note,
        )
        storage.append_reading(reading, _readings_path_for(active_tank.id))
        return redirect(
            url_for("parameter_view", tank_id=active_tank.id, param_id=parameter.id)
        )

    def _render_aggregate(tank_id: str):
        """Render one tank's combined Aggregate overview (spec §5.7).

        Shows every configured parameter for the active tank at once: a cards
        row (latest / trend / in-range badge per parameter) and an all-parameter
        overlay chart on a shared, normalized timeline, plus the full reading
        history. Everything is scoped to ``tank_id`` from the path (no cross-tank
        comparison in v1) and reuses the chart contract (#7), stats contract (#8)
        and per-tank range resolution (#9).

        This is the shared body behind BOTH the tank-view default landing
        (``/tank/<id>``) and the explicit ``/tank/<id>/aggregate`` URL, so
        selecting a tank opens straight into its overview with the parameter tabs
        above for drilling into a single metric.
        """
        config: Config = app.config["FISHY_CONFIG"]
        active_tank = config.tank(tank_id)
        if active_tank is None:
            abort(404, description=f"No tank configured with id '{tank_id}'.")

        # One canonical chart-series contract per parameter (active tank only).
        # Built once and fed to BOTH the cards row and the overlay so the two
        # views share a single source of truth.
        series_list = [
            _chart_series(_readings_for(active_tank.id, p.id), p, active_tank.id)
            for p in config.parameters
        ]
        # Full reading history for the active tank (task #13): the bottom of the
        # page lists every reading, most-recent-first, as its own tidy row —
        # including any archived/unknown-parameter rows (they render without a
        # tab elsewhere but must not be dropped here). Loaded from the tank's CSV.
        load_result = storage.load_readings(
            _readings_path_for(active_tank.id), emit_warnings=False
        )
        all_readings = load_result.readings
        history = _history_rows(all_readings, config, active_tank.id)
        return render_template(
            "aggregate.html",
            **_shell(
                tanks=config.tanks,
                active_tank=active_tank,
                # Tab data: reuse the same nav; mark the Aggregate tab active.
                parameters=config.parameters,
                active_param=None,
                active_tab="aggregate",
                cards=_aggregate_cards(series_list),
                overlay=_aggregate_series(series_list),
                has_any_readings=any(s["points"] for s in series_list),
                history=history,
                # Surface any archived/unknown-parameter ids as a gentle heads-up
                # next to the tabs (readings for params no longer in config).
                unknown_params=_unknown_param_ids(tank_id),
                # Non-fatal malformed-row notice (task #15): reuse the same load
                # so valid rows above still render while skipped rows are listed.
                load_warnings=load_result.warnings,
            ),
        )

    @app.route("/tank/<tank_id>/aggregate")
    def aggregate_view(tank_id: str):  # pragma: no cover - exercised via test client
        """Explicit Aggregate URL — the same overview as the tank-view landing."""
        return _render_aggregate(tank_id)

    @app.route("/health")
    def health():  # pragma: no cover - exercised via test client
        return jsonify(status="ok", app=app.config["APP_NAME"])
