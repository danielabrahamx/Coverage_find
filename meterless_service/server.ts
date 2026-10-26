// Meterless service for Coverage Detective: the agents' shared case file.
//
// A small HTTP/JSON service over the vendored Meterless reference engines
// (vendor/meterless, Apache 2.0, unmodified):
//   H-MEM        evidence items, beliefs (cause + confidence), critiques, notes (guard
//                interventions, tool calls, rounds) and past diagnoses, as memory records.
//                Belief revisions are trust-ledger "update" entries carrying who, the old
//                and new confidence and the reason, so the audit trail is the ledger.
//   World Model  places, zones, sites, operators, warnings, their relationships (with the
//                operator as relationship context) and events (diagnosis_completed, ...).
//
// Structured fields that H-MEM records do not model (numbers, ids, cell lists) live in a
// sidecar keyed by memory id (data/meterless/payloads.json). Everything persists under
// data/meterless/ (or MEMORY_DIR). Port 8100 (or MEMORY_PORT).
//
//   npx tsx server.ts

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HMEM } from "../vendor/meterless/hmem/src/index.ts";
import type { MemoryRecord } from "../vendor/meterless/hmem/src/index.ts";
import { WorldModel, externalId } from "../vendor/meterless/world-model/src/index.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = process.env.MEMORY_DIR ?? path.join(HERE, "..", "data", "meterless");
const PORT = Number(process.env.MEMORY_PORT ?? 8100);
const KINDS = ["run", "evidence", "belief", "critique", "note", "diagnosis"] as const;
type Kind = (typeof KINDS)[number];

fs.mkdirSync(DATA, { recursive: true });
const hmem = new HMEM({ persistDir: path.join(DATA, "hmem"), actor: "coverage-detective" });
const world = new WorldModel({ namespace: "coverage_detective", storage: "local", directory: DATA });

// ------------------------------------------------------------------ sidecar payloads

const PAYLOADS = path.join(DATA, "payloads.json");
const payloads: Record<string, Record<string, unknown>> = fs.existsSync(PAYLOADS)
  ? JSON.parse(fs.readFileSync(PAYLOADS, "utf-8"))
  : {};
let payloadTimer: NodeJS.Timeout | undefined;
function savePayloads(): void {
  clearTimeout(payloadTimer);
  payloadTimer = setTimeout(() => fs.writeFileSync(PAYLOADS, JSON.stringify(payloads)), 50);
}
process.on("exit", () => fs.writeFileSync(PAYLOADS, JSON.stringify(payloads)));

// ------------------------------------------------------------------ indexes

// memory ids by run and kind; (run, ref) -> memory id for idempotent writes
const byRun = new Map<string, string[]>();
const byRef = new Map<string, string>();
function index(rec: MemoryRecord): void {
  const p = payloads[rec.id] ?? {};
  const run = p.run_id as string | undefined;
  if (!run) return;
  if (!byRun.has(run)) byRun.set(run, []);
  byRun.get(run)!.push(rec.id);
  if (p.ref) byRef.set(`${run}|${p.kind}|${p.ref}`, rec.id);
}
for (const rec of hmem.store.all().sort((a, b) => Number(a.id.slice(4)) - Number(b.id.slice(4)))) index(rec);

const now = () => Date.now();
const iso = () => new Date().toISOString();

function addRecord(kind: Kind, runId: string | undefined, content: string, opts: {
  ref?: string; confidence?: number; source: string; layer?: "working" | "long_term"; payload: Record<string, unknown>;
  derivedFrom?: string[];
}): { record: MemoryRecord; created: boolean } {
  const key = runId && opts.ref ? `${runId}|${kind}|${opts.ref}` : undefined;
  if (key && byRef.has(key)) return { record: hmem.store.get(byRef.get(key)!)!, created: false };
  const record = hmem.add({
    content: content || `${kind} ${opts.ref ?? ""}`.trim(),
    type: "factual",
    layer: opts.layer ?? "working",
    tags: [kind, ...(runId ? [`run:${runId}`] : []), ...(opts.ref ? [`ref:${opts.ref}`] : [])],
    confidence: opts.confidence ?? 0.7,
    source: opts.source,
    provenance: { origin: "model_response", learnedAt: now(), label: opts.source, refs: opts.derivedFrom },
    goalRunId: runId,
    missionId: kind,
    derivedFrom: opts.derivedFrom,
  });
  // The record's own fields go last so a payload can never overwrite them.
  payloads[record.id] = { ...opts.payload, kind, run_id: runId, ref: opts.ref };
  savePayloads();
  index(record);
  return { record, created: true };
}

