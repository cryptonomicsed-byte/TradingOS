"""Anthropic (Claude) provider implementation."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .provider import LLMConfig, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolDefinition


class AnthropicProvider(LLMProvider):
    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [_to_anthropic_message(m) for m in messages],
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [_tool_to_anthropic(t) for t in tools]

        resp = await self._client.messages.create(**kwargs)
        return _from_anthropic_response(resp)

    async def complete_tool_result(
        self,
        messages: list[LLMMessage],
        tool_results: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        anthropic_messages = [_to_anthropic_message(m) for m in messages]
        anthropic_messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r["tool_call_id"], "content": r["content"]}
                for r in tool_results
            ],
        })

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": anthropic_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [_tool_to_anthropic(t) for t in tools]

        resp = await self._client.messages.create(**kwargs)
        return _from_anthropic_response(resp)


# ─── Format translators ──────────────────────────────────────

def _to_anthropic_message(msg: LLMMessage) -> dict[str, Any]:
    if msg.tool_calls:
        content: list[Any] = []
        if msg.content:
            content.append({"type": "text", "text": msg.content})
        for tc in msg.tool_calls:
            content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return {"role": "assistant", "content": content}
    return {"role": msg.role, "content": msg.content}


def _tool_to_anthropic(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }


def _from_anthropic_response(resp: anthropic.types.Message) -> LLMResponse:
    text = ""
    tool_calls: list[ToolCall] = []

    for block in resp.content:
        if block.type == "text":
            text = block.text
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

    stop = "tool_use" if tool_calls else "end_turn"
    usage = resp.usage

    return LLMResponse(
        content=text,
        tool_calls=tool_calls,
        stop_reason=stop,
        model=resp.model,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
    )
