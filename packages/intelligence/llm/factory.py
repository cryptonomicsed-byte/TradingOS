"""
LLM Provider Factory — resolves a LLMConfig to a concrete provider instance.
"""

from __future__ import annotations

from .provider import LLMConfig, LLMProvider


def create_provider(config: LLMConfig) -> LLMProvider:
    """
    Instantiate the correct provider from config.

    provider values:
      "anthropic"    → AnthropicProvider (Claude)
      "openai"       → OpenAICompatProvider
      "groq"         → OpenAICompatProvider with Groq base URL
      "ollama"       → OpenAICompatProvider with Ollama base URL
      "google"       → GoogleProvider (Gemini)
      "together"     → OpenAICompatProvider with Together AI base URL
      "fireworks"    → OpenAICompatProvider with Fireworks base URL
      "openai-compat"→ OpenAICompatProvider with custom base_url
    """
    p = config.provider.lower()

    if p == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(config)

    if p in ("openai", "groq", "ollama", "together", "fireworks", "openai-compat"):
        from .openai_provider import OpenAICompatProvider
        return OpenAICompatProvider(config)

    if p == "google":
        from .google_provider import GoogleProvider
        return GoogleProvider(config)

    raise ValueError(
        f"Unknown LLM provider: '{p}'. "
        f"Supported: anthropic, openai, groq, ollama, google, together, fireworks, openai-compat"
    )


def provider_from_env() -> LLMProvider:
    """Convenience: build provider from environment variables."""
    return create_provider(LLMConfig.from_env())
