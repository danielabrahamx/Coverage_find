// End-to-end test of the Meterless service: starts it on a spare port with a temp data dir.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const PORT = 18100 + Math.floor(Math.random() * 500);
const BASE = `http://127.0.0.1:${PORT}`;
const DIR = fs.mkdtempSync(path.join(os.tmpdir(), "meterless-test-"));
let proc: ChildProcess;

async function call(method: string, p: string, body?: unknown) {
  const r = await fetch(BASE + p, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json() as any };
}

before(async () => {
  proc = spawn(process.execPath, ["--import", "tsx", "server.ts"], { env: { ...process.env, MEMORY_PORT: String(PORT), MEMORY_DIR: DIR }, stdio: "ignore" });
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${BASE}/health`)).ok) return; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("service did not start");
});
after(() => { proc.kill(); fs.rmSync(DIR, { recursive: true, force: true }); });

test("run, evidence, belief revision and ordered audit trail", async () => {
  const { body: run } = await call("POST", "/runs", { scope: "point", query: "Great Langdale", location: { lat: 54.445, lon: -3.105 } });
  const id = run.run_id;
  const ev = await call("POST", `/runs/${id}/evidence`, { evidence_id: "los_vodafone", finding: "Terrain rises 288 m above the line", strength: "strong" });
  assert.equal(ev.body.created, true);
  assert.equal((await call("POST", `/runs/${id}/evidence`, { evidence_id: "los_vodafone", finding: "dup" })).body.created, false);
  await call("POST", `/runs/${id}/beliefs`, { cause: "terrain_blocking", confidence: 0.8, supporting: ["los_vodafone"], round: 1 });
  const upd = await call("PATCH", `/runs/${id}/beliefs/terrain_blocking`, { confidence: 0.6, reason: "antenna height assumed", by: "critic", round: 1 });
  assert.deepEqual(upd.body.history.map((h: any) => h.confidence), [0.8, 0.6]);
  assert.equal(upd.body.history[1].previous, 0.8);
  assert.equal(upd.body.history[1].reason, "antenna height assumed");
  assert.equal(upd.body.history[1].by, "critic");
  await call("POST", `/runs/${id}/critiques`, { belief_id: "terrain_blocking", verdict: "downgrade", reason: "assumed height" });
  const trail = (await call("GET", `/runs/${id}/audit`)).body;
  assert.deepEqual(trail.map((t: any) => t.kind), ["run", "evidence", "belief", "belief", "critique"]);
  assert.ok(trail.every((t: any, i: number) => i === 0 || t.seq > trail[i - 1].seq));
  assert.equal(trail[3].old_confidence, 0.8);
  assert.equal(trail[3].new_confidence, 0.6);
});

test("prior diagnoses near a point", async () => {
  const { body: run } = await call("POST", "/runs", { scope: "point", query: "x" });
  await call("POST", "/diagnoses", { run_id: run.run_id, lat: 54.445, lon: -3.105, headline: "Terrain blocks the nearest sites" });
  const near = (await call("GET", "/diagnoses/near?lat=54.45&lon=-3.10&km=10")).body;
  assert.equal(near.length, 1);
  assert.ok(near[0].distance_km < 1);
  assert.equal((await call("GET", `/diagnoses/near?lat=51.5&lon=-0.12&km=10`)).body.length, 0);
});

test("world entities, operator-scoped relationships and events", async () => {
  const place = (await call("POST", "/world/entities", { type: "place", key: "54.44500,-3.10500", name: "Great Langdale" })).body;
  const ee = (await call("POST", "/world/entities", { type: "site", key: "S065491", attrs: { operators: ["EE", "Three"] } })).body;
  const vf = (await call("POST", "/world/entities", { type: "site", key: "S075142", attrs: { operators: ["Vodafone"] } })).body;
  await call("POST", "/world/relationships", { from: place.id, type: "nearest_site", to: ee.id, context: { type: "operator", key: "EE" }, attrs: { line_of_sight: "blocked" } });
  await call("POST", "/world/relationships", { from: place.id, type: "nearest_site", to: vf.id, context: { type: "operator", key: "Vodafone" }, attrs: { line_of_sight: "blocked" } });
  await call("POST", "/world/events", { kind: "diagnosis_completed", subject: place.id, attrs: { headline: "h" } });
  const view = (await call("GET", `/world/entities/${encodeURIComponent(place.id)}`)).body;
  assert.equal(view.relationships.filter((r: any) => r.type === "nearest_site").length, 2); // per-operator edges stay open
  assert.equal(view.relationships.filter((r: any) => r.type === "concerns").length, 1);
});
