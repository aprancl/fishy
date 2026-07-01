/*
 * fishy — parameter time-series chart (task #7, spec §5.3).
 *
 * Rendering only. All policy (which readings, which range, in/out-of-range
 * classification) is decided server-side in fishy/__init__.py::_chart_series and
 * handed over as a JSON contract embedded in each `.reef-chart` seam:
 *
 *   { tank_id, parameter_id, display_name, unit,
 *     range: {min: number|null, max: number|null},
 *     points: [ {date: "YYYY-MM-DD", value: number, in_range: bool}, ... ] }
 *
 * This file walks every `.reef-chart` on the page, parses its inline JSON, and
 * draws a line+markers series with a shaded target-range band and out-of-range
 * points highlighted in red. It never fetches or computes ranges itself, so the
 * per-tank range swap in task #9 needs no change here.
 */
(function () {
  "use strict";

  var IN_RANGE_COLOR = "#01baef"; /* reef teal — in range */
  var OUT_RANGE_COLOR = "#e4572e"; /* coral red — out of range */
  var IN_RANGE_SYMBOL = "circle";  /* round = healthy (non-colour cue) */
  var OUT_RANGE_SYMBOL = "triangle-up"; /* distinct SHAPE = out of range (§6.4) */
  var BAND_FILL = "rgba(1, 186, 239, 0.12)";
  var THEME_FONT =
    'Nunito, "Segoe UI", system-ui, -apple-system, sans-serif';
  var THEME_INK = "#06323f";

  function renderChart(host) {
    var script = host.querySelector("script.reef-chart-data");
    if (!script) {
      return;
    }

    var data;
    try {
      data = JSON.parse(script.textContent);
    } catch (err) {
      return;
    }

    var points = (data && data.points) || [];

    // Empty state: a friendly prompt instead of a broken/empty chart.
    if (points.length === 0) {
      var msg = document.createElement("p");
      msg.className = "reef-muted reef-chart__empty";
      msg.textContent = "No readings yet — add one above to see the chart.";
      host.appendChild(msg);
      return;
    }

    var dates = points.map(function (p) { return p.date; });
    var values = points.map(function (p) { return p.value; });
    var markerColors = points.map(function (p) {
      return p.in_range ? IN_RANGE_COLOR : OUT_RANGE_COLOR;
    });
    // Accessibility (spec §6.4): out-of-range must be conveyed by MORE THAN
    // colour. In-range points are round; out-of-range points use a distinct
    // triangle SHAPE (and a touch larger), so a red/teal-blind reader can still
    // tell a flagged reading apart from a healthy one.
    var markerSymbols = points.map(function (p) {
      return p.in_range ? IN_RANGE_SYMBOL : OUT_RANGE_SYMBOL;
    });
    var markerSizes = points.map(function (p) {
      return p.in_range ? 9 : 12;
    });
    var unitSuffix = data.unit ? " " + data.unit : "";

    var series = {
      type: "scatter",
      mode: "lines+markers",
      x: dates,
      y: values,
      name: data.display_name || "value",
      line: { color: IN_RANGE_COLOR, width: 2 },
      marker: {
        color: markerColors,
        symbol: markerSymbols,
        size: markerSizes,
        line: { color: "#ffffff", width: 1.5 }
      },
      hovertemplate: "%{x}<br>%{y}" + unitSuffix + "<extra></extra>"
    };

    var shapes = [];
    var range = data.range || {};
    var hasMin = range.min !== null && range.min !== undefined;
    var hasMax = range.max !== null && range.max !== undefined;

    if (hasMin || hasMax) {
      // For a one-sided band, extend the shaded region to the data extreme on
      // the open side so the safe zone is still visibly shaded.
      var yMin = Math.min.apply(null, values);
      var yMax = Math.max.apply(null, values);
      var pad = (yMax - yMin) || Math.abs(yMax) || 1;
      var y0 = hasMin ? range.min : yMin - pad;
      var y1 = hasMax ? range.max : yMax + pad;
      shapes.push({
        type: "rect",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y",
        y0: y0,
        y1: y1,
        fillcolor: BAND_FILL,
        line: { width: 0 },
        layer: "below"
      });
    }

    var layout = {
      margin: { t: 12, r: 16, b: 44, l: 52 },
      shapes: shapes,
      font: { family: THEME_FONT, color: THEME_INK },
      xaxis: { title: "Date", type: "date", gridcolor: "rgba(11,79,108,0.08)" },
      yaxis: { title: data.unit || "Value", gridcolor: "rgba(11,79,108,0.08)" },
      showlegend: false,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      hovermode: "closest"
    };

    var config = { responsive: true, displayModeBar: false };

    if (typeof Plotly !== "undefined") {
      Plotly.newPlot(host, [series], layout, config);
    }
  }

  function renderAll() {
    var hosts = document.querySelectorAll(".reef-chart");
    for (var i = 0; i < hosts.length; i++) {
      renderChart(hosts[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }
})();
