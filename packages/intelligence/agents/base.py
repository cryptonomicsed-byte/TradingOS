"""
Base agent infrastructure for TradingOS.
All Claude-powered agents inherit from BaseAgent.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import anthropic
import structlog
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

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
    model: str = "claude-sonnet-4-6"
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

    @property
    def accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.5
        return self.correct_predictions / self.total_predictions

    def record_outcome(self, was_correct: bool) -> None:
        self.total_predictions += 1
        if was_correct:
            self.correct_predictions += 1
        # Reputation is exponentially weighted average (recent matters more)
        self.reputation = 0.95 * self.reputation + 0.05 * (1.0 if was_correct else 0.0)


# ═══════════════════════════════════════════════════════════════
# BASE AGENT
# ═══════════════════════════════════════════════════════════════

class BaseAgent(ABC):
    """
    Foundation for all Claude-powered TradingOS agents.

    Provides:
    - Structured Claude API calls with tool use
    - Automatic retry with backoff
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
        self.client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        self.log = logger.bind(
            agent_id=self.profile.id,
            agent_type=self.profile.agent_type,
            agent_name=self.profile.name,
        )

        self._conversation_history: list[dict[str, Any]] = []

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def call_claude(
        self,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> anthropic.types.Message:
        """Make a Claude API call with automatic retry."""

        messages = self._conversation_history + [
            {"role": "user", "content": user_message}
        ]

        kwargs: dict[str, Any] = {
            "model": self.profile.model,
            "max_tokens": self.profile.max_tokens,
            "system": system or self.system_prompt,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        self.log.debug("Calling Claude API", message_len=len(user_message))
        response = await self.client.messages.create(**kwargs)  # type: ignore[arg-type]

        # Update conversation history for multi-turn
        self._conversation_history.append({"role": "user", "content": user_message})
        self._conversation_history.append({"role": "assistant", "content": response.content})

        return response

    def reset_conversation(self) -> None:
        """Clear conversation history for a fresh context."""
        self._conversation_history = []

    async def run_tool_loop(
        self,
        initial_message: str,
        tools: list[dict[str, Any]],
        tool_executor: "ToolExecutor",
        system: str | None = None,
    ) -> str:
        """
        Run a ReAct-style tool use loop until Claude stops calling tools.
        Returns the final text output.
        """
        message = initial_message
        max_iterations = 10

        for _ in range(max_iterations):
            response = await self.call_claude(message, tools=tools, system=system)

            # If no tool calls, we're done
            if response.stop_reason != "tool_use":
                text_blocks = [b for b in response.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else ""

            # Execute tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    self.log.debug("Executing tool", tool=block.name, input=block.input)
                    result = await tool_executor.execute(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            # Continue conversation with tool results
            self._conversation_history.append({
                "role": "user",
                "content": tool_results,
            })

            message = "Continue based on the tool results."

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

    def to_claude_format(self) -> list[dict[str, Any]]:
        """Tools are registered with their schemas separately."""
        return []
