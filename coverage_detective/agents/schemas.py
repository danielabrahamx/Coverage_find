"""Shapes the agents exchange. LLM outputs are validated against these (strict JSON schema).

Agents never output numbers about the world: they cite evidence ids, and code attaches the
values (speeds, distances, people reached) from those evidence items.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Cause = Literal["distance_to_mast", "terrain_blocking", "single_operator", "capacity_strain", "weather",
                "active_incident", "insufficient_data"]
Operator = Literal["EE", "O2", "Three", "Vodafone"]
ToolName = Literal["speeds_near", "speed_trend", "sites_near", "line_of_sight", "terrain", "ofcom_area",
                   "live_conditions", "prior_diagnoses_nearby", "zone_summary", "candidate_sites"]
Verdict = Literal["approve", "needs_evidence", "downgrade", "reject"]
FixType = Literal["new_site", "add_operators", "capacity_upgrade", "gather_data"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------- diagnostician


class Hypothesis(Strict):
    id: str = Field(description="stable id, use the cause name, e.g. terrain_blocking")
    cause: Cause
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[str] = Field(description="evidence ids that support it")
    contradicting_evidence: list[str] = Field(description="evidence ids that count against it")
    explanation: str = Field(description="one or two sentences, citing evidence ids in [brackets]; no new numbers")


class HypothesisSet(Strict):
    hypotheses: list[Hypothesis] = Field(max_length=4)
    revision_reasons: list[RevisionReason] = Field(description="for each existing belief whose confidence you change, why")


class RevisionReason(Strict):
    id: str
    reason: str


HypothesisSet.model_rebuild()


# --------------------------------------------------------------- critic


class RequestedCheck(Strict):
    tool: ToolName
    operator: Operator | None = Field(description="only for line_of_sight; otherwise null")
    why: str


class Critique(Strict):
    hypothesis_id: str
    verdict: Verdict
    reason: str
    requested_checks: list[RequestedCheck]
    suggested_confidence: float | None = Field(ge=0, le=1, description="for downgrade: the confidence it should have")


class CritiqueSet(Strict):
    critiques: list[Critique]


# --------------------------------------------------------------- advisor


class RuledOut(Strict):
    cause: Cause
    reason: str
    evidence: list[str]


class NetworkRank(Strict):
    operator: Operator
    rank: int = Field(ge=1, le=4)
    confidence: Literal["high", "medium", "low"]
    why: str
    evidence: list[str]


class BestNetwork(Strict):
    summary: str
    ranking: list[NetworkRank]


class Action(Strict):
    text: str
    audience: Literal["resident", "operator", "council"]


class AdvisorOutput(Strict):
    headline: str = Field(description="one sentence, plain English, says 'likely'")
    explanation: str = Field(description="short paragraph citing evidence ids in [brackets]; no new facts or numbers")
    cited_evidence: list[str]
    ruled_out: list[RuledOut]
    limitations: str = Field(description="one line")
    best_network: BestNetwork
    actions: list[Action]


# --------------------------------------------------------------- letter writer


class Letter(Strict):
    recipient: Literal["operator", "council", "mp"]
    subject: str
    body_markdown: str = Field(description="the letter; cite sources and dates from the evidence; a specific ask")
    cited_evidence: list[str]


class PrioritySummary(Strict):  # no title field: 3.5 Super left it out under strict json_schema; code sets it
    body_markdown: str = Field(description="the summary for council officers; cite zone ids in [brackets]")
    cited_evidence: list[str]


# --------------------------------------------------------------- fix planner (zone)


class FixPlan(Strict):
    fix_type: FixType
    candidate: str | None = Field(description="evidence id of the chosen candidate site (e.g. cand_1), or null")
    why: str = Field(description="why this fix matches the cause, citing evidence ids; no numbers")
    assumptions: list[str]
    cited_evidence: list[str]


class ZoneAdvice(Strict):
    headline: str
    explanation: str
    cited_evidence: list[str]
    limitations: str


# --------------------------------------------------------------- assembled by code


class TraceEvent(BaseModel):
    at: str
    round: int | None = None
    agent: str
    type: str                     # tool_call | belief | revision | critique | guard | llm_call | round | event
    summary: str
    model: str | None = None
    tokens: dict | None = None
    duration_ms: int | None = None
    details: dict | None = None


class Diagnosis(BaseModel):
    run_id: str
    scope: Literal["point", "zone"]
    query: str | None
    location: dict
    headline: str
    explanation: str | None = None
    hypotheses: list[dict]        # beliefs with confidence history (from Meterless)
    ruled_out: list[dict] = []
    actions: list[dict] = []
    best_network: dict | None = None
    fix_plan: dict | None = None
    limitations: list[str] = []
    rounds: int
    status: Literal["complete", "partial", "failed"]
    notes: list[str] = []


class FixReview(Strict):
    verdict: Literal["approve", "revise"]
    reason: str
    issues: list[str]


# --------------------------------------------------------------- guard


class Rewrite(Strict):
    original: str
    rewritten: str = Field(description="the sentence again, with numbers only as written in the cited evidence, or none")


class RewriteSet(Strict):
    rewrites: list[Rewrite]
