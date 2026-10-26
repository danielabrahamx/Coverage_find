/* Council view: gap zones ranked by a priority score (computed in code, weights adjustable); agent zone
   diagnoses (POST /api/council/zones/{id}/diagnose) and a priority summary per area (agents.js renders). */
"use strict";

const BASEMAP = "https://tiles.openfreemap.org/styles/positron";
const UK_VIEW = { center: [-3.2, 54.6], zoom: 4.9 };
const FACTORS = {
  people: { label: "People affected", color: "#1D4ED8" },
  severity: { label: "Severity", color: "#C2410C" },
  persistence: { label: "Persistence", color: "#7C3AED" },
  trend: { label: "Worsening trend", color: "#0D9488" },
  operator_choice: { label: "Few operators", color: "#CA8A04" },
  need: { label: "Need (deprivation, rural)", color: "#64748B" },
};
const DEFAULT_WEIGHTS = { people: 0.35, severity: 0.25, persistence: 0.15, trend: 0.10, operator_choice: 0.15, need: 0 };
const SCORE = { breaks: [40, 55, 70, 85], colors: ["#FEF3C7", "#FDBA74", "#F97316", "#C2410C", "#7C2D12"] };
const CAND_COLORS = ["#1D4ED8", "#7C3AED", "#0D9488"];
const LABELLED_ZONES = 40;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
const rgb = (hex, a = 255) => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), a];
const scoreColor = (s) => SCORE.colors[SCORE.breaks.filter((b) => s >= b).length];

const state = { scope: "uk", weights: { ...DEFAULT_WEIGHTS }, data: null, zone: null, detail: null, request: 0, run: null, runId: null };
const FIX_LABELS = { new_site: "A new site", add_operators: "Add operators at an existing site", capacity_upgrade: "A capacity upgrade",
  gather_data: "Measure first (gather data)" };

async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}

/* ---------- map ---------- */

const map = new maplibregl.Map({ container: "map", style: BASEMAP, ...UK_VIEW, attributionControl: { compact: true } });
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
const overlay = new deck.MapboxOverlay({ interleaved: false, layers: [], getCursor: ({ isHovering }) => (isHovering ? "pointer" : "grab") });
map.addControl(overlay);

