/*
 * fishy — aggregate all-parameter overlay chart (task #12, spec §5.7).
 *
 * Rendering only. All policy (which readings, which range, in/out-of-range
 * classification, and the per-series min-max normalization that makes wildly
 * different scales comparable) is decided server-side in
 * fishy/__init__.py::_aggregate_series and handed over as a JSON LIST embedded
 * in the `.reef-aggregate-chart` seam. Each list element is a chart-series
 * contract (one per parameter for the active tank):
 *
 *   { tank_id, parameter_id, display_name, unit,
 *     range: {min: number|null, max: number|null},
 *     points: [ {date: "YYYY-MM-DD", value: number,
 *                norm: number, in_range: bool}, ... ] }
 *
 * This file parses that list and overlays one line+markers trace per parameter
 * on a SHARED time x-axis and a common normalized 0..1 y-axis (so a 1.026
 * specific-gravity line and a 420 ppm calcium line are visually comparable).
 * The hover shows each point's REAL value + unit. Out-of-range points are
 * highlighted in coral. Plotly's legend already toggles individual traces on
 * click; we label each legend entry with the display name + unit.
 */
(function () {
  "use strict";

  var OUT_RANGE_COLOR = "#e4572e"; /* coral red — out of range */
  var IN_RANGE_SYMBOL = "circle";  /* round = healthy (non-colour cue) */
  var OUT_RANGE_SYMBOL = "triangle-up"; /* distinct SHAPE = out of range (§6.4) */
  /* Themed type: Nunito body, Baloo 2 display for axis titles (matches the
     app's --reef-font-body / --reef-font-display tokens). */
  var THEME_FONT =
    'Nunito, "Segoe UI", system-ui, -apple-system, sans-serif';
  var THEME_DISPLAY_FONT =
    '"Baloo 2", Nunito, "Segoe UI", system-ui, sans-serif';
  var THEME_INK = "#06323f";   /* --reef-ink */
  var THEME_MUTED = "#4d6b78"; /* --reef-muted — ticks + axis lines */
  var THEME_GRID = "rgba(11, 79, 108, 0.08)"; /* subtle deep-ocean gridlines */
  var THEME_DEEP = "#0b4f6c";  /* --reef-deep — hover surface */

  /* A qualitative palette so each parameter's line is easy to tell apart.
     Cycled if there are more parameters than colours. */
  var SERIES_COLORS = [
    "#01baef", /* reef teal   */
    "#0b4f6c", /* deep        */
    "#20bf55", /* lagoon      */
    "#f4a261", /* sand-orange */
    "#9b5de5", /* urchin      */
    "#ff6b6b", /* coral       */
    "#118ab2", /* ocean       */
    "#e9c46a"  /* seagrass    */
  ];

  function legendName(series) {
    var name = series.display_name || series.parameter_id || "series";
    return series.unit ? name + " (" + series.unit + ")" : name;
  }

  function buildTrace(series, colorIndex) {
    var points = series.points || [];
    var color = SERIES_COLORS[colorIndex % SERIES_COLORS.length];
    var unitSuffix = series.unit ? " " + series.unit : "";

    // Out-of-range points are coloured coral; in-range points take the series
    // colour. The line stays the series colour so the parameter is still
    // identifiable even where a point is flagged.
    var markerColors = points.map(function (p) {
      return p.in_range ? color : OUT_RANGE_COLOR;
    });
    // Accessibility (spec §6.4): out-of-range conveyed by SHAPE too, not just
    // colour — in-range points are round, out-of-range points are triangles and
    // slightly larger, so flagged readings stand out without relying on hue.
    var markerSymbols = points.map(function (p) {
      return p.in_range ? IN_RANGE_SYMBOL : OUT_RANGE_SYMBOL;
    });
    var markerSizes = points.map(function (p) {
      return p.in_range ? 8 : 11;
    });

    return {
      type: "scatter",
      mode: "lines+markers",
      x: points.map(function (p) { return p.date; }),
      y: points.map(function (p) { return p.norm; }),
      // Carry the real value so the hover shows it (the y-axis is normalized).
      customdata: points.map(function (p) { return p.value; }),
      name: legendName(series),
      line: { color: color, width: 2.5 },
      marker: {
        color: markerColors,
        symbol: markerSymbols,
        size: markerSizes,
        line: { color: "#ffffff", width: 1.5 }
      },
      hovertemplate:
        "<b>" + legendName(series) + "</b><br>" +
        "%{x}<br>%{customdata}" + unitSuffix +
        "<extra></extra>"
    };
  }

  function renderOverlay(host) {
    var script = host.querySelector("script.reef-aggregate-data");
    if (!script) {
      return;
    }

    var seriesList;
    try {
      seriesList = JSON.parse(script.textContent);
    } catch (err) {
      return;
    }

    if (!seriesList || !seriesList.length) {
      showEmpty(host);
      return;
    }

    // Only parameters that actually have readings become traces; a parameter
    // with no points would add a phantom legend entry with nothing to plot.
    var traces = [];
    for (var i = 0; i < seriesList.length; i++) {
      var series = seriesList[i];
      if (series.points && series.points.length) {
        traces.push(buildTrace(series, traces.length));
      }
    }

    if (!traces.length) {
      showEmpty(host);
      return;
    }

    var axisBase = {
      gridcolor: THEME_GRID,
      zeroline: false,
      linecolor: "rgba(11, 79, 108, 0.18)",
      tickfont: { family: THEME_FONT, color: THEME_MUTED, size: 12 },
      titlefont: { family: THEME_DISPLAY_FONT, color: THEME_INK, size: 14 }
    };

    var layout = {
      margin: { t: 16, r: 18, b: 48, l: 56 },
      font: { family: THEME_FONT, color: THEME_INK, size: 13 },
      xaxis: Object.assign({ title: "Date", type: "date" }, axisBase),
      yaxis: Object.assign(
        { title: "Normalized (0–1)", range: [-0.05, 1.05], fixedrange: true },
        axisBase
      ),
      showlegend: true,
      // Horizontal legend above the plot wraps to multiple rows, keeping many
      // overlaid series legible at narrow widths (spec §5.6 edge case).
      legend: {
        orientation: "h",
        x: 0,
        y: 1.14,
        font: { family: THEME_FONT, color: THEME_INK, size: 12 },
        bgcolor: "rgba(0,0,0,0)"
      },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      hovermode: "closest",
      hoverlabel: {
        bgcolor: THEME_DEEP,
        bordercolor: THEME_DEEP,
        font: { family: THEME_FONT, color: "#ffffff", size: 13 }
      }
    };

    var config = { responsive: true, displayModeBar: false };

    if (typeof Plotly !== "undefined") {
      Plotly.newPlot(host, traces, layout, config);
    }
  }

  function showEmpty(host) {
    var msg = document.createElement("p");
    msg.className = "reef-muted reef-aggregate-chart__empty";
    msg.textContent =
      "No readings yet — log a reading from a parameter tab to see the overlay.";
    host.appendChild(msg);
  }

  function renderAll() {
    var hosts = document.querySelectorAll(".reef-aggregate-chart");
    for (var i = 0; i < hosts.length; i++) {
      renderOverlay(hosts[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }
})();