function runRecords(runId: string, kind?: Kind): { rec: MemoryRecord; p: Record<string, unknown> }[] {
  return (byRun.get(runId) ?? [])
    .map((id) => ({ rec: hmem.store.get(id)!, p: payloads[id] ?? {} }))
    .filter((x) => x.rec && (!kind || x.p.kind === kind));
}

function findRun(runId: string): { rec: MemoryRecord; p: Record<string, unknown> } | undefined {
  return runRecords(runId, "run")[0];
}

// Confidence change on a live record: one ledger entry with actor, old -> new and reason.
function revise(memId: string, confidence: number, reason: string, by: string, extra: Record<string, unknown> = {}): void {
  const rec = hmem.store.get(memId)!;
  const old = rec.confidence;
  rec.confidence = Math.min(1, Math.max(0, confidence));
  hmem.store.persist();
  hmem.ledger.log(memId, "update", by, {
    previousState: { confidence: old }, newState: { confidence: rec.confidence },
    details: { reason, ...extra },
  });
}

function view(rec: MemoryRecord, p: Record<string, unknown>) {
  return { memory_id: rec.id, kind: p.kind, ref: p.ref, content: rec.content, confidence: rec.confidence,
           source: rec.source, created_at: new Date(rec.timestamp).toISOString(), ...p };
}

// ------------------------------------------------------------------ H-MEM routes

function createRun(b: any) {
  const runId = b.run_id ?? `run_${new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14)}_${Math.random().toString(36).slice(2, 6)}`;
  const { record } = addRecord("run", runId, `Diagnosis run (${b.scope ?? "point"}) for ${b.label ?? b.query ?? runId}`, {
    ref: runId, source: b.by ?? "coordinator", confidence: 1,
    payload: { scope: b.scope ?? "point", query: b.query, label: b.label, location: b.location, status: "running",
               progress: [], created: iso(), by: b.by ?? "coordinator" },
  });
  return { run_id: runId, memory_id: record.id };
}

function getRun(runId: string) {
  const run = findRun(runId);
  if (!run) return null;
  const counts: Record<string, number> = {};
  for (const { p } of runRecords(runId)) counts[p.kind as string] = (counts[p.kind as string] ?? 0) + 1;
  return { ...view(run.rec, run.p), counts };
}

function updateRun(runId: string, b: any) {
  const run = findRun(runId);
  if (!run) return null;
  const p = payloads[run.rec.id];
  if (b.status && b.status !== p.status) {
    hmem.ledger.log(run.rec.id, "update", b.by ?? "coordinator", { details: { status_from: p.status, status_to: b.status } });
    p.status = b.status;
  }
  if (b.progress) (p.progress as unknown[]).push({ at: iso(), ...b.progress });
  if (b.result !== undefined) p.result = b.result;
  savePayloads();
  return getRun(runId);
}

function addEvidence(runId: string, b: any) {
  if (!findRun(runId)) return null;
  if (!b.evidence_id) throw new Error("evidence_id is required");
  const { record, created } = addRecord("evidence", runId, b.finding ?? "", {
    ref: b.evidence_id, source: b.source ?? b.by ?? "investigator",
    confidence: ({ strong: 0.9, moderate: 0.7, weak: 0.4 } as Record<string, number>)[b.strength] ?? 0.6,
    payload: { ...b, by: b.by ?? "investigator" },
  });
  return { evidence_id: b.evidence_id, memory_id: record.id, created };
}

