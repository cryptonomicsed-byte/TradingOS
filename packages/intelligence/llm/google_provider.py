"""Google Gemini provider implementation."""

from __future__ import annotations

import json
from typing import Any

from .provider import LLMConfig, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolDefinition


class GoogleProvider(LLMProvider):
    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        try:
            import google.generativeai as genai
            genai.configure(api_key=config.api_key)
            self._genai = genai
        except ImportError:
            raise ImportError(
                "google-generativeai not installed. Run: pip install google-generativeai"
            )

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        import asyncio

        model = self._genai.GenerativeModel(
            model_name=self.config.model,
            system_instruction=system,
            tools=[_tool_to_gemini(t) for t in (tools or [])],
        )

        history = [_to_gemini_message(m) for m in messages[:-1]]
        last = messages[-1].content

        chat = model.start_chat(history=history)
        resp = await asyncio.to_thread(chat.send_message, last)
        return _from_gemini_response(resp, self.config.model)

    async def complete_tool_result(
        self,
        messages: list[LLMMessage],
        tool_results: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        import asyncio

        model = self._genai.GenerativeModel(
            model_name=self.config.model,
            system_instruction=system,
            tools=[_tool_to_gemini(t) for t in (tools or [])],
        )

        history = [_to_gemini_message(m) for m in messages]
        parts = [
            self._genai.protos.Part(
                function_response=self._genai.protos.FunctionResponse(
                    name=r.get("name", "tool"),
                    response={"result": r["content"]},
                )
            )
            for r in tool_results
        ]

        chat = model.start_chat(history=history)
        resp = await asyncio.to_thread(
            chat.send_message,
            self._genai.protos.Content(role="user", parts=parts),
        )
        return _from_gemini_response(resp, self.config.model)


def _to_gemini_message(msg: LLMMessage) -> dict[str, Any]:
    role = "model" if msg.role == "assistant" else "user"
    return {"role": role, "parts": [msg.content]}


def _tool_to_gemini(tool: ToolDefinition) -> Any:
    try:
        import google.generativeai as genai
        return genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=_schema_to_gemini(tool.parameters),
                )
            ]
        )
    except Exception:
        return {}


def _schema_to_gemini(schema: dict[str, Any]) -> Any:
    try:
        import google.generativeai as genai
        return genai.protos.Schema(
            type=genai.protos.Type.OBJECT,
            properties={
                k: genai.protos.Schema(type=genai.protos.Type.STRING, description=v.get("description", ""))
                for k, v in schema.get("properties", {}).items()
            },
            required=schema.get("required", []),
        )
    except Exception:
        return {}


def _from_gemini_response(resp: Any, model_name: str) -> LLMResponse:
    text = ""
    tool_calls: list[ToolCall] = []

    try:
        candidate = resp.candidates[0]
        for part in candidate.content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
            elif hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=fc.name,
                    name=fc.name,
                    arguments=dict(fc.args),
                ))
    except (AttributeError, IndexError):
        pass

    return LLMResponse(
        content=text,
        tool_calls=tool_calls,
        stop_reason="tool_use" if tool_calls else "end_turn",
        model=model_name,
    )
