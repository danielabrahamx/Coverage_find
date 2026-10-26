"""Nemotron client with a mocked endpoint: schemas, corrective retry, fallback, no secrets or reasoning kept."""

import json
import logging

import httpx
import pytest

from coverage_detective.agents import llm as L
from coverage_detective.agents import schemas as S

GOOD = {"hypotheses": [{"id": "terrain_blocking", "cause": "terrain_blocking", "confidence": 0.8,
                        "supporting_evidence": ["los_ee"], "contradicting_evidence": [], "explanation": "x [los_ee]"}],
        "revision_reasons": []}


def reply(content=None, tool_calls=None, status=200, reasoning="secret chain of thought"):
    msg = {"content": content, "reasoning_content": reasoning, **({"tool_calls": tool_calls} if tool_calls else {})}
    return httpx.Response(status, json={"choices": [{"message": msg}], "usage": {"total_tokens": 10}} if status == 200
                          else {"message": "Failed"}, request=httpx.Request("POST", "https://x/chat/completions"))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(L, "_throttle", L._Throttle(1000))
    c = L.LLM()
    c.base_url, c.model, c.reasoning_model, c._key = "https://x", "fast-model", "reason-model", "nvapi-SECRET"
    return c


def script(monkeypatch, responses):
    sent = []

    def post(url, json=None, **kw):
        sent.append(json)
        return responses.pop(0)

    monkeypatch.setattr(L.httpx, "post", post)
    return sent


def test_strict_schema_is_closed_and_inlined():
    sch = L.strict_schema(S.HypothesisSet)
    assert "$defs" not in json.dumps(sch) and "$ref" not in json.dumps(sch)
    item = sch["properties"]["hypotheses"]["items"]
    assert item["additionalProperties"] is False and set(item["required"]) == set(item["properties"])
    assert "terrain_blocking" in json.dumps(item["properties"]["cause"])


def test_reasoning_uses_prompt_schema_and_drops_reasoning_text(client, monkeypatch):
    sent = script(monkeypatch, [reply(json.dumps(GOOD))])
    r = client.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], reasoning=True, schema=S.HypothesisSet)
    body = sent[0]
    assert body["model"] == "reason-model" and body["chat_template_kwargs"] == {"enable_thinking": True}
    assert "response_format" not in body and "JSON schema" in body["messages"][0]["content"]
    assert r.parsed.hypotheses[0].cause == "terrain_blocking"
    assert "secret chain" not in json.dumps(r.__dict__, default=str)


def test_fast_uses_strict_json_schema(client, monkeypatch):
    sent = script(monkeypatch, [reply(json.dumps(GOOD))])
    client.chat([{"role": "system", "content": "s"}], schema=S.HypothesisSet)
    assert sent[0]["response_format"]["json_schema"]["strict"] is True
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_corrective_retry_on_invalid_json(client, monkeypatch):
    sent = script(monkeypatch, [reply("{not json"), reply(json.dumps(GOOD))])
    r = client.chat([{"role": "system", "content": "s"}], schema=S.HypothesisSet)
    assert r.parsed is not None and len(sent) == 2 and "did not match the schema" in sent[1]["messages"][-1]["content"]


def test_falls_back_to_the_other_model_on_server_errors(client, monkeypatch):
    sent = script(monkeypatch, [reply(status=500), reply(status=500), reply(json.dumps(GOOD))])
    r = client.chat([{"role": "system", "content": "s"}], reasoning=True, schema=S.HypothesisSet)
    assert [b["model"] for b in sent] == ["reason-model", "reason-model", "fast-model"]
    assert r.model == "fast-model" and "reasoning model failed" in r.fallback


def test_tool_calls_parsed(client, monkeypatch):
    calls = [{"id": "1", "function": {"name": "line_of_sight", "arguments": '{"operator": "EE"}'}}]
    script(monkeypatch, [reply(None, tool_calls=calls)])
    r = client.chat([{"role": "system", "content": "s"}], tools=[{"type": "function"}])
    assert r.tool_calls == [{"id": "1", "name": "line_of_sight", "arguments": {"operator": "EE"}}]


def test_key_never_logged(client, monkeypatch, caplog):
    script(monkeypatch, [reply(status=500), reply(status=500), reply(status=500), reply(status=500)])
    with caplog.at_level(logging.DEBUG), pytest.raises(L.LLMError) as e:
        client.chat([{"role": "system", "content": "s"}], schema=S.HypothesisSet)
    assert "SECRET" not in caplog.text and "SECRET" not in str(e.value)