function addBelief(runId: string, b: any) {
  if (!findRun(runId)) return null;
  const beliefId = b.belief_id ?? `${b.cause}`;
  const { record, created } = addRecord("belief", runId, `${b.cause}: ${b.explanation ?? ""}`, {
    ref: beliefId, source: b.by ?? "diagnostician", confidence: b.confidence ?? 0.5,
    derivedFrom: evidenceMemIds(runId, [...(b.supporting ?? []), ...(b.contradicting ?? [])]),
    payload: { belief_id: beliefId, cause: b.cause, explanation: b.explanation, supporting: b.supporting ?? [],
               contradicting: b.contradicting ?? [], round: b.round, by: b.by ?? "diagnostician", status: "active" },
  });
  if (!created) return { belief_id: beliefId, memory_id: record.id, created: false };
  return { belief_id: beliefId, memory_id: record.id, created: true };
}

function updateBelief(runId: string, beliefId: string, b: any) {
  const id = byRef.get(`${runId}|belief|${beliefId}`);
  if (!id) return null;
  const p = payloads[id];
  for (const k of ["explanation", "supporting", "contradicting", "status"]) if (b[k] !== undefined) p[k] = b[k];
  savePayloads();
  if (b.confidence !== undefined || b.reason) {
    revise(id, b.confidence ?? hmem.store.get(id)!.confidence, b.reason ?? "updated", b.by ?? "diagnostician",
           { round: b.round, belief_id: beliefId, status: b.status });
  }
  return beliefView(runId, id);
}

function beliefView(runId: string, memId: string) {
  const rec = hmem.store.get(memId)!;
  const history = hmem.ledger.history(memId)
    .filter((e) => e.action === "create" || (e.action === "update" && e.newState?.confidence !== undefined))
    .map((e) => ({
      at: new Date(e.timestamp).toISOString(), by: e.actor === "coverage-detective" ? payloads[memId].by : e.actor,
      confidence: e.newState?.confidence ?? null, previous: e.previousState?.confidence ?? null,
      reason: (e.details?.reason as string) ?? (e.action === "create" ? "proposed" : ""), round: e.details?.round ?? payloads[memId].round,
    }));
  return { ...view(rec, payloads[memId]), history };
}

function addCritique(runId: string, b: any) {
  if (!findRun(runId)) return null;
  const n = runRecords(runId, "critique").length + 1;
  const { record } = addRecord("critique", runId, `${b.verdict} on ${b.belief_id ?? b.target}: ${b.reason ?? ""}`, {
    ref: `c${n}`, source: b.by ?? "critic", confidence: 1,
    derivedFrom: b.belief_id ? [byRef.get(`${runId}|belief|${b.belief_id}`)].filter(Boolean) as string[] : undefined,
    payload: { ...b, critique_id: `c${n}`, by: b.by ?? "critic" },
  });
  return { critique_id: `c${n}`, memory_id: record.id };
}

function addNote(runId: string, b: any) {
  if (!findRun(runId)) return null;
  const n = runRecords(runId, "note").length + 1;
  const { record } = addRecord("note", runId, b.summary ?? b.type ?? "note", {
    ref: `n${n}`, source: b.by ?? "coordinator", confidence: 1, payload: { ...b, note_id: `n${n}` },
  });
  return { note_id: `n${n}`, memory_id: record.id };
}

function evidenceMemIds(runId: string, ids: string[]): string[] {
  return ids.map((e) => byRef.get(`${runId}|evidence|${e}`)).filter(Boolean) as string[];
}

// Ordered audit trail of a run: every ledger entry on the run's records.
function audit(runId: string) {
  const ids = new Set(byRun.get(runId) ?? []);
  return hmem.ledger.all()
    .map((e, seq) => ({ e, seq }))
    .filter(({ e }) => ids.has(e.memoryId))
    .map(({ e, seq }) => {
      const p = payloads[e.memoryId] ?? {};
      const rec = hmem.store.get(e.memoryId);
      return {
        seq, at: new Date(e.timestamp).toISOString(), action: e.action, actor: e.actor === "coverage-detective" ? (p.by ?? p.kind) : e.actor,
        kind: p.kind, ref: p.ref, memory_id: e.memoryId, round: e.details?.round ?? p.round,
        summary: e.action === "create" ? rec?.content : (e.details?.reason ?? e.details?.status_to ?? "updated"),
        old_confidence: e.previousState?.confidence ?? null,
        new_confidence: e.action === "create" ? (e.newState?.confidence ?? null) : (e.newState?.confidence ?? null),
        reason: e.details?.reason ?? null,
        payload: e.action === "create" ? p : undefined,
      };
    });
}

