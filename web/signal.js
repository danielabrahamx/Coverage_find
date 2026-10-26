/* My signal: evidence for one exact point from POST /api/evidence. No LLM: all computed in code. */
"use strict";

const BASEMAP = "https://tiles.openfreemap.org/styles/positron";
const OPERATORS = ["EE", "O2", "Three", "Vodafone"];
// Distinct, non-red operator colours (red is kept for blocked lines). Drawn widest first so
// operators sharing a site show as nested stripes.
const OP_STYLE = {
  EE: { color: "#0D9488", width: 11 },
  O2: { color: "#2563EB", width: 8 },
  Vodafone: { color: "#9333EA", width: 5.5 },
  Three: { color: "#CA8A04", width: 3 },
};
const BLOCKED = "#DC2626";
const SPEED = { breaks: [2, 5, 10], colors: ["#C2410C", "#F59E0B", "#93C5FD", "#2563EB"] };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
const rgb = (hex, a = 255) => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), a];
const speedColor = (v) => SPEED.colors[SPEED.breaks.filter((b) => v >= b).length];

const state = { bundle: null, request: null };

const map = new maplibregl.Map({ container: "map", style: BASEMAP, center: [-3.2, 54.6], zoom: 4.9, attributionControl: { compact: true } });
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
const overlay = new deck.MapboxOverlay({ interleaved: false, layers: [] });
map.addControl(overlay);
const dashed = new deck.PathStyleExtension({ dash: true });

/* ---------- map layers ---------- */

function circle(lat, lon, km, n = 64) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI;
    pts.push([lon + (km / (111.32 * Math.cos((lat * Math.PI) / 180))) * Math.sin(a), lat + (km / 111.0) * Math.cos(a)]);
  }
  return pts;
}

function layers() {
  const b = state.bundle;
  if (!b) return [];
  const p = b.point;
  const rows = OPERATORS.map((o) => b.operators.find((r) => r.operator === o)).filter((r) => r && r.site)
    .sort((a, c) => OP_STYLE[c.operator].width - OP_STYLE[a.operator].width);
  const tiles = (b.items.find((i) => i.id === "speed_1km")?.value?.tiles) || [];
  const sites = {};
  rows.forEach((r) => { (sites[r.site.site_id] ||= { ...r.site, ops: [] }).ops.push(r.operator); });
  const obstructions = rows.filter((r) => r.los.class !== "clear" && r.los.obstruction_lat);
  return [
    new deck.PolygonLayer({
      id: "radius", data: [circle(p.lat, p.lon, 1)], getPolygon: (d) => d, filled: true, getFillColor: [29, 78, 216, 14],
      stroked: true, getLineColor: [29, 78, 216, 120], lineWidthUnits: "pixels", getLineWidth: 1,
    }),
    new deck.ScatterplotLayer({
      id: "tiles", data: tiles, getPosition: (t) => [t.lon, t.lat], getFillColor: (t) => rgb(speedColor(t.download_mbps), t.tests < 10 ? 120 : 230),
      radiusUnits: "meters", getRadius: 120, stroked: true, getLineColor: [255, 255, 255, 220], lineWidthUnits: "pixels", getLineWidth: 1,
      pickable: true,
    }),
    new deck.PathLayer({
      id: "lines", data: rows, getPath: (r) => [[p.lon, p.lat], [r.site.lon, r.site.lat]],
      getColor: (r) => rgb(r.los.class === "blocked" ? BLOCKED : OP_STYLE[r.operator].color),
      getWidth: (r) => OP_STYLE[r.operator].width, widthUnits: "pixels", capRounded: true,
      getDashArray: (r) => (r.los.class === "clear" ? [0, 0] : [3, 2]), dashJustified: true, extensions: [dashed],
      pickable: true,
    }),
    new deck.ScatterplotLayer({
      id: "obstructions", data: obstructions, getPosition: (r) => [r.los.obstruction_lon, r.los.obstruction_lat],
      getFillColor: [255, 255, 255, 255], getLineColor: rgb(BLOCKED), stroked: true, lineWidthUnits: "pixels", getLineWidth: 3,
      radiusUnits: "pixels", getRadius: 7, pickable: true,
    }),
    new deck.ScatterplotLayer({
      id: "sites", data: Object.values(sites), getPosition: (s) => [s.lon, s.lat],
      getFillColor: (s) => rgb(OP_STYLE[s.ops[0]].color), getLineColor: [255, 255, 255, 255], stroked: true,
      lineWidthUnits: "pixels", getLineWidth: 2, radiusUnits: "pixels", getRadius: 8, pickable: true,
    }),
    new deck.TextLayer({
      id: "site-labels", data: Object.values(sites), getPosition: (s) => [s.lon, s.lat], getText: (s) => s.ops.join(" · "),
      getSize: 13, getPixelOffset: [0, -18], getColor: [21, 25, 31, 255], fontFamily: "Manrope, sans-serif", fontWeight: 700,
      outlineWidth: 4, outlineColor: [255, 255, 255, 230], fontSettings: { sdf: true },
    }),
    new deck.ScatterplotLayer({
      id: "point", data: [p], getPosition: (d) => [d.lon, d.lat], getFillColor: [21, 25, 31, 255],
      getLineColor: [255, 255, 255, 255], stroked: true, lineWidthUnits: "pixels", getLineWidth: 3, radiusUnits: "pixels", getRadius: 8,
    }),
  ];
}

