"""NVIDIA Nemotron through its OpenAI-compatible API (build.nvidia.com).

    LLM_BASE_URL=https://integrate.api.nvidia.com/v1
    LLM_API_KEY=nvapi-...                  never logged or printed
    LLM_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b      investigator, advisor, letters, fix planner
    LLM_MODEL_REASONING=nvidia/nemotron-3-ultra-550b-a55b diagnostician, critic (thinking on)

Structured output, chosen by probes on 26 Oct 2026 (repeated tries per combination):
  - tool calling (investigator): Super 3/3, ~1-2 s.
  - strict JSON schema (`response_format: json_schema`, strict) on Super, thinking off: reliable,
    4-16 s on the full evidence list. Used by the advisor, letter writer and fix planner.
  - reasoning agents (diagnostician, critic): Ultra with thinking on and the JSON schema given in
    the prompt (no constrained decoding), validated by pydantic: 4/4, 17-26 s. Ultra under strict
    json_schema degenerated on long prompts (2 of 3 ran out of tokens padding output), and Super
    with thinking was slow and flaky, so neither is used. NVIDIA's `guided_json` is rejected.
Replies are validated with pydantic; one corrective retry on invalid JSON. If a model still fails
(the endpoint has bursts of HTTP 500), the other model answers once: reasoning -> fast with strict
json_schema, fast -> reasoning model with thinking off and the schema in the prompt; the result's
`fallback` says so. Tool calling falls back to the reasoning model too (Ultra, thinking off: 3/3,
3-7 s); if both fail, the coordinator uses a fixed tool plan in code. Reasoning text (`reasoning_content`) is never stored or returned. 45 s timeout,
one retry on timeouts, 5xx retried after 2 s and 6 s before switching model, a shared throttle
under 40 requests per minute, backoff on 429. Every retry and model switch is in `retries`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ValidationError

from coverage_detective.config import env

log = logging.getLogger("coverage_detective.llm")
TIMEOUT_S = 45.0
MAX_PER_MINUTE = 38
SERVER_ERROR_WAITS_S = (2.0, 6.0)  # retry a 5xx after 2 s, then 6 s, then switch model


class LLMError(RuntimeError):
    def __init__(self, message: str, retries: list[dict] | None = None):
        super().__init__(message)
        self.retries = list(retries or [])


@dataclass
class LLMResult:
    model: str
    content: str | None = None
    parsed: BaseModel | None = None
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    duration_ms: int = 0
    attempts: int = 1
    fallback: str | None = None  # set when one model failed and the other answered
    retries: list[dict] = field(default_factory=list)  # every retry (model, attempt, error, wait_s)


class _Throttle:
    """At most MAX_PER_MINUTE request starts in any 60 s window (shared by all threads)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.starts: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.starts and now - self.starts[0] > 60:
                    self.starts.popleft()
                if len(self.starts) < self.per_minute:
                    self.starts.append(now)
                    return
                sleep = 60 - (now - self.starts[0]) + 0.05
            time.sleep(sleep)


_throttle = _Throttle(MAX_PER_MINUTE)


