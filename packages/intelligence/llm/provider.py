"""
LLM Provider Abstraction — provider-agnostic interface for all agent LLM calls.

Agents declare WHAT they need (tool use, streaming, structured output).
The provider handles HOW to get it from whatever LLM they're configured to use.

Supported providers:
  - anthropic     → Claude family
  - openai        → GPT-4o, o1, etc.
  - groq          → Llama, Mixtral, Gemma (ultra-fast inference)
  - ollama        → Any local model (Llama, Mistral, Qwen, etc.)
  - google        → Gemini family
  - openai-compat → Any OpenAI-compatible endpoint (Together, Fireworks, vLLM, etc.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════
# UNIFIED TYPES — provider-agnostic message/response format
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str           # "user" | "assistant" | "system" | "tool"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None   # For tool result messages


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    content: str
    tool_calls: list[ToolCall]
    stop_reason: str        # "tool_use" | "end_turn" | "stop" | "length"
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_done(self) -> bool:
        return not self.has_tool_calls


@dataclass
class LLMConfig:
    """
    Per-agent LLM configuration.
    Stored in AgentProfile so each agent can use a different LLM.
    """
    provider: str           # "anthropic" | "openai" | "groq" | "ollama" | "google" | "openai-compat"
    model: str              # e.g. "claude-sonnet-4-6", "gpt-4o", "llama-3.1-70b-versatile"
    api_key: str | None = None          # Overrides env var if set
    base_url: str | None = None         # For openai-compat / ollama
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 60

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build config from environment variables."""
        import os
        provider = os.getenv("LLM_PROVIDER", "anthropic")
        model = os.getenv("LLM_MODEL", _default_model(provider))
        return cls(
            provider=provider,
            model=model,
            api_key=os.getenv("LLM_API_KEY") or _provider_api_key(provider),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("AGENT_MAX_TOKENS", "4096")),
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LLMConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _default_model(provider: str) -> str:
    defaults = {
        "anthropic": "claude-sonnet-4-6",
        "openai": "gpt-4o",
        "groq": "llama-3.3-70b-versatile",
        "ollama": "llama3.2",
        "google": "gemini-2.0-flash",
        "openai-compat": "llama-3.1-70b",
    }
    return defaults.get(provider, "gpt-4o")


def _provider_api_key(provider: str) -> str | None:
    import os
    env_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "google": "GOOGLE_API_KEY",
        "ollama": None,
        "openai-compat": "LLM_API_KEY",
    }
    env_var = env_keys.get(provider)
    return os.getenv(env_var) if env_var else None


# ═══════════════════════════════════════════════════════════════
# TOOL DEFINITION FORMAT — normalized, provider translates
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolDefinition:
    """
    Provider-agnostic tool definition.
    Each provider's adapter translates this to its native format.
    """
    name: str
    description: str
    parameters: dict[str, Any]      # JSON Schema object

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolDefinition":
        """Accept either Anthropic-style (input_schema) or OpenAI-style (parameters)."""
        schema = d.get("input_schema") or d.get("parameters") or {}
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            parameters=schema,
        )


# ═══════════════════════════════════════════════════════════════
# ABSTRACT PROVIDER
# ═══════════════════════════════════════════════════════════════

class LLMProvider(ABC):
    """
    Base class for all LLM providers.
    Subclasses translate to/from the provider's native API format.
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        """Send messages and get a response. Tool calls will be in the response."""
        ...

    @abstractmethod
    async def complete_tool_result(
        self,
        messages: list[LLMMessage],
        tool_results: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        """Continue a conversation after tool execution."""
        ...

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def provider_name(self) -> str:
        return self.config.provider