function tooltip({ object, layer }) {
  if (!object) return null;
  if (layer.id === "tiles") return { html: `<strong>Ookla tile</strong><br>${fmt(object.download_mbps, 1)} Mbps · ${object.tests} tests` };
  if (layer.id === "lines") return { html: `<strong>${object.operator}</strong>: ${esc(losWord(object.los))}, ${fmt(object.site.distance_km, 1)} km` };
  if (layer.id === "obstructions") return { html: `<strong>${object.operator}</strong>: ground ${fmt(object.los.obstruction_m, 0)} m above the line here` };
  if (layer.id === "sites") return { html: `<strong>${esc(object.ops.join(", "))}</strong><br>${esc(object.sources.join(" + "))}` };
  return null;
}

function render() {
  overlay.setProps({ layers: layers(), getTooltip: tooltip, onClick: onMapClick });
}

function fitToBundle() {
  const b = state.bundle;
  const pts = [[b.point.lon, b.point.lat], ...b.operators.filter((r) => r.site).map((r) => [r.site.lon, r.site.lat])];
  const lons = pts.map((q) => q[0]), lats = pts.map((q) => q[1]);
  const pad = window.innerWidth < 760 ? 40 : 70;
  map.fitBounds([[Math.min(...lons) - 0.01, Math.min(...lats) - 0.01], [Math.max(...lons) + 0.01, Math.max(...lats) + 0.01]],
    { padding: pad, maxZoom: 14, duration: 900 });
}

function renderLegend() {
  const el = $("op-legend");
  el.hidden = false;
  el.innerHTML = `<h2>Line of sight from this point</h2><ul>
    ${OPERATORS.map((o) => `<li><span class="line-swatch" style="background:${OP_STYLE[o].color}"></span>${o}</li>`).join("")}
    <li><span class="line-swatch dashed" style="--c:${BLOCKED}"></span>Blocked (10 m +)</li>
    <li><span class="line-swatch dashed" style="--c:#64748B"></span>Marginal (operator colour, dashed)</li>
    <li><span class="dot" style="background:#fff;border:2px solid ${BLOCKED}"></span>Highest obstruction</li>
    <li><span class="dot" style="background:${SPEED.colors[3]}"></span>Ookla tile within 1 km</li></ul>`;
}

/* ---------- panel ---------- */

const item = (id) => state.bundle.items.find((i) => i.id === id);
const strengthChip = (s) => `<span class="strength s-${esc(s)}">${esc(s)}</span>`;

function losWord(los) {
  if (los.class === "clear") return los.obstruction_m > -1 ? "clear (only just)" : "clear";
  if (los.class === "marginal") return `marginal, ${fmt(los.obstruction_m, 0)} m`;
  return `blocked, ${fmt(los.obstruction_m, 0)} m`;
}

function operatorTable(rows) {
  return `<table class="ops"><thead><tr><th>Network</th><th>Nearest site</th><th>Line of sight</th><th>Mast height</th></tr></thead><tbody>
    ${OPERATORS.map((o) => {
      const r = rows.find((x) => x.operator === o);
      const sw = `<span class="op-swatch" style="background:${OP_STYLE[o].color}"></span>`;
      if (!r || !r.site) {
        return `<tr><th scope="row">${sw}${o}</th><td colspan="3" class="muted">No site identified in our data within 10 km
          <span class="sub-note">Not the same as no coverage: crowd-sourced data is incomplete.</span></td></tr>`;
      }
      const s = r.site, l = r.los;
      return `<tr><th scope="row">${sw}${o}</th>
        <td><strong>${fmt(s.distance_km, 1)} km</strong> ${esc(s.direction)}
          <span class="sub-note">${esc(s.sources.join(" + "))}</span>
          <span class="sub-note">${r.status === "confirmed" ? `<span class="tick">✓ Confirmed</span> by Ofcom's licence register` : "Operator inferred from crowd-sourced data"}</span></td>
        <td><span class="los los-${l.class}">${esc(l.class)}</span>
          <span class="sub-note">${l.class === "clear" ? `clears by ${fmt(-l.obstruction_m, 0)} m` : `ground ${fmt(l.obstruction_m, 0)} m above the line, ${fmt(l.obstruction_distance_m / 1000, 1)} km from here`}</span></td>
        <td>${fmt(l.mast_height_m, 0)} m<span class="sub-note">${l.mast_height === "measured" ? "Ofcom register" : "assumed"}</span></td></tr>`;
    }).join("")}</tbody></table>`;
}

function speedRow(label, it) {
  if (!it) return "";
  const v = it.value, n = it.sample_size || {};
  const big = v && v.download_mbps !== undefined ? `${fmt(v.download_mbps, 1)} <small>Mbps</small>` : `<span class="muted">no tests</span>`;
  return `<div class="speed-row"><div class="speed-label">${label}</div><div class="speed-val">${big}</div>
    <div class="speed-n">${fmt(n.tests || 0, 0)} tests${n.devices ? ` · ${fmt(n.devices, 0)} devices` : ""} ${strengthChip(it.strength)}</div>
    <p class="finding">${esc(it.finding)}</p></div>`;
}

function trendHTML(it) {
  if (!it) return `<p class="muted">Not enough quarters of data for a trend here.</p>`;
  const h = it.value.history || [];
  const max = Math.max(...h.map((q) => q.download_mbps), 1);
  const bars = h.map((q) => `<div class="bar" title="${esc(q.quarter)}: ${fmt(q.download_mbps, 1)} Mbps, ${q.tests} tests">
      <span>${fmt(q.download_mbps, 0)}</span><div class="fill ${q.tests < 10 ? "weak-bar" : ""}" style="height:${Math.max(3, (q.download_mbps / max) * 36)}px"></div>
      <span>${esc(q.quarter.replace("20", "'"))}</span></div>`).join("");
  return `<div class="spark">${bars}</div><p class="finding">${esc(it.finding)} ${strengthChip(it.strength)}</p>`;
}

function evidenceLine(it) {
  if (!it) return "";
  return `<div class="ev"><p>${esc(it.finding)}</p><p class="meta">${strengthChip(it.strength)} ${esc(it.source)} · ${esc(it.data_period || "")}
    ${it.as_of ? `· ${esc(String(it.as_of).replace("T", " ").slice(0, 16))}` : ""}</p></div>`;
}