function layers() {
  const zones = state.data?.zones || [];
  const cells = zones.flatMap((z) => z.cell_ids.map((c) => ({ cell: c, zone: z })));
  const out = [
    new deck.H3HexagonLayer({
      id: "zones", data: cells, getHexagon: (d) => d.cell, extruded: false, stroked: false, coverage: 1,
      getFillColor: (d) => rgb(scoreColor(d.zone.score), state.zone && d.zone.zone_id !== state.zone ? 120 : 220),
      pickable: true, updateTriggers: { getFillColor: [state.zone, state.data] },
    }),
    new deck.TextLayer({
      id: "ranks", data: zones.slice(0, LABELLED_ZONES), getPosition: (z) => [z.centroid.lon, z.centroid.lat],
      getText: (z) => String(z.rank), getSize: 13, getColor: [21, 25, 31, 255], fontWeight: 800,
      fontFamily: "Manrope, sans-serif", outlineWidth: 4, outlineColor: [255, 255, 255, 240], fontSettings: { sdf: true },
      getPixelOffset: [0, -14],
    }),
  ];
  const d = state.detail;
  if (d) {
    const ring = d.zone.cell_ids.map((c) => h3.cellToBoundary(c, true));
    out.push(new deck.PolygonLayer({
      id: "zone-outline", data: ring, getPolygon: (p) => p, filled: false, stroked: true,
      getLineColor: [21, 25, 31, 255], lineWidthUnits: "pixels", getLineWidth: 2.5,
    }));
    const cands = d.candidates.map((c, i) => ({ ...c, n: i + 1, color: CAND_COLORS[i] }));
    out.push(new deck.LineLayer({
      id: "reach", data: cands.flatMap((c) => c.reached.map((r) => ({ c, r }))),
      getSourcePosition: (x) => [x.c.lon, x.c.lat], getTargetPosition: (x) => [x.r.lon, x.r.lat],
      getColor: (x) => rgb(x.c.color, x.r.in_zone ? 230 : 110), getWidth: (x) => (x.r.in_zone ? 2.5 : 1.2), widthUnits: "pixels",
    }));
    out.push(new deck.ScatterplotLayer({
      id: "existing", data: d.existing_sites, getPosition: (s) => [s.lon, s.lat], getFillColor: [100, 116, 139, 255],
      getLineColor: [255, 255, 255, 255], stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.5, radiusUnits: "pixels",
      getRadius: 5, pickable: true,
    }));
    out.push(new deck.ScatterplotLayer({
      id: "candidates", data: cands, getPosition: (c) => [c.lon, c.lat], getFillColor: (c) => rgb(c.color),
      getLineColor: [255, 255, 255, 255], stroked: true, lineWidthUnits: "pixels", getLineWidth: 2.5, radiusUnits: "pixels",
      getRadius: 11, pickable: true,
    }));
    const pick = agentPick();
    if (pick) {
      out.push(new deck.ScatterplotLayer({
        id: "agent-pick", data: [pick], getPosition: (c) => [c.lon, c.lat], filled: false, stroked: true,
        getLineColor: [21, 25, 31, 255], lineWidthUnits: "pixels", getLineWidth: 3, radiusUnits: "pixels", getRadius: 18,
      }));
      out.push(new deck.TextLayer({
        id: "agent-pick-label", data: [pick], getPosition: (c) => [c.lon, c.lat], getText: () => "Agents' fix", getSize: 12,
        getPixelOffset: [0, -28], getColor: [21, 25, 31, 255], fontWeight: 800, fontFamily: "Manrope, sans-serif",
        outlineWidth: 4, outlineColor: [255, 255, 255, 240], fontSettings: { sdf: true },
      }));
    }
    out.push(new deck.TextLayer({
      id: "candidate-numbers", data: cands, getPosition: (c) => [c.lon, c.lat], getText: (c) => String(c.n), getSize: 13,
      getColor: [255, 255, 255, 255], fontWeight: 800, fontFamily: "Manrope, sans-serif", fontSettings: { sdf: true },
    }));
  }
  return out;
}

function tooltip({ object, layer }) {
  if (!object) return null;
  if (layer.id === "zones") {
    const z = object.zone;
    return { html: `<strong>#${z.rank} ${esc(z.name)}</strong><br>${esc(z.council)} · ${fmt(z.people, 0)} people<br>Score ${fmt(z.score, 1)}` };
  }
  if (layer.id === "candidates") {
    return { html: `<strong>Candidate ${object.n}</strong>: new site on high ground (${fmt(object.ground_m, 0)} m)<br>`
      + `${fmt(object.zone_people_gaining, 0)} of this zone's people gain a clear line` };
  }
  if (layer.id === "existing") {
    return { html: `<strong>Existing site</strong> ${esc(object.operators.join(", ") || "operator unknown")}<br>reaches ${fmt(object.people_reached, 0)} people` };
  }
  return null;
}

function render() {
  overlay.setProps({ layers: layers(), getTooltip: tooltip, onClick: (info) => { if (info.object?.zone) openZone(info.object.zone.zone_id); } });
}

function renderLegend() {
  $("legend").innerHTML = `<h2>Priority score</h2><p class="units">0 – 100, within the chosen area</p><ul>
    ${SCORE.colors.map((c, i) => `<li><span class="swatch" style="background:${c}"></span>${["< 40", "40 – 54", "55 – 69", "70 – 84", "85 +"][i]}</li>`).join("")}
    </ul><p class="note">Numbers: rank (top ${LABELLED_ZONES}). Hexagons are the zones' poorly served cells.</p>
    ${state.detail ? `<div class="masts"><ul>
      <li><span class="dot" style="background:${CAND_COLORS[0]}"></span>Candidate new sites (1–3), lines to cells they reach</li>
      <li><span class="dot" style="background:#64748B"></span>Existing sites considered</li></ul></div>` : ""}`;
}