function addDiagnosis(b: any) {
  const { record } = addRecord("diagnosis", b.run_id, b.headline ?? "diagnosis", {
    ref: `diagnosis`, source: b.by ?? "coordinator", layer: "long_term", confidence: b.confidence ?? 0.7,
    payload: { ...b, recorded: iso() },
  });
  return { memory_id: record.id };
}

function haversineKm(a: number, b: number, c: number, d: number): number {
  const r = Math.PI / 180;
  const x = Math.sin(((c - a) * r) / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(((d - b) * r) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(x));
}

function diagnosesNear(lat: number, lon: number, km: number, exclude?: string) {
  const out = [];
  for (const rec of hmem.store.all()) {
    const p = payloads[rec.id];
    if (!p || p.kind !== "diagnosis" || p.run_id === exclude || p.lat === undefined) continue;
    const d = haversineKm(lat, lon, p.lat as number, p.lon as number);
    if (d <= km) out.push({ ...view(rec, p), distance_km: Math.round(d * 100) / 100 });
  }
  return out.sort((a, b) => a.distance_km - b.distance_km);
}

// ------------------------------------------------------------------ World Model routes

const prov = (b: any) => ({ kind: "agent", by: b.by ?? "coordinator", at: iso(), runId: b.run_id });
const entityId = (type: string, key: string) => externalId(type, "cd", key);

async function upsertEntity(b: any) {
  const e = await world.upsertEntity({ type: b.type, externalKey: { system: "cd", id: String(b.key) }, name: b.name,
                                       attrs: b.attrs ?? {}, source: prov(b) });
  return e;
}

async function relate(b: any) {
  let context: string | undefined;
  if (b.context) {  // e.g. {type: "operator", key: "EE"}: edges per operator do not close each other
    const c = await world.upsertContext({ type: b.context.type, externalKey: { system: "cd", id: String(b.context.key) },
                                          attrs: { name: b.context.key }, source: prov(b) });
    context = c.id;
  }
  return world.relate({ from: b.from, type: b.type, to: b.to, context, attrs: b.attrs, source: prov(b) });
}

async function addEvent(b: any) {
  const key = `${b.kind}:${b.run_id ?? ""}:${b.subject ?? ""}:${Date.now()}`;
  const ev = await world.upsertEntity({ type: "event", externalKey: { system: "cd", id: key }, name: b.kind,
                                        attrs: { kind: b.kind, ...(b.attrs ?? {}), run_id: b.run_id, at: iso() }, source: prov(b) });
  if (b.subject) await world.relate({ from: ev.id, type: "concerns", to: b.subject, source: prov(b) });
  return ev;
}

function entityView(id: string) {
  const graph = world.view("graph");
  const e = graph.entity(id);
  if (!e) return null;
  const relationships = allRelationships().filter((r) => (r.from === e.id || r.to === e.id) && !r.validTo);
  return { entity: e, relationships, facts: world.view("facts").about(id) };
}

function allRelationships(): any[] {
  // Fold of relate events (closed edges keep validTo).
  const out = new Map<string, any>();
  for (const ev of world.events()) if (ev.kind === "relate") out.set((ev.payload as any).id, ev.payload);
  return [...out.values()];
}

function worldForRun(runId: string) {
  const entities = new Map<string, any>();
  for (const ev of world.events()) {
    const p = ev.payload as any;
    if (ev.kind === "upsertEntity" && p.source?.runId === runId) entities.set(p.id, world.view("graph").entity(p.id) ?? p);
  }
  // Edges written in this run, plus existing edges of the run's entities (relationships are
  // content-addressed, so an identical edge from an earlier run is not written again).
  const rels = allRelationships().filter((r) => r.source?.runId === runId || ((entities.has(r.from) || entities.has(r.to)) && !r.validTo));
  for (const r of rels) for (const id of [r.from, r.to]) if (!entities.has(id)) {
    const e = world.view("graph").entity(id);
    if (e) entities.set(id, e);
  }
  return { entities: [...entities.values()], relationships: rels };
}

// ------------------------------------------------------------------ HTTP

type Handler = (m: RegExpMatchArray, body: any, q: URLSearchParams) => unknown | Promise<unknown>;
const routes: [string, RegExp, Handler][] = [
  ["GET", /^\/health$/, () => ({ status: "ok", engines: { hmem: "vendored reference", world_model: "vendored reference" },
    records: hmem.store.all().length, ledger_entries: hmem.ledger.all().length, world_events: world.events().length, data_dir: DATA })],
  ["POST", /^\/runs$/, (_m, b) => createRun(b)],
  ["GET", /^\/runs\/([\w-]+)$/, (m) => getRun(m[1])],
  ["PATCH", /^\/runs\/([\w-]+)$/, (m, b) => updateRun(m[1], b)],
  ["POST", /^\/runs\/([\w-]+)\/evidence$/, (m, b) => addEvidence(m[1], b)],
  ["GET", /^\/runs\/([\w-]+)\/evidence$/, (m) => findRun(m[1]) ? runRecords(m[1], "evidence").map((x) => view(x.rec, x.p)) : null],
  ["POST", /^\/runs\/([\w-]+)\/beliefs$/, (m, b) => addBelief(m[1], b)],
  ["GET", /^\/runs\/([\w-]+)\/beliefs$/, (m) => findRun(m[1]) ? runRecords(m[1], "belief").map((x) => beliefView(m[1], x.rec.id)) : null],
  ["PATCH", /^\/runs\/([\w-]+)\/beliefs\/([\w-]+)$/, (m, b) => updateBelief(m[1], m[2], b)],
  ["POST", /^\/runs\/([\w-]+)\/critiques$/, (m, b) => addCritique(m[1], b)],
  ["GET", /^\/runs\/([\w-]+)\/critiques$/, (m) => findRun(m[1]) ? runRecords(m[1], "critique").map((x) => view(x.rec, x.p)) : null],
  ["POST", /^\/runs\/([\w-]+)\/notes$/, (m, b) => addNote(m[1], b)],
  ["GET", /^\/runs\/([\w-]+)\/notes$/, (m) => findRun(m[1]) ? runRecords(m[1], "note").map((x) => view(x.rec, x.p)) : null],
  ["GET", /^\/runs\/([\w-]+)\/audit$/, (m) => findRun(m[1]) ? audit(m[1]) : null],
  ["GET", /^\/runs\/([\w-]+)\/world$/, (m) => worldForRun(m[1])],
  ["POST", /^\/diagnoses$/, (_m, b) => addDiagnosis(b)],
  ["GET", /^\/diagnoses\/near$/, (_m, _b, q) => diagnosesNear(Number(q.get("lat")), Number(q.get("lon")), Number(q.get("km") ?? 10), q.get("exclude_run") ?? undefined)],
  ["POST", /^\/world\/entities$/, (_m, b) => upsertEntity(b)],
  ["POST", /^\/world\/relationships$/, (_m, b) => relate(b)],
  ["POST", /^\/world\/events$/, (_m, b) => addEvent(b)],
  ["GET", /^\/world\/entities\/(.+)$/, (m) => entityView(decodeURIComponent(m[1]))],
  ["GET", /^\/world\/id$/, (_m, _b, q) => ({ id: entityId(q.get("type") ?? "", q.get("key") ?? "") })],
];

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  let raw = "";
  for await (const chunk of req) raw += chunk;
  const send = (status: number, body: unknown) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  };
  for (const [method, re, handler] of routes) {
    const m = url.pathname.match(re);
    if (!m || method !== req.method) continue;
    try {
      const body = raw ? JSON.parse(raw) : {};
      const out = await handler(m, body, url.searchParams);
      return out === null || out === undefined ? send(404, { error: "not found" }) : send(200, out);
    } catch (e) {
      return send(400, { error: (e as Error).message });
    }
  }
  send(404, { error: `no route ${req.method} ${url.pathname}` });
});

server.listen(PORT, "127.0.0.1", () => console.log(`Meterless service on http://127.0.0.1:${PORT} (data: ${DATA})`));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { fs.writeFileSync(PAYLOADS, JSON.stringify(payloads)); process.exit(0); });
