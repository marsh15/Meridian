"""OpenAI-compatible chat client for the intelligence layer.

One code path serves every deployment shape: Ollama on the laptop
(http://localhost:11434/v1, no key), or any hosted OpenAI-shaped API via
LLM_BASE_URL + LLM_API_KEY. json_object response format is requested but
retried without it — small local models and older gateways vary. Reasoning
models (qwen3, deepseek-r1) wrap output in <think> blocks; those are
stripped before parsing.
"""

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("meridian.intel.llm")


class LLMError(Exception):
    pass


class LLMNotConfigured(LLMError):
    pass


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(content: str) -> dict[str, Any]:
    stripped = _THINK.sub("", content).strip()
    # tolerate prose fences around the object
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    match = _JSON_OBJECT.search(stripped)
    if match is None:
        raise LLMError(f"model returned no JSON object: {content[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except ValueError as err:
        raise LLMError(f"model returned invalid JSON: {err}") from err
    if not isinstance(data, dict):
        raise LLMError("model JSON is not an object")
    return data


async def chat_json(messages: list[dict[str, str]], *, max_tokens: int = 1400) -> dict:
    """messages → parsed JSON object. Raises LLMNotConfigured / LLMError."""
    if not settings.llm_base_url:
        raise LLMNotConfigured("LLM_BASE_URL is not set")

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    messages = [dict(m) for m in messages]
    if "qwen3" in settings.llm_model and messages:
        # qwen3's thinking mode doubles latency on exactly the structured
        # tasks that don't benefit from it; other providers see plain text
        messages[0] = {**messages[0], "content": messages[0]["content"] + " /no_think"}

    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
        for attempt in (1, 2):
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as err:
                raise LLMError(f"LLM endpoint unreachable: {err}") from err
            if resp.status_code == 400 and attempt == 1 and "response_format" in body:
                # gateway/model rejects json_object — try plain completion
                body = {k: v for k, v in body.items() if k != "response_format"}
                continue
            if resp.status_code != 200:
                raise LLMError(f"LLM returned {resp.status_code}: {resp.text[:200]}")
            try:
                message = resp.json()["choices"][0]["message"]
                content = message.get("content") or ""
                # reasoning models (qwen3-style) can starve `content` while
                # filling a separate reasoning field; it's still our best
                # candidate on the fallback attempt
                if not content.strip() and attempt == 2:
                    content = message.get("reasoning") or ""
            except (KeyError, IndexError, ValueError) as err:
                raise LLMError(f"malformed LLM response: {err}") from err
            if not content.strip() and attempt == 1:
                body = {k: v for k, v in body.items() if k != "response_format"}
                continue
            return _extract_json(content)
    raise LLMError("LLM rejected both request shapes")