/* ---------- weights ---------- */

function renderSliders() {
  $("sliders").innerHTML = Object.entries(FACTORS).map(([k, f]) => {
    const disabled = k === "need";
    return `<label class="slider ${disabled ? "disabled" : ""}"><span class="f-dot" style="background:${f.color}"></span>
      <span class="f-name">${f.label}</span>
      <input type="range" min="0" max="1" step="0.05" value="${state.weights[k]}" data-k="${k}" ${disabled ? "disabled" : ""} aria-label="${f.label} weight">
      <span class="f-val" id="w-${k}">${disabled ? "not built" : Math.round(state.weights[k] * 100)}</span></label>`;
  }).join("");
  $("sliders").querySelectorAll("input").forEach((el) => el.addEventListener("input", () => {
    state.weights[el.dataset.k] = +el.value;
    $(`w-${el.dataset.k}`).textContent = Math.round(+el.value * 100);
    clearTimeout(state.timer);
    state.timer = setTimeout(loadZones, 250);
  }));
  $("weights-note").textContent = "Weights are rescaled to add up to 100%. Data confidence (Ookla tests) is shown beside each zone, not scored. "
    + "Need (deprivation, rural–urban) joins the score once that data is built.";
}

const weightParam = () => Object.entries(state.weights).filter(([k]) => k !== "need").map(([k, v]) => `${k}:${v}`).join(",");

/* ---------- ranked list ---------- */

function bar(breakdown) {
  return `<div class="score-bar" title="${esc(Object.entries(breakdown).map(([k, b]) => `${FACTORS[k].label}: ${b.contribution}`).join("\n"))}">
    ${Object.entries(breakdown).map(([k, b]) => `<span style="width:${b.contribution}%;background:${FACTORS[k].color}"></span>`).join("")}</div>`;
}

function renderTable() {
  const d = state.data;
  $("list-summary").innerHTML = `<strong>${fmt(d.zones_in_scope, 0)} gap zones</strong> · ${fmt(d.people_in_zones, 0)} people ·
    ${esc(scopeName(d.scope))}. Ranked by priority (${d.duration_ms} ms through Zetaris).`;
  $("zones-table").querySelector("tbody").innerHTML = d.zones.map((z) => `
    <tr data-zone="${z.zone_id}" class="${z.zone_id === state.zone ? "selected" : ""}" tabindex="0">
      <td class="rank">${z.rank}</td>
      <td><strong>${esc(z.name)}</strong><span class="sub-note">${esc(z.council)} · ${z.zone_id} ·
        <span class="conf conf-${z.confidence}">${z.confidence} confidence</span></span></td>
      <td class="num">${fmt(z.people, 0)}</td>
      <td class="num">${z.median_speed_mbps === null ? "–" : `${fmt(z.median_speed_mbps, 1)}`}<span class="sub-note">${fmt(z.tests, 0)} test${z.tests === 1 ? "" : "s"}</span></td>
      <td class="num">${z.persistence === null ? "–" : `${fmt(z.persistence * 100, 0)}%`}</td>
      <td class="num">${fmt(z.operators_mean, 1)}</td>
      <td class="score-cell"><strong>${fmt(z.score, 1)}</strong>${bar(z.breakdown)}</td>
    </tr>`).join("");
  $("zones-table").querySelectorAll("tr[data-zone]").forEach((tr) => {
    const go = () => openZone(tr.dataset.zone);
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });
  $("csv").href = `/api/council/zones.csv?scope=${encodeURIComponent(state.scope)}&weights=${encodeURIComponent(weightParam())}`;
}

