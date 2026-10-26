/* My signal: evidence for one exact point from POST /api/evidence (computed in code), then the agents'
   diagnosis on request (POST /api/diagnose, polled at GET /api/runs/{id}; rendering in agents.js). */
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
const MULTI = "#334155";      // site shared by several operators
const UNKNOWN = "#9CA3AF";    // site with no known operator
const siteColor = (s) => (s.operators.length === 1 ? OP_STYLE[s.operators[0]].color : s.operators.length ? MULTI : UNKNOWN);
const SPEED = { breaks: [2, 5, 10], colors: ["#C2410C", "#F59E0B", "#93C5FD", "#2563EB"] };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
const rgb = (hex, a = 255) => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), a];
const speedColor = (v) => SPEED.colors[SPEED.breaks.filter((b) => v >= b).length];

const state = { bundle: null, request: null, run: null, runId: null, letter: null };

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
      id: "hexagon", data: [h3.cellToBoundary(b.cell_id, true)], getPolygon: (d) => d, filled: true,
      getFillColor: [21, 25, 31, 8], stroked: true, getLineColor: [21, 25, 31, 90], lineWidthUnits: "pixels", getLineWidth: 1.5,
    }),
    new deck.PolygonLayer({
      id: "radius", data: [circle(p.lat, p.lon, 1)], getPolygon: (d) => d, filled: false,
      stroked: true, getLineColor: [29, 78, 216, 140], lineWidthUnits: "pixels", getLineWidth: 1, getDashArray: [4, 3],
      extensions: [dashed],
    }),
    new deck.ScatterplotLayer({
      id: "tiles", data: tiles, getPosition: (t) => [t.lon, t.lat], getFillColor: (t) => rgb(speedColor(t.download_mbps), t.tests < 10 ? 110 : 220),
      radiusUnits: "meters", getRadius: 110, stroked: true, getLineColor: [255, 255, 255, 220], lineWidthUnits: "pixels", getLineWidth: 1,
      pickable: true,
    }),
    new deck.ScatterplotLayer({
      id: "all-sites", data: b.sites || [], getPosition: (s) => [s.lon, s.lat], getFillColor: (s) => rgb(siteColor(s)),
      stroked: true, getLineColor: (s) => (s.status === "confirmed" ? [17, 24, 39, 255] : [255, 255, 255, 255]),
      lineWidthUnits: "pixels", getLineWidth: (s) => (s.status === "confirmed" ? 2.5 : 1.2), radiusUnits: "pixels", getRadius: 5,
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
  if (layer.id === "sites") return { html: `<strong>Nearest site for ${esc(object.ops.join(", "))}</strong><br>${esc(object.sources.join(" + "))}` };
  if (layer.id === "all-sites") {
    const how = { confirmed: `confirmed: ${object.operators_confirmed.join(", ")} (Ofcom register)`, inferred: "operators inferred (crowd-sourced)", unknown: "operator unknown" }[object.status];
    return { html: `<strong>${esc(object.operators.join(", ") || "Unknown operator")}</strong> · ${fmt(object.distance_km, 1)} km<br>${esc(how)}<br>${esc(object.sources.join(" + "))}` };
  }
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
  el.innerHTML = `<h2>From this exact point</h2><ul>
    ${OPERATORS.map((o) => `<li><span class="line-swatch" style="background:${OP_STYLE[o].color}"></span>${o} line of sight</li>`).join("")}
    <li><span class="line-swatch dashed" style="--c:${BLOCKED}"></span>Blocked (10 m +); dashed operator colour = marginal</li>
    <li><span class="dot" style="background:#fff;border:2px solid ${BLOCKED}"></span>Highest obstruction</li></ul>
    <h2 class="legend-sub">Sites within 10 km</h2><ul>
    <li><span class="dot" style="background:${MULTI};box-shadow:0 0 0 2px #111827"></span>Confirmed (Ofcom register, dark ring)</li>
    <li><span class="dot" style="background:${MULTI}"></span>Inferred (crowd-sourced); colour = operator, slate = several</li>
    <li><span class="dot" style="background:${UNKNOWN}"></span>Operator unknown</li></ul>
    <h2 class="legend-sub">Ookla tiles within 2 km</h2><ul>
    ${["< 2", "2 – 5", "5 – 10", "> 10"].map((l, i) => `<li><span class="dot" style="background:${SPEED.colors[i]}"></span>${l} Mbps</li>`).join("")}
    <li><span class="line-swatch dashed" style="--c:#1D4ED8"></span>1 km (speed figure) · grey outline: this hexagon</li></ul>`;
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
      <a class="to-explore" href="/?cell=${esc(b.cell_id)}&lat=${p.lat.toFixed(5)}&lon=${p.lon.toFixed(5)}&zoom=11">See this area in Explore →</a>
    </div>

    <section class="agents" id="agents">
      <div class="agents-head"><h3>Explanation (agents)</h3>
        <label class="aud">For <select id="audience" aria-label="Explain for">
          <option value="resident">a resident</option><option value="council officer">a council officer</option>
          <option value="operator">an operator</option></select></label></div>
      <div id="agent-out"><p class="agents-intro">An Investigator, Diagnostician and Critic work through this evidence in
        rounds (up to 3): the Critic can send them back for more checks. Takes one to three minutes.</p></div>
      <div class="agent-buttons"><button type="button" class="primary" id="diagnose">Diagnose with agents</button></div>
    </section>

    <section class="best card-inner">
      <div class="best-head"><h3>Likely best network here (rule-based)</h3><span class="tag">${esc(best.label)}</span></div>
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

/* ---------- agents ---------- */

function agentResultHTML(run) {
  const r = run.result || {};
  const ev = AG.evMap(run);
  if (r.status === "failed") return `<p class="error">${esc(r.headline)} ${esc((r.notes || []).join(" "))}</p>`;
  const bn = r.best_network;
  const actions = (r.actions || []).map((a) => `<li data-ev-host>${AG.linkify(a.text, ev)}</li>`).join("");
  return `
    <div class="agent-verdict ${r.status === "partial" ? "partial" : ""}" data-ev-host>
      <p class="headline">${AG.linkify(r.headline, ev)}</p>
      ${r.explanation ? `<p class="explain">${AG.linkify(r.explanation, ev)}</p>` : ""}
      <p class="footnote">${r.rounds} round${r.rounds === 1 ? "" : "s"} · ${(r.critiques || []).filter((c) => c.verdict !== "approve").length} critic objections ·
        ${AG.fmt(r.elapsed_s, 0)} s · confidence is how well the public evidence supports a cause, not proof.</p>
    </div>
    <h4>Likely causes</h4>
    <p class="footnote">Hover or focus a bar to see how its confidence changed and why. Tap an evidence tag to see the item and its Zetaris query.</p>
    ${AG.causesHTML(r.hypotheses, ev)}
    ${(r.ruled_out || []).length ? `<h4>Ruled out</h4><ul class="ruled">${r.ruled_out.map((x) => `<li data-ev-host><strong>${esc(AG.CAUSES[x.cause] || x.cause)}</strong>
      <span class="sub-note">${AG.linkify(x.reason, ev)} ${AG.tags(x.evidence, ev)}</span></li>`).join("")}</ul>` : ""}
    ${bn ? `<h4>Best network (reviewed by the agents)</h4><p data-ev-host>${AG.linkify(bn.summary, ev)}</p>
      <ol class="net-rank">${bn.ranking.map((n) => `<li data-ev-host><span class="op-swatch" style="background:${OP_STYLE[n.operator].color}"></span>
        <strong>${esc(n.operator)}</strong> <span class="conf-word cw-${esc(n.confidence)}">${esc(n.confidence)} confidence</span>
        <span class="sub-note">${AG.linkify(n.why, ev)} ${AG.tags(n.evidence, ev)}</span></li>`).join("")}</ol>` : ""}
    ${actions ? `<h4>What to do</h4><ul class="actions">${actions}</ul>` : ""}
    ${(r.limitations || []).length ? `<details><summary>Limitations</summary><ul class="limits">${r.limitations.filter(Boolean).map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details>` : ""}
    <section class="letter" id="letter">
      <h4>Draft evidence letter</h4>
      <div class="letter-controls"><label>To <select id="recipient"><option value="operator">the mobile operator</option>
        <option value="council">the local council</option><option value="mp">the local MP</option></select></label>
        <button type="button" id="draft-letter">Draft evidence letter</button></div>
      <div id="letter-out"></div>
    </section>
    <details class="trace-wrap"><summary>How the agents worked it out (trace)</summary>${AG.traceHTML(run, "place")}</details>`;
}

function renderRun(run) {
  state.run = run;
  const out = $("agent-out");
  if (!out) return;
  const done = !["queued", "running"].includes(run.status);
  out.innerHTML = AG.progressHTML(run) + (done ? agentResultHTML(run) : "");
  const btn = $("diagnose");
  btn.disabled = !done;
  btn.textContent = done ? "Diagnose again" : "Agents working…";
  if (done && $("draft-letter")) $("draft-letter").addEventListener("click", draftLetter);
}

async function attachRun(runId) {
  state.runId = runId;
  const p = new URLSearchParams(location.search);
  p.set("run", runId);
  history.replaceState(null, "", `/signal?${p}`);
  try {
    await AG.poll(runId, renderRun, () => state.runId === runId);
  } catch (e) {
    $("agent-out").innerHTML = `<p class="error">Could not follow the run: ${esc(e.message)}</p>`;
    $("diagnose").disabled = false;
  }
}

async function diagnose() {
  const p = state.bundle.point;
  $("diagnose").disabled = true;
  $("agent-out").innerHTML = `<p class="loading">Starting the agents…</p>`;
  try {
    const r = await AG.post("/api/diagnose", { lat: p.lat, lon: p.lon, audience: $("audience").value });
    await attachRun(r.run_id);
  } catch (e) {
    $("agent-out").innerHTML = `<p class="error">Could not start the agents: ${esc(e.message)}</p>`;
    $("diagnose").disabled = false;
  }
}

async function draftLetter() {
  const btn = $("draft-letter"), out = $("letter-out"), recipient = $("recipient").value;
  btn.disabled = true;
  out.innerHTML = `<p class="loading">The letter writer is drafting from the reviewed diagnosis…</p>`;
  try {
    const l = await AG.post(`/api/runs/${state.runId}/letter`, { recipient });
    const text = `# ${l.subject}\n\n${l.body_markdown}\n`;
    out.innerHTML = `<p class="footnote">Edit before sending. Sources are listed from the evidence by code${l.guard.length ? `; the guard made ${l.guard.length} correction${l.guard.length > 1 ? "s" : ""}` : ""}.</p>
      <textarea id="letter-text" class="letter-text" rows="16" aria-label="Letter (Markdown)">${esc(text)}</textarea>
      <div class="letter-controls"><button type="button" id="letter-download">Download .md</button>
        <button type="button" id="letter-preview" class="link-btn">Preview</button></div><div id="letter-view" class="md" hidden></div>`;
    const place = (state.bundle.point.nearest_postcode || state.bundle.point.label || "location").replace(/\W+/g, "-");
    $("letter-download").addEventListener("click", () => AG.download(`evidence-letter-${recipient}-${place}.md`, $("letter-text").value));
    $("letter-preview").addEventListener("click", () => {
      const v = $("letter-view");
      v.hidden = !v.hidden;
      v.innerHTML = AG.markdown($("letter-text").value);
      $("letter-preview").textContent = v.hidden ? "Preview" : "Hide preview";
    });
  } catch (e) {
    out.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

AG.bindTags($("panel"), () => AG.evMap(state.run || {}));

/* ---------- loading ---------- */

async function check(request) {
  state.request = request;
  state.run = state.runId = null;
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
    $("diagnose").addEventListener("click", diagnose);
    if (request.run) attachRun(request.run);
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
  const run = params.get("run") || undefined;
  if (params.get("q")) { $("search-input").value = params.get("q"); check({ query: params.get("q"), run }); }
  else if (params.get("lat") && params.get("lon")) check({ lat: +params.get("lat"), lon: +params.get("lon"), run });
});
