"""
Base agent infrastructure for TradingOS.
Provider-agnostic: each agent uses whatever LLM it has configured.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from ..llm import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolDefinition,
    create_provider,
)

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# AGENT IDENTITY & PROFILE
# ═══════════════════════════════════════════════════════════════

class AgentProfile(BaseModel):
    """Persistent agent identity. Survives restarts."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: str
    name: str
    description: str
    temperature: float = 0.3
    max_tokens: int = 4096

    # Reputation — updated by outcome feedback
    reputation: float = 0.8
    total_predictions: int = 0
    correct_predictions: int = 0

    # Memory namespace — agents don't share memory by default
    memory_namespace: str = ""

    # Skill tags for agent discovery
    skills: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Per-agent LLM override — empty dict means "inherit from environment"
    # Example: {"provider": "groq", "model": "llama-3.3-70b-versatile"}
    # Example: {"provider": "ollama", "model": "llama3.2", "base_url": "http://localhost:11434/v1"}
    llm: dict[str, Any] = Field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.5
        return self.correct_predictions / self.total_predictions

    def record_outcome(self, was_correct: bool) -> None:
        self.total_predictions += 1
        if was_correct:
            self.correct_predictions += 1
        # Exponentially weighted average — recent results matter more
        self.reputation = 0.95 * self.reputation + 0.05 * (1.0 if was_correct else 0.0)


# ═══════════════════════════════════════════════════════════════
# BASE AGENT
# ═══════════════════════════════════════════════════════════════

class BaseAgent(ABC):
    """
    Foundation for all TradingOS agents.

    Provider-agnostic: set LLM_PROVIDER / LLM_MODEL env vars,
    or override per-agent via AgentProfile.llm dict.

    Provides:
    - LLM calls with tool use (any provider: Anthropic, OpenAI, Groq, Ollama, etc.)
    - Automatic retry with exponential backoff
    - Outcome feedback and reputation tracking
    - Structured logging with agent context
    - Memory access via namespace isolation
    """

    def __init__(
        self,
        profile: AgentProfile,
        signal_bus_url: str | None = None,
        qdrant_url: str | None = None,
    ) -> None:
        self.profile = profile
        self.signal_bus_url = signal_bus_url or os.getenv("SIGNAL_BUS_URL", "http://signal-bus:7700")
        self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.llm: LLMProvider = create_provider(self._build_llm_config())

        self.log = logger.bind(
            agent_id=self.profile.id,
            agent_type=self.profile.agent_type,
            agent_name=self.profile.name,
            llm_provider=self.llm.provider_name,
            llm_model=self.llm.model,
        )

        self._conversation_history: list[LLMMessage] = []

    def _build_llm_config(self) -> LLMConfig:
        """Start from env defaults, apply profile-level overrides."""
        config = LLMConfig.from_env()
        config.temperature = self.profile.temperature
        config.max_tokens = self.profile.max_tokens
        for k, v in self.profile.llm.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config

    @property
    def system_prompt(self) -> str:
        """Override in subclasses to specialize agent behavior."""
        return f"""You are {self.profile.name}, an AI agent in the TradingOS Agent Parliament.

Your role: {self.profile.description}

Your reputation score: {self.profile.reputation:.3f} (based on {self.profile.total_predictions} past predictions)
Your accuracy: {self.profile.accuracy:.1%}

Core principles:
1. Be concise and specific — your outputs feed automated systems
2. Quantify everything — probabilities, confidence intervals, impact estimates
3. Think adversarially — what would prove you wrong?
4. Cite your reasoning — the Parliament needs to evaluate your logic
5. When uncertain, say so explicitly with a confidence score

Output format: Always respond with structured JSON unless told otherwise.
"""

    def reset_conversation(self) -> None:
        """Clear conversation history for a fresh context."""
        self._conversation_history = []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def call_llm(
        self,
        user_message: str,
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        """Make a provider-agnostic LLM call with automatic retry."""
        history = list(self._conversation_history)
        history.append(LLMMessage(role="user", content=user_message))

        self.log.debug("Calling LLM", message_len=len(user_message))

        resp = await self.llm.complete(
            messages=history,
            tools=tools,
            system=system or self.system_prompt,
        )

        # Update shared conversation history for multi-turn sessions
        self._conversation_history.append(LLMMessage(role="user", content=user_message))
        self._conversation_history.append(LLMMessage(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls,
        ))

        return resp

    async def run_tool_loop(
        self,
        initial_message: str,
        tools: list[ToolDefinition],
        tool_executor: "ToolExecutor",
        system: str | None = None,
    ) -> str:
        """
        Run a ReAct-style tool use loop until the LLM stops calling tools.
        Returns the final text output.
        """
        sys_prompt = system or self.system_prompt
        messages: list[LLMMessage] = list(self._conversation_history)
        messages.append(LLMMessage(role="user", content=initial_message))

        resp = await self.llm.complete(messages=messages, tools=tools, system=sys_prompt)
        messages.append(LLMMessage(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls,
        ))

        for _ in range(10):
            if not resp.has_tool_calls:
                return resp.content or ""

            tool_results = []
            for tc in resp.tool_calls:
                self.log.debug("Executing tool", tool=tc.name)
                result = await tool_executor.execute(tc.name, tc.arguments)
                tool_results.append({
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result),
                })

            resp = await self.llm.complete_tool_result(
                messages=messages,
                tool_results=tool_results,
                tools=tools,
                system=sys_prompt,
            )
            messages.append(LLMMessage(
                role="assistant",
                content=resp.content,
                tool_calls=resp.tool_calls,
            ))

        return "Max iterations reached"

    def update_reputation(self, was_correct: bool) -> None:
        """Called by the evolution system with prediction outcomes."""
        self.profile.record_outcome(was_correct)
        self.log.info(
            "Reputation updated",
            was_correct=was_correct,
            new_reputation=self.profile.reputation,
            accuracy=f"{self.profile.accuracy:.1%}",
        )

    @abstractmethod
    async def process(self, context: dict[str, Any]) -> dict[str, Any]:
        """Main agent processing method. Must be implemented by subclasses."""
        ...


class ToolExecutor:
    """Registry and executor for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, name: str, fn: Any) -> None:
        self._tools[name] = fn

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._tools:
            return {"error": f"Unknown tool: {name}"}
        fn = self._tools[name]
        if asyncio.iscoroutinefunction(fn):
            return await fn(**arguments)
        return fn(**arguments)