async function loadZones() {
  const id = ++state.request;
  $("list-summary").textContent = "Ranking zones…";
  try {
    const d = await getJSON(`/api/council/zones?scope=${encodeURIComponent(state.scope)}&weights=${encodeURIComponent(weightParam())}`);
    if (id !== state.request) return;
    state.data = d;
    renderTable();
    render();
  } catch (e) {
    $("list-summary").innerHTML = `<span class="error">Could not load zones: ${esc(e.message)}</span>`;
  }
}

function fitZones(zones) {
  if (!zones.length) return;
  const lats = zones.map((z) => z.centroid.lat), lons = zones.map((z) => z.centroid.lon);
  map.fitBounds([[Math.min(...lons) - 0.15, Math.min(...lats) - 0.1], [Math.max(...lons) + 0.15, Math.max(...lats) + 0.1]],
    { padding: 40, maxZoom: 11, duration: 800 });
}

/* ---------- scopes ---------- */

let SCOPES = null;
const scopeName = (s) => (s === "uk" ? "United Kingdom" : s.startsWith("nation:") ? s.slice(7)
  : (SCOPES?.councils.find((c) => c.scope === s)?.name || s));

async function loadScopes() {
  SCOPES = await getJSON("/api/council/scopes");
  const byNation = {};
  SCOPES.councils.forEach((c) => (byNation[c.nation] ||= []).push(c));
  $("scope").innerHTML = `<option value="uk">United Kingdom (${SCOPES.uk.zones} zones)</option>
    <optgroup label="Nations">${SCOPES.nations.map((n) => `<option value="${n.scope}">${esc(n.name)} (${n.zones})</option>`).join("")}</optgroup>
    ${Object.entries(byNation).map(([n, cs]) => `<optgroup label="Councils: ${esc(n)}">${cs.map((c) =>
      `<option value="${c.scope}">${esc(c.name)} (${c.zones})</option>`).join("")}</optgroup>`).join("")}`;
  $("scope").value = state.scope;
  $("scope").addEventListener("change", async () => {
    state.scope = $("scope").value;
    closeZone();
    syncUrl();
    await loadZones();
    fitZones(state.data.zones);
  });
}

/* ---------- zone detail ---------- */

function candidateHTML(c, i) {
  return `<li class="cand"><span class="cand-n" style="background:${CAND_COLORS[i]}">${i + 1}</span>
    <div><strong>New site on high ground</strong> (${fmt(c.ground_m, 0)} m, ${c.in_zone ? "inside the zone" : "near the zone"})
    <span class="sub-note">${fmt(c.zone_people_gaining, 0)} of the zone's people gain a clear line ·
      ${fmt(c.poor_people_gaining, 0)} poorly served people in all · ${fmt(c.people_reached, 0)} people reached
      (${c.reached.length} of ${c.cells_checked} cells, 25 m mast)</span></div></li>`;
}