def strict_schema(model: type[BaseModel]) -> dict:
    """A pydantic model's JSON schema, inlined and tightened for strict structured output."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


class LLM:
    def __init__(self):
        self.base_url = (env("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1") or "").rstrip("/")
        self.model = env("LLM_MODEL")
        self.reasoning_model = env("LLM_MODEL_REASONING") or self.model
        self._key = env("LLM_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self._key and self.model)

    def _post(self, body: dict, retries: list[dict]) -> tuple[dict, int]:
        """POST with retries; every retry is appended to `retries` (for the trace)."""
        if not self.configured:
            raise LLMError("LLM_API_KEY / LLM_MODEL are not set in .env")
        model = body["model"]
        attempts = 0
        rate_backoff = 2.0
        server_waits = list(SERVER_ERROR_WAITS_S)
        while True:
            attempts += 1
            _throttle.wait()
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=TIMEOUT_S,
                               headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"})
            except httpx.HTTPError as e:
                what = f"no answer within {TIMEOUT_S:.0f} s" if isinstance(e, httpx.TimeoutException) else type(e).__name__
                if attempts >= 2:  # one retry on timeouts / connection errors
                    raise LLMError(f"{model}: {what} (twice)", retries) from None
                retries.append({"model": model, "attempt": attempts, "error": what, "wait_s": 0})
                continue
            if r.status_code == 429:  # rate limited: back off (not counted as the retry)
                wait = min(float(r.headers.get("retry-after") or rate_backoff), 30)
                retries.append({"model": model, "attempt": attempts, "error": "HTTP 429", "wait_s": wait})
                log.warning("LLM 429 from %s, waiting %.0f s", model, wait)
                time.sleep(wait)
                rate_backoff = min(rate_backoff * 2, 30)
                if attempts > 6:
                    raise LLMError(f"{model}: rate limited", retries)
                continue
            if r.status_code >= 500 and server_waits:  # bursts of 500s: wait 2 s, then 6 s
                wait = server_waits.pop(0)
                retries.append({"model": model, "attempt": attempts, "error": f"HTTP {r.status_code}", "wait_s": wait})
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise LLMError(f"{model}: HTTP {r.status_code} {r.text[:200]}", retries)
            return r.json(), attempts

    def chat(self, messages: list[dict], *, reasoning: bool = False, schema: type[BaseModel] | None = None,
             tools: list[dict] | None = None, temperature: float = 0.2, max_tokens: int = 4000,
             _corrective: bool = False) -> LLMResult:
        """One completion. reasoning=True uses the reasoning model with thinking on."""
        try:
            return self._chat(messages, reasoning, schema, tools, temperature, max_tokens, _corrective)
        except LLMError as e:
            if self.reasoning_model == self.model:
                raise
            first_retries = e.retries + [{"model": self.reasoning_model if reasoning else self.model,
                                          "error": str(e)[:160], "switched_to": self.model if reasoning else self.reasoning_model}]
            # The other model, once: reasoning -> fast (strict json_schema); fast -> reasoning model,
            # thinking off, JSON schema in the prompt.
            other = "fast" if reasoning else "reasoning"
            log.warning("%s model failed (%s); falling back to the %s model", "reasoning" if reasoning else "fast",
                        str(e)[:120], other)
            try:
                result = self._chat(messages, not reasoning, schema, tools, temperature, max_tokens, False,
                                    thinking=False, prompt_schema=not reasoning)
            except LLMError as e2:
                raise LLMError(f"both models failed: {str(e)[:120]} / {str(e2)[:120]}", first_retries + e2.retries) from None
            result.retries = first_retries + result.retries
            result.fallback = f"{'reasoning' if reasoning else 'fast'} model failed ({str(e)[:140]}); {other} model answered"
            return result

    def _chat(self, messages, reasoning, schema, tools, temperature, max_tokens, _corrective,
              thinking: bool | None = None, prompt_schema: bool | None = None) -> LLMResult:
        model = self.reasoning_model if reasoning else self.model
        thinking = reasoning if thinking is None else thinking
        prompt_schema = reasoning if prompt_schema is None else prompt_schema
        body: dict = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                      "chat_template_kwargs": {"enable_thinking": thinking}}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if schema and prompt_schema:  # the schema goes in the prompt; constrained decoding degenerates on Ultra
            instruction = ("\n\nReply with ONLY one JSON object matching this JSON schema (no prose, no code fences):\n"
                           + json.dumps(strict_schema(schema)))
            body["messages"] = [{**messages[0], "content": messages[0]["content"] + instruction}, *messages[1:]]
        elif schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": schema.__name__, "schema": strict_schema(schema), "strict": True}}
        t0 = time.monotonic()
        retries: list[dict] = []
        data, attempts = self._post(body, retries)
        msg = data["choices"][0]["message"]
        result = LLMResult(model=model, content=msg.get("content"), usage=data.get("usage") or {},
                           tool_calls=[{"id": c.get("id"), "name": c["function"]["name"],
                                        "arguments": json.loads(c["function"].get("arguments") or "{}")}
                                       for c in msg.get("tool_calls") or []],
                           attempts=attempts, retries=retries)
        # msg.get("reasoning_content") is deliberately dropped: raw reasoning is never stored.
        if schema:
            try:
                result.parsed = schema.model_validate_json(_strip_fences(result.content or ""))
            except ValidationError as e:
                if _corrective:
                    raise LLMError(f"{model}: invalid {schema.__name__} after a corrective retry: {str(e)[:300]}") from None
                fix = messages + [{"role": "assistant", "content": result.content or ""},
                                  {"role": "user", "content": f"That did not match the schema ({str(e)[:400]}). "
                                                              "Reply again with only the corrected JSON."}]
                retry = self._chat(fix, reasoning, schema, None, temperature, max_tokens, True, thinking, prompt_schema)
                retry.attempts += attempts
                retry.usage = _add_usage(result.usage, retry.usage)
                return retry
        result.duration_ms = round((time.monotonic() - t0) * 1000)
        return result


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return text


def _add_usage(a: dict, b: dict) -> dict:
    return {k: (a.get(k) or 0) + (b.get(k) or 0) for k in set(a) | set(b) if isinstance(a.get(k, 0), int)}


llm = LLM()
