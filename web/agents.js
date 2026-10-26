/* Agent runs on the pages: start, poll, progress strip, causes, evidence tags, trace and World Model.
   Shared by My signal (signal.js) and Council view (council.js). Every number shown comes from the
   run's result or its evidence items; the agents' text is shown as written, after the code guard. */
"use strict";

const AG = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: d }));
  const CAUSES = {
    terrain_blocking: "Hills blocking the signal", distance_to_mast: "Distance to the nearest site",
    single_operator: "Few networks nearby", capacity_strain: "Capacity strain (busy network)", weather: "Weather",
    active_incident: "Active incident", insufficient_data: "Not enough data to tell",
  };
  const AGENTS = { investigator: "Investigator", diagnostician: "Diagnostician", critic: "Critic", advisor: "Advisor",
    fix_planner: "Fix planner", letter_writer: "Letter writer", coordinator: "Coordinator", guard: "Guard" };
  const word = (c) => (c >= 0.7 ? "likely" : c >= 0.4 ? "possible" : "unlikely");
  const pct = (c) => `${Math.round(c * 100)}%`;
  const POLL_MS = 1500;

  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof out.detail === "string" ? out.detail : JSON.stringify(out.detail || r.statusText));
    return out;
  }

  /* Poll a run until it finishes; onUpdate(run) after every poll. Returns the final run. */
  async function poll(runId, onUpdate, isCurrent = () => true) {
    for (;;) {
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      const run = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(run.detail || r.statusText);
      if (!isCurrent()) return null;
      onUpdate(run);
      if (!["queued", "running"].includes(run.status)) return run;
      await new Promise((ok) => setTimeout(ok, POLL_MS));
    }
  }

  /* ---------- progress strip: one chip per agent call, tool calls grouped ---------- */

  function progressHTML(run) {
    const groups = {};
    for (const s of run.steps || []) (groups[s.round || 0] ||= []).push(s);
    const order = Object.keys(groups).map(Number).sort((a, b) => (a || 99) - (b || 99));
    const rows = order.map((r) => {
      const chips = [];
      let tools = null;
      for (const s of groups[r]) {
        if (s.kind === "phase") continue;
        if (s.kind === "tool") {
          if (!tools) { tools = { kind: "tools", steps: [] }; chips.push(tools); }
          tools.steps.push(s);
          continue;
        }
        tools = null;
        chips.push(s);
      }
      return `<div class="pg-row"><span class="pg-round">${r ? `Round ${r}` : "Final"}</span><div class="pg-chips">${chips.map(chipHTML).join("")}</div></div>`;
    });
    const cur = run.current;
    const status = run.status === "queued" ? "Waiting for a free slot…"
      : run.status === "running" ? `${cur ? `${esc(AGENTS[cur.agent] || cur.agent)}: ${esc(cur.label)}` : "Starting"}…`
      : run.status === "complete" ? "Finished" : run.status === "partial" ? "Finished with a partial result" : "Failed";
    return `<div class="progress ${run.status === "running" || run.status === "queued" ? "live" : ""}">
      <div class="pg-head"><span class="pg-status">${status}</span><span class="pg-time">${fmt(run.elapsed_s, 0)} s</span></div>
      ${rows.join("") || `<p class="muted">Queued.</p>`}</div>`;
  }

  function chipHTML(c) {
    if (c.kind === "tools") {
      const running = c.steps.some((s) => s.status === "running");
      const failed = c.steps.filter((s) => s.status === "failed").length;
      const title = c.steps.map((s) => `${s.label}: ${s.summary || s.status}`).join("\n");
      return `<span class="pchip tool ${running ? "running" : failed ? "failed" : "done"}" title="${esc(title)}">
        ${running ? "" : "✓ "}${c.steps.length} check${c.steps.length > 1 ? "s" : ""}${failed ? ` (${failed} failed)` : ""}</span>`;
    }
    const name = (AGENTS[c.agent] || c.agent) + (/rewrite/.test(c.label) ? " · rewrite" : "");
    const t = c.duration_ms ? ` ${fmt(c.duration_ms / 1000, 0)} s` : "";
    const mark = c.status === "running" ? "" : c.status === "failed" ? "✕ " : "✓ ";
    const warn = /retr|switched/.test(c.summary || "") ? " warn" : "";
    return `<span class="pchip agent a-${esc(c.agent)} ${esc(c.status)}${warn}" title="${esc(`${c.label}${c.summary ? `: ${c.summary}` : ""}`)}">${mark}${esc(name)}${t}</span>`;
  }

  /* ---------- evidence tags ---------- */

  function linkify(text, ev) {
    return esc(text).replace(/\[([A-Za-z0-9_]+)\]/g, (m, id) => (ev[id] ? tag(id, ev) : ""));
  }

  function tag(id, ev) {
    const e = ev[id];
    return `<button type="button" class="ev-tag s-${esc(e?.strength || "none")}" data-ev="${esc(id)}" title="${esc(e?.finding || id)}">${esc(id)}</button>`;
  }

  function tags(ids, ev) {
    return (ids || []).filter((i) => ev[i]).map((i) => tag(i, ev)).join("");
  }

  function evidenceDetailHTML(e) {
    const sql = (e.zetaris || []).map((q) => `<p class="meta">Zetaris query ${esc(q.id)}</p><pre class="sql">${esc(q.sql)}</pre>`).join("");
    const size = e.sample_size ? Object.entries(e.sample_size).map(([k, v]) => `${fmt(v, 0)} ${k.replace(/_/g, " ")}`).join(", ") : "";
    return `<div class="ev-detail"><p><span class="mono">${esc(e.evidence_id)}</span> ${esc(e.finding)}</p>
      <p class="meta"><span class="strength s-${esc(e.strength)}">${esc(e.strength)}</span> ${esc(e.source)} · data ${esc(e.data_period || "–")}
      · as of ${esc(String(e.as_of || "").slice(0, 16).replace("T", " "))}${size ? ` · ${esc(size)}` : ""}
      ${e.tool ? ` · from ${esc(e.tool)}() in round ${esc(e.round)}` : ""}</p>
      ${sql || `<p class="meta">Source: ${esc(e.query_or_url)}</p>`}</div>`;
  }

  /* Clicking a tag opens the item (with its Zetaris SQL) under the block it sits in; again closes it. */
  function bindTags(root, getEv) {
    root.addEventListener("click", (event) => {
      const b = event.target.closest(".ev-tag");
      if (!b || !root.contains(b)) return;
      const host = b.closest("[data-ev-host]") || b.parentElement;
      let box = host.querySelector(":scope > .ev-open");
      const same = box && box.dataset.ev === b.dataset.ev;
      root.querySelectorAll(".ev-tag.open").forEach((x) => x.classList.remove("open"));
      if (box) box.remove();
      if (same) return;
      const e = getEv()[b.dataset.ev];
      if (!e) return;
      box = document.createElement("div");
      box.className = "ev-open";
      box.dataset.ev = b.dataset.ev;
      box.innerHTML = evidenceDetailHTML(e);
      host.appendChild(box);
      b.classList.add("open");
    });
  }

  /* ---------- causes with confidence bars (hover: history with reasons) ---------- */

  function historyHTML(h) {
    const steps = (h.history || []).map((x, i) => `<li><span class="hist-conf">${x.previous != null ? `${pct(x.previous)} → ` : ""}${pct(x.confidence)}</span>
      <span class="hist-by">${i === 0 ? "proposed" : `round ${esc(x.round)}, ${esc(AGENTS[x.by] || x.by)}`}</span>
      ${i ? `<span class="hist-why">${esc(String(x.reason || "").replace(/^critic( rejected)?: /, ""))}</span>` : ""}</li>`).join("");
    return `<ul class="hist">${steps}</ul>`;
  }

  function causesHTML(hyps, ev) {
    const sorted = [...(hyps || [])].sort((a, b) => (a.status === "rejected") - (b.status === "rejected") || b.confidence - a.confidence);
    return `<ol class="causes">${sorted.map((h) => {
      const changed = (h.history || []).length > 1;
      return `<li class="cause ${h.status === "rejected" ? "rejected" : ""}" data-ev-host>
        <div class="cause-head"><strong>${esc(CAUSES[h.cause] || h.cause)}</strong>
          <span class="cause-word">${h.status === "rejected" ? "rejected by the critic" : word(h.confidence)}</span></div>
        <div class="cbar" tabindex="0" aria-label="Confidence ${pct(h.confidence)}${changed ? ", revised" : ""}">
          <div class="conf-track"><div class="conf-fill c-${word(h.confidence)}" style="width:${Math.max(3, h.confidence * 100)}%"></div>
            ${changed ? `<div class="conf-first" style="left:${h.history[0].confidence * 100}%" title="first estimate"></div>` : ""}</div>
          <span class="conf-num">${pct(h.confidence)}${changed ? " ↺" : ""}</span>
          <div class="conf-pop" role="tooltip"><p class="pop-title">How this confidence changed</p>${historyHTML(h)}</div>
        </div>
        <p class="cause-text">${linkify(h.explanation, ev)}</p>
        <div class="tags">${tags(h.supporting, ev)}${(h.contradicting || []).filter((i) => ev[i]).length ? `<span class="against">against:</span>${tags(h.contradicting, ev)}` : ""}</div>
      </li>`;
    }).join("")}</ol>`;
  }

  /* ---------- trace: round cards from the Meterless audit trail ---------- */

  function roundCardHTML(c, ev) {
    const title = c.round ? `Round ${c.round}` : "Final: advice and drafting";
    const calls = c.llm_calls.map((l) => `<li><strong>${esc(AGENTS[l.agent] || l.agent)}</strong>${l.purpose ? ` (${esc(l.purpose)})` : ""} · ${esc(l.model)} · ${fmt((l.duration_ms || 0) / 1000, 1)} s
      ${l.retries ? `<span class="warn-text">· ${l.retries} retr${l.retries > 1 ? "ies" : "y"}</span>` : ""}${l.fallback ? ` <span class="warn-text">· model switched</span>` : ""}${l.error ? ` <span class="error-text">· failed</span>` : ""}</li>`).join("");
    const tools = c.tools.map((t) => `<li><span class="mono">${esc(t.tool)}(${esc(t.args?.operator || "")})</span> → ${tags(t.evidence_ids, ev) || "<span class='muted'>no items</span>"}</li>`).join("");
    const revs = c.revisions.map((r) =>
      `<li><strong>${esc(CAUSES[r.belief] || r.belief)}</strong> ${r.from != null ? `${pct(r.from)} → ` : ""}${pct(r.to)} <span class="muted">(${esc(AGENTS[r.by] || r.by)})</span>
      ${r.from != null ? `<span class="sub-note">${esc(String(r.reason || "").replace(/^critic( rejected)?: /, ""))}</span>` : ""}</li>`).join("");
    const crit = c.critiques.map((k) => `<li><span class="verdict v-${esc(k.verdict)}">${esc(k.verdict.replace("_", " "))}</span>
      <strong>${esc(CAUSES[k.target] || k.target)}</strong><span class="sub-note">${linkify(k.reason, ev)}</span>
      ${k.requested_checks.length ? `<span class="sub-note">Asked for: ${k.requested_checks.map((q) => `<span class="mono">${esc(q.tool)}(${esc(q.operator || "")})</span>`).join(", ")}</span>` : ""}</li>`).join("");
    const guard = c.guard.map((g) => `<li><span class="mono">${esc(g.kind)}</span> ${esc(g.summary)}</li>`).join("");
    const coord = c.coordinator.filter((x) => x.type !== "round").map((x) => `<li>${esc(x.summary)}</li>`).join("");
    const block = (h, body) => (body ? `<h5>${h}</h5><ul class="trace-list">${body}</ul>` : "");
    return `<article class="round-card" data-ev-host><h4>${title}</h4>
      ${block("Agent calls", calls)}${block("Checks run (evidence written to Meterless)", tools)}
      ${block("Beliefs", revs)}${block("Critic", crit)}${block("Code guard", guard)}${block("Coordinator", coord)}</article>`;
  }

  function traceHTML(run, centre) {
    const ev = evMap(run);
    const cards = (run.trace?.rounds || []).map((c) => roundCardHTML(c, ev)).join("");
    const audit = run.trace?.audit || [];
    return `<div class="trace">
      <p class="footnote">From the Meterless audit trail (${audit.length} entries${run.memory_mode === "fallback" ? ", in-memory fallback" : ""}).
      The agents never message each other: each reads and writes this shared case file.</p>
      <div class="round-cards">${cards}</div>
      <h4 class="wm-title">World Model</h4>${worldHTML(run.world, centre)}</div>`;
  }

  /* ---------- World Model: the place or zone and what it is linked to ---------- */

  function worldHTML(world, centreType) {
    const ents = world?.entities || [], rels = world?.relationships || [];
    const byId = Object.fromEntries(ents.map((e) => [e.id, e]));
    const centre = ents.find((e) => e.type === centreType) || ents[0];
    if (!centre) return `<p class="muted">Nothing recorded.</p>`;
    const W = 340, H = 250, cx = W / 2, cy = H / 2;
    const first = rels.filter((r) => r.from === centre.id && byId[r.to]);
    const seen = new Map();
    first.forEach((r) => { if (!seen.has(r.to)) seen.set(r.to, []); seen.get(r.to).push(r); });
    const ring = [...seen.keys()];
    const pos = { [centre.id]: [cx, cy] };
    ring.forEach((id, i) => {
      const a = (i / Math.max(ring.length, 1)) * 2 * Math.PI - Math.PI / 2;
      pos[id] = [cx + 100 * Math.cos(a), cy + 82 * Math.sin(a)];
    });
    const second = rels.filter((r) => pos[r.from] && r.from !== centre.id && byId[r.to] && !pos[r.to]);
    const outer = [...new Set(second.map((r) => r.to))];
    outer.forEach((id, i) => {
      const a = (i / Math.max(outer.length, 1)) * 2 * Math.PI - Math.PI / 4;
      pos[id] = [cx + 155 * Math.cos(a), cy + 112 * Math.sin(a)];
    });
    const label = (e) => esc((e.name || e.id.split(":").slice(2).join(":")).slice(0, 22));
    const color = { place: "#15191F", zone: "#15191F", site: "#1D4ED8", candidate_site: "#7C3AED", operator: "#0D9488", area: "#64748B", warning: "#C2410C" };
    const edges = [...first, ...second.filter((r) => pos[r.to])].map((r) => {
      const [x1, y1] = pos[r.from], [x2, y2] = pos[r.to];
      const blocked = r.attrs?.line_of_sight === "blocked";
      return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="wm-edge ${blocked ? "blocked" : ""}"><title>${esc(r.type)}${r.attrs?.operator ? ` (${esc(r.attrs.operator)})` : ""}${r.attrs?.line_of_sight ? `: line of sight ${esc(r.attrs.line_of_sight)}${r.attrs.obstruction_m != null ? `, ${fmt(r.attrs.obstruction_m, 0)} m` : ""}` : ""}</title></line>`;
    }).join("");
    const nodes = Object.entries(pos).map(([id, [x, y]]) => {
      const e = byId[id];
      return `<g class="wm-node"><circle cx="${x}" cy="${y}" r="${id === centre.id ? 9 : 6}" fill="${color[e.type] || "#94A3B8"}"><title>${esc(e.type)}: ${esc(e.name || id)}</title></circle>
        <text x="${x}" y="${y + (id === centre.id ? 21 : 16)}" text-anchor="middle">${label(e)}</text></g>`;
    }).join("");
    const counts = {};
    ents.forEach((e) => { counts[e.type] = (counts[e.type] || 0) + 1; });
    return `<svg class="wm" viewBox="0 0 ${W} ${H}" role="img" aria-label="World Model entities linked to this ${esc(centre.type)}">${edges}${nodes}</svg>
      <p class="footnote">${Object.entries(counts).map(([t, n]) => `${n} ${esc(t.replace("_", " "))}${n > 1 ? "s" : ""}`).join(" · ")} · ${rels.length} relationships
      (red: line of sight blocked). Hover for details.</p>`;
  }

  /* ---------- Markdown (letters, summaries): a small safe subset ---------- */

  function markdown(md) {
    const inline = (s) => esc(s).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const out = [];
    let list = null;
    const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (const line of String(md || "").split("\n")) {
      const h = line.match(/^(#{1,4})\s+(.*)/), li = line.match(/^\s*[-*]\s+(.*)/), ol = line.match(/^\s*\d+\.\s+(.*)/);
      if (h) { close(); out.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`); }
      else if (li || ol) {
        const kind = li ? "ul" : "ol";
        if (list !== kind) { close(); out.push(`<${kind}>`); list = kind; }
        out.push(`<li>${inline((li || ol)[1])}</li>`);
      } else if (/^-{3,}$/.test(line.trim())) { close(); out.push("<hr>"); }
      else if (line.trim()) { close(); out.push(`<p>${inline(line)}</p>`); }
      else close();
    }
    close();
    return out.join("");
  }

  function download(name, text) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  const evMap = (run) => Object.fromEntries((run.evidence || []).map((e) => [e.evidence_id, e]));

  return { esc, fmt, CAUSES, AGENTS, word, pct, post, poll, progressHTML, linkify, tags, bindTags, causesHTML, traceHTML,
    worldHTML, markdown, download, evMap };
})();