function detailHTML(d) {
  const z = d.zone, f = d.fix;
  const ranks = Object.entries(d.ranks).map(([s, r]) => `#${r.rank} of ${r.of} in ${esc(scopeName(s))}`).join(" · ");
  const bd = (d.ranks[state.scope] || d.ranks.uk || {}).breakdown || z.breakdown || {};
  return `
    <h2>${esc(z.name)}</h2>
    <p class="sub">${esc(z.council)} · ${esc(z.nation)} · ${z.zone_id} · ${ranks}</p>
    <div class="zone-links">
      <a href="${z.links.explore}">See its cells in Explore →</a>
      <a href="${z.links.signal}">My signal at its centre →</a>
    </div>
    <section><h3>Evidence summary</h3><ul class="summary">${d.summary.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></section>
    <section><h3>Score breakdown</h3>${bar(bd)}
      <dl class="kv">${Object.entries(bd).map(([k, b]) => `<dt><span class="f-dot" style="background:${FACTORS[k].color}"></span>${FACTORS[k].label}</dt>
        <dd>${fmt(b.contribution, 1)}${b.no_data ? " (no data: neutral)" : ""}</dd>`).join("")}</dl></section>
    <section><h3>Suggested fix</h3>
      <p class="fix"><strong>${esc(f.label)}</strong>${f.secondary_label ? `, then ${esc(f.secondary_label.toLowerCase())}` : ""}</p>
      <ul class="summary">${f.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      <p class="footnote">${esc(f.note)}</p></section>
    <section><h3>Candidate sites (top 3 of ${d.evaluated.new_sites} high points)</h3>
      ${d.candidates.length ? `<ol class="cands">${d.candidates.map(candidateHTML).join("")}</ol>` : `<p class="muted">No high points found.</p>`}
      ${d.existing_sites.length ? `<p class="status">Existing sites nearby (for adding operators): ${d.existing_sites.map((s) =>
        `${esc(s.operators.join(", ") || "operator unknown")} at ${fmt(s.distance_to_zone_km, 1)} km, reaching ${fmt(s.zone_people_gaining, 0)} of the zone's people`).join("; ")}.</p>` : ""}
      <details><summary>Method and limits</summary><ul class="limits">${d.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details></section>
    <section class="agents" id="zone-agents">
      <div class="agents-head"><h3>Agents</h3></div>
      <div id="zone-agent-out"><p class="agents-intro">The agents diagnose the zone's main cause in rounds (the Critic can ask
        for more checks), then the Fix planner proposes a fix from the candidates above and the Critic reviews it. One to three minutes.</p></div>
      <div class="agent-buttons"><button type="button" class="primary" id="zone-diagnose">Diagnose zone (agents)</button></div>
    </section>
    <details><summary>Data details: ${d.zetaris_queries.length} Zetaris queries · ${d.duration_ms} ms (planning ${d.planning_ms} ms)</summary>
      ${d.zetaris_queries.map((q) => `<p class="meta">${q.rows} rows · ${q.duration_ms} ms</p><pre class="sql">${esc(q.sql)}</pre>`).join("")}</details>`;
}

/* ---------- agents: zone diagnosis ---------- */

function agentPick() {
  const f = state.run?.result?.fix_plan;
  return f && f.candidate_values && f.candidate_values.lat !== undefined && state.run.result.zone?.zone_id === state.zone ? f.candidate_values : null;
}

function zoneResultHTML(run) {
  const r = run.result || {};
  const ev = AG.evMap(run);
  if (r.status === "failed") return `<p class="error">${esc(r.headline)} ${esc((r.notes || []).join(" "))}</p>`;
  const top = (r.hypotheses || []).find((h) => h.status === "active");
  const f = r.fix_plan, v = f?.candidate_values || {};
  const objections = (r.critiques || []).filter((c) => c.verdict !== "approve");
  return `
    <div class="agent-verdict ${r.status === "partial" ? "partial" : ""}" data-ev-host>
      <p class="headline">${AG.linkify(r.headline, ev)}</p>
      ${r.explanation ? `<p class="explain">${AG.linkify(r.explanation, ev)}</p>` : ""}
      <p class="footnote">${r.rounds} round${r.rounds === 1 ? "" : "s"} · ${AG.fmt(r.elapsed_s, 0)} s${top ? ` · main cause: ${esc(AG.CAUSES[top.cause] || top.cause)} (${AG.pct(top.confidence)})` : ""}</p>
    </div>
    <h4>Causes</h4>${AG.causesHTML(r.hypotheses, ev)}
    ${f ? `<h4>Recommended fix</h4><div class="fix-card" data-ev-host>
      <p class="fix"><strong>${esc(FIX_LABELS[f.fix_type] || f.fix_type)}</strong>${f.candidate ? ` at candidate ${esc(f.candidate.replace("cand_", ""))} (outlined on the map)` : ""}</p>
      ${v.zone_people_gaining !== undefined ? `<p><span class="people">${AG.fmt(v.zone_people_gaining, 0)}</span> of the zone's people would gain a clear line
        <span class="sub-note">${AG.fmt(v.poor_people_gaining, 0)} poorly served people in all · ${AG.fmt(v.people_reached, 0)} people reached ·
        ground ${AG.fmt(v.ground_m, 0)} m. Numbers from the candidate's evidence ${AG.tags([f.candidate], ev)}, not the model.</span></p>` : ""}
      <p class="cause-text">${AG.linkify(f.why, ev)}</p>
      <p class="sub-note">Assumptions: ${esc((f.assumptions || []).join("; "))}</p>
      ${f.review ? `<p class="sub-note"><span class="verdict v-${esc(f.review.verdict)}">${esc(f.review.verdict)}</span> Critic${f.revisions ? ` (after ${f.revisions} revision${f.revisions > 1 ? "s" : ""})` : ""}: ${AG.linkify(f.review.reason, ev)}</p>` : ""}
    </div>` : ""}
    <h4>Critic notes</h4>
    ${objections.length ? `<ul class="ruled">${objections.map((c) => `<li data-ev-host><span class="verdict v-${esc(c.verdict)}">${esc(c.verdict.replace("_", " "))}</span>
      <strong>${esc(c.target === "fix_plan" ? "Fix plan" : AG.CAUSES[c.target] || c.target)}</strong> (round ${esc(c.round)})
      <span class="sub-note">${AG.linkify(c.reason, ev)}${(c.issues || []).length ? ` Issues: ${esc(c.issues.join("; "))}` : ""}</span></li>`).join("")}</ul>`
      : `<p class="muted">The critic approved every belief${f?.review ? " and the fix plan" : ""}.</p>`}
    <details class="trace-wrap"><summary>How the agents worked it out (trace)</summary>${AG.traceHTML(run, "zone")}</details>`;
}

