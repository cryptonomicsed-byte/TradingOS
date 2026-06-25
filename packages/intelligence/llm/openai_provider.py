"""
OpenAI-compatible provider — covers OpenAI, Groq, Ollama, Together,
Fireworks, vLLM, LM Studio, and any endpoint following the OpenAI API spec.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from openai import AsyncOpenAI

from .provider import LLMConfig, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolDefinition

# Provider-specific base URLs
_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "ollama": "http://localhost:11434/v1",
}


class OpenAICompatProvider(LLMProvider):
    """
    Works for: openai, groq, ollama, together, fireworks, openai-compat.
    Pass base_url in config to point at any OpenAI-compatible endpoint.
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        base_url = config.base_url or _BASE_URLS.get(config.provider)
        api_key = config.api_key or ("ollama" if config.provider == "ollama" else None)

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=config.timeout,
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        oai_messages: list[dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_to_oai_message(m) for m in messages)

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": oai_messages,
        }
        if tools:
            kwargs["tools"] = [_tool_to_oai(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        resp = await self._client.chat.completions.create(**kwargs)
        return _from_oai_response(resp)

    async def complete_tool_result(
        self,
        messages: list[LLMMessage],
        tool_results: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        oai_messages: list[dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_to_oai_message(m) for m in messages)

        # Append tool results
        for r in tool_results:
            oai_messages.append({
                "role": "tool",
                "tool_call_id": r["tool_call_id"],
                "content": r["content"],
            })

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": oai_messages,
        }
        if tools:
            kwargs["tools"] = [_tool_to_oai(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        resp = await self._client.chat.completions.create(**kwargs)
        return _from_oai_response(resp)


# ─── Format translators ──────────────────────────────────────

def _to_oai_message(msg: LLMMessage) -> dict[str, Any]:
    if msg.tool_calls:
        return {
            "role": "assistant",
            "content": msg.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in msg.tool_calls
            ],
        }
    return {"role": msg.role, "content": msg.content}


def _tool_to_oai(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _from_oai_response(resp: Any) -> LLMResponse:
    choice = resp.choices[0]
    msg = choice.message

    text = msg.content or ""
    tool_calls: list[ToolCall] = []

    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = resp.usage

    return LLMResponse(
        content=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        model=resp.model,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )
