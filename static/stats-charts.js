// Statistics page charts (Plotly).  Data comes from the server as JSON (#chart-data); the colours are
// chosen server-side (app/routers/stats.py): categorical slots 1-8 in fixed order, grey = Unknown / Other.
(function () {
  const data = JSON.parse(document.getElementById("chart-data").textContent);
  const INK = "#52514e", GRID = "#ecebe8", LAND = "#ecebe8", SURFACE = "#ffffff", BLUE = "#2a78d6";
  // sequential, one hue (blue), light -> dark; the lightest step means "one user"
  const RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
    .map((c, i, a) => [i / (a.length - 1), c]);
  const base = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", size: 12, color: INK },
    margin: { l: 44, r: 12, t: 8, b: 36 },
  };
  const cfg = { responsive: true, displayModeBar: false };
  const empty = (id, msg) => { document.getElementById(id).innerHTML = '<div class="text-muted small text-center pt-5">' + msg + "</div>"; };
  const hover = { bgcolor: "#ffffff", bordercolor: "#d6d5cf", font: { color: "#0b0b0b", size: 12 } };

  // 1) Approved ESAFs per year
  if (data.years.length) {
    Plotly.newPlot("chart-years", [{
      type: "bar", x: data.years.map(r => String(r.year)), y: data.years.map(r => r.count),
      marker: { color: BLUE, cornerradius: 4 },
      hovertemplate: "%{x}: <b>%{y}</b> approved ESAFs<extra></extra>", hoverlabel: hover,
    }], Object.assign({}, base, {
      bargap: 0.45,
      xaxis: { type: "category", tickangle: -45, linecolor: GRID, ticks: "" },
      yaxis: { gridcolor: GRID, zeroline: false, rangemode: "tozero", title: { text: "Approved ESAFs", standoff: 8 } },
    }), cfg);
  } else empty("chart-years", "No approved ESAFs in this range.");

  // 2) pies: users per career stage, ESAFs per funding agency
  function pie(id, rows, noun, msg) {
    if (!rows.length) return empty(id, msg);
    Plotly.newPlot(id, [{
      type: "pie", labels: rows.map(r => r.label), values: rows.map(r => r.value), sort: false,
      marker: { colors: rows.map(r => r.color), line: { color: SURFACE, width: 2 } },   // 2px gap between slices
      textinfo: "value", textposition: "inside", insidetextorientation: "horizontal",      // counts on the slices; % in the tooltip
      hovertemplate: "%{label}<br><b>%{value}</b> " + noun + " (%{percent})<extra></extra>", hoverlabel: hover,
    }], Object.assign({}, base, {
      margin: { l: 8, r: 8, t: 8, b: 8 },
      showlegend: true, legend: { orientation: "h", y: -0.02, yanchor: "top", font: { size: 11, color: INK } },
    }), cfg);
  }
  pie("chart-stages", data.stages, "unique users", "No users in this range.");
  pie("chart-funding", data.funding, "ESAFs", "No funding sources recorded.");

  // 3) + 4) maps: unique users, blue ramp on a log scale (a few places hold most users)
  function map(id, rows, key, name, geo, msg) {
    if (!rows.length) return empty(id, msg);
    const max = Math.max(...rows.map(r => r.unique_users));
    const ticks = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000].filter(t => t <= max);
    if (ticks.length === 0 || max / ticks[ticks.length - 1] > 1.5) ticks.push(max);   // no crowded top labels
    const locs = rows.map(r => r[key]), logMax = Math.max(Math.log10(max), 0.01);
    const labels = {            // the user count written on each region; white on the dark cells, dark on the light ones
      type: "scattergeo", mode: "text", locations: locs, locationmode: geo.locationmode,
      text: rows.map(r => String(r.unique_users)), hoverinfo: "skip", showlegend: false,
      textfont: { size: 10, color: rows.map(r => Math.log10(r.unique_users) / logMax > 0.55 ? "#ffffff" : "#0b0b0b") },
    };
    Plotly.newPlot(id, [{
      type: "choropleth", locations: locs, z: rows.map(r => Math.log10(r.unique_users)),
      text: rows.map(r => r[name]), customdata: rows.map(r => r.unique_users),
      locationmode: geo.locationmode, zmin: 0, zmax: logMax,
      colorscale: RAMP, marker: { line: { color: SURFACE, width: 0.6 } },
      colorbar: { thickness: 10, len: 0.7, title: { text: "Users", side: "top" }, outlinewidth: 0,
                  tickvals: ticks.map(Math.log10), ticktext: ticks.map(String), tickfont: { size: 11 } },
      hovertemplate: "%{text}: <b>%{customdata}</b> user(s)<extra></extra>", hoverlabel: hover,
    }, labels], Object.assign({}, base, {
      margin: { l: 0, r: 0, t: 0, b: 0 },
      geo: Object.assign({ bgcolor: "rgba(0,0,0,0)", showland: true, landcolor: LAND, showlakes: false,
                           showframe: false, coastlinecolor: "#cfcec8", countrycolor: "#cfcec8" }, geo.geo),
    }), cfg);
  }
  map("chart-states", data.states, "state", "name",
      { locationmode: "USA-states", geo: { scope: "usa", projection: { type: "albers usa" }, subunitcolor: "#cfcec8" } },
      "No users with a US state in this range.");
  map("chart-countries", data.countries, "iso3", "country",
      { locationmode: "ISO-3", geo: { projection: { type: "natural earth" }, lataxis: { range: [-58, 85] } } },
      "No users with a known country in this range.");
})();