function renderZoneRun(run) {
  state.run = run;
  const out = $("zone-agent-out");
  if (!out) return;
  const done = !["queued", "running"].includes(run.status);
  out.innerHTML = AG.progressHTML(run) + (done ? zoneResultHTML(run) : "");
  const btn = $("zone-diagnose");
  btn.disabled = !done;
  btn.textContent = done ? "Diagnose again" : "Agents working…";
  if (done) render();
}

async function attachZoneRun(runId) {
  state.runId = runId;
  syncUrl();
  try {
    await AG.poll(runId, renderZoneRun, () => state.runId === runId);
  } catch (e) {
    $("zone-agent-out").innerHTML = `<p class="error">Could not follow the run: ${esc(e.message)}</p>`;
  }
}

async function diagnoseZone() {
  const zoneId = state.zone;
  $("zone-diagnose").disabled = true;
  $("zone-agent-out").innerHTML = `<p class="loading">Starting the agents…</p>`;
  try {
    const r = await AG.post(`/api/council/zones/${zoneId}/diagnose`);
    if (state.zone === zoneId) await attachZoneRun(r.run_id);
  } catch (e) {
    $("zone-agent-out").innerHTML = `<p class="error">Could not start the agents: ${esc(e.message)}</p>`;
    $("zone-diagnose").disabled = false;
  }
}

/* ---------- agents: priority summary for the area ---------- */