function panelHTML(b) {
  const p = b.point;
  const best = b.likely_best;
  const place = [p.admin_district, p.region && p.region !== p.country ? p.region : null, p.country].filter(Boolean).join(", ");
  const others = b.items.filter((i) => !["location"].includes(i.id));
  return `
    <div class="place">
      <h2>${esc(p.kind === "point" ? (p.nearest_postcode ? `Near ${p.nearest_postcode}` : "Selected point") : p.label)}</h2>
      <p class="sub">${esc(place)} · ${fmt(p.lat, 5)}, ${fmt(p.lon, 5)} · <span class="mono">${esc(b.cell_id)}</span>
      ${p.approximate ? ` · <span class="warn-text">approximate match</span>` : ""}</p>
    </div>

    <section class="best card-inner">
      <div class="best-head"><h3>Likely best network here</h3><span class="tag">${esc(best.label)}</span></div>
      <p class="best-text">${esc(best.text)}</p>
      <p class="footnote">Rule: ${esc(best.rule)}</p>
    </section>

    <section><h3>Networks compared (from this exact point)</h3>${operatorTable(b.operators)}
      <p class="footnote">Sites are approximate. Blocked means the ground rises above the straight line to the site, so the
      signal is likely weaker, not necessarily absent. Copernicus GLO-30 surface model.</p></section>

    <section><h3>Measured speeds</h3>
      ${speedRow("Within 1 km", item("speed_1km"))}
      ${speedRow("This cell (about 5 km²)", item("speed_cell"))}
      ${speedRow("Neighbouring cells", item("speed_neighbours"))}
      <h4>Trend, last 4 quarters</h4>${trendHTML(item("speed_trend"))}
      ${item("usage_per_head") ? `<p class="finding">${esc(item("usage_per_head").finding)} ${strengthChip(item("usage_per_head").strength)}</p>` : ""}
    </section>

    <section><h3>The wider area (Ofcom)</h3>${evidenceLine(item("ofcom_area")) || `<p class="muted">No Ofcom area figures.</p>`}
      ${evidenceLine(item("terrain_cell"))}</section>

    <section><h3>Right now</h3>${evidenceLine(item("weather"))}${evidenceLine(item("met_office_warnings"))}${evidenceLine(item("flood_warnings"))}</section>

    <section class="placeholder">
      <h3>Explanation (agents)</h3>
      <p>The agents will turn this evidence into ranked likely causes with confidence, causes ruled out and what to do,
      each linked to the evidence items below. Not built yet.</p>
      <div class="ph-buttons">
        <button disabled title="Agents not built yet">Diagnose with agents</button>
        <button disabled title="Agents not built yet">Draft evidence letter</button>
      </div>
    </section>

    <section><h3>What you can do now</h3>
      <p class="status"><a href="https://www.ofcom.org.uk/mobile-coverage-checker" target="_blank" rel="noopener">Check your address on Ofcom's mobile coverage checker</a>
      for each network's own prediction at your address.</p></section>

    <details><summary>All evidence (${b.items.length} items)</summary>
      ${others.map((i) => `<div class="ev"><p><span class="mono">${esc(i.id)}</span> ${esc(i.finding)}</p>
        <p class="meta">${strengthChip(i.strength)} ${esc(i.source)} · ${esc(i.data_period || "")} · ${esc(i.query_or_url)}
        ${i.bears_on.length ? `· bears on ${esc(i.bears_on.join(", "))}` : ""}</p></div>`).join("")}
    </details>
    <details><summary>Zetaris queries (${b.zetaris_queries.length})</summary>
      ${b.zetaris_queries.map((q) => `<p class="meta"><strong>${esc(q.id)}</strong> · ${q.rows} rows · ${q.duration_ms} ms${q.cached ? " (cached)" : ""}</p><pre class="sql">${esc(q.sql)}</pre>`).join("")}
    </details>
    <details><summary>Limitations</summary><ul class="limits">${b.limitations.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details>
    ${b.errors.length ? `<p class="error">Some sources failed: ${esc(b.errors.join("; "))}</p>` : ""}`;
}

/* ---------- loading ---------- */

async function check(request) {
  state.request = request;
  const panel = $("panel");
  panel.innerHTML = `<p class="loading">Gathering evidence for this point (Zetaris queries, line of sight, live sources)…</p>`;
  const qs = request.query ? `?q=${encodeURIComponent(request.query)}` : `?lat=${request.lat.toFixed(5)}&lon=${request.lon.toFixed(5)}`;
  history.replaceState(null, "", `/signal${qs}`);
  try {
    const r = await fetch("/api/evidence", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request) });
    const body = await r.json();
    if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
    if (state.request !== request) return;
    state.bundle = body;
    panel.innerHTML = panelHTML(body);
    panel.scrollTop = 0;
    $("map-hint").hidden = true;
    renderLegend();
    render();
    fitToBundle();
  } catch (e) {
    panel.innerHTML = `<p class="error">Could not gather evidence: ${esc(e.message)}</p>`;
  }
}

function onMapClick(info) {
  if (!info.coordinate) return;
  const [lon, lat] = info.coordinate;
  check({ lat, lon });
}

$("search").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $("search-input").value.trim();
  if (q.length >= 2) check({ query: q });
});

map.on("load", () => {
  render();  // deck.gl's onClick receives every map click, with or without a picked object
  const params = new URLSearchParams(location.search);
  if (params.get("q")) { $("search-input").value = params.get("q"); check({ query: params.get("q") }); }
  else if (params.get("lat") && params.get("lon")) check({ lat: +params.get("lat"), lon: +params.get("lon") });
});