async function prioritySummary() {
  closeZone();
  $("panel").hidden = false;
  const scope = state.scope;
  $("panel-body").innerHTML = `<h2>Priority summary</h2><p class="sub">${esc(scopeName(scope))}</p>
    <p class="loading">The advisor is writing a summary of the top zones (with any agent diagnoses in Meterless)…</p>`;
  try {
    const r = await AG.post("/api/council/summary", { scope, weights: weightParam() });
    if (state.scope !== scope || state.zone) return;
    const md = `# ${r.title}\n\n${r.body_markdown}\n`;
    const html = AG.markdown(md).replace(/\[(Z\d{5})\]/g, (m, z) => `<button type="button" class="ev-tag zone-link" data-zone="${z}">${z}</button>`);
    $("panel-body").innerHTML = `<div class="summary-panel"><p class="sub">${esc(scopeName(scope))} · top ${r.zones.length} zones ·
      ${r.diagnosed.length} with an agent diagnosis${r.guard.length ? ` · the guard made ${r.guard.length} correction${r.guard.length > 1 ? "s" : ""}` : ""}</p>
      <div class="md">${html}</div>
      <div class="letter-controls"><button type="button" id="summary-download">Download .md</button></div>
      <p class="footnote">Written by the Advisor agent from the ranked zones; numbers are checked against them by code. The score ranks need, not certainty.</p></div>`;
    $("summary-download").addEventListener("click", () => AG.download(`priority-summary-${scope.replace(/\W+/g, "-")}.md`, md));
    $("panel-body").querySelectorAll(".zone-link").forEach((b) => b.addEventListener("click", () => openZone(b.dataset.zone)));
  } catch (e) {
    $("panel-body").innerHTML += `<p class="error">${esc(e.message)}</p>`;
  }
}

async function openZone(zoneId, runId = null) {
  state.zone = zoneId;
  state.run = state.runId = null;
  syncUrl();
  render();
  document.querySelectorAll("tr[data-zone]").forEach((tr) => tr.classList.toggle("selected", tr.dataset.zone === zoneId));
  $("panel").hidden = false;
  $("panel-body").innerHTML = `<p class="loading">Loading zone, checking candidate sites…</p>`;
  try {
    const d = await getJSON(`/api/council/zones/${zoneId}?weights=${encodeURIComponent(weightParam())}`);
    if (state.zone !== zoneId) return;
    state.detail = d;
    $("panel-body").innerHTML = detailHTML(d);
    $("zone-diagnose").addEventListener("click", diagnoseZone);
    if (runId) attachZoneRun(runId);
    $("panel").scrollTop = 0;
    const pts = [...d.cells.map((c) => [c.lon, c.lat]), ...d.candidates.map((c) => [c.lon, c.lat])];
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    const right = window.innerWidth > 760 ? 420 : 40;
    map.fitBounds([[Math.min(...lons) - 0.03, Math.min(...lats) - 0.02], [Math.max(...lons) + 0.03, Math.max(...lats) + 0.02]],
      { padding: { top: 40, bottom: 40, left: 40, right }, maxZoom: 12.5, duration: 800 });
    renderLegend();
    render();
  } catch (e) {
    $("panel-body").innerHTML = `<p class="error">Could not load the zone: ${esc(e.message)}</p>`;
  }
}

function closeZone() {
  state.zone = null;
  state.run = state.runId = null;
  state.detail = null;
  $("panel").hidden = true;
  document.querySelectorAll("tr.selected").forEach((tr) => tr.classList.remove("selected"));
  syncUrl();
  renderLegend();
  render();
}
$("panel-close").addEventListener("click", closeZone);
$("summary-btn").addEventListener("click", prioritySummary);
AG.bindTags($("panel"), () => AG.evMap(state.run || {}));

function syncUrl() {
  const p = new URLSearchParams();
  if (state.scope !== "uk") p.set("scope", state.scope);
  if (state.zone) p.set("zone", state.zone);
  if (state.zone && state.runId) p.set("run", state.runId);
  history.replaceState(null, "", `/council${p.toString() ? `?${p}` : ""}`);
}

$("reset").addEventListener("click", () => {
  state.weights = { ...DEFAULT_WEIGHTS };
  renderSliders();
  loadZones();
});

/* ---------- start ---------- */

map.on("load", async () => {
  const params = new URLSearchParams(location.search);
  state.scope = params.get("scope") || "uk";
  renderSliders();
  renderLegend();
  try {
    await loadScopes();
    await loadZones();
    if (state.scope !== "uk") fitZones(state.data.zones);
    if (params.get("zone")) openZone(params.get("zone"), params.get("run"));
  } catch (e) {
    $("list-summary").innerHTML = `<span class="error">${esc(e.message)}</span>`;
  }
});
