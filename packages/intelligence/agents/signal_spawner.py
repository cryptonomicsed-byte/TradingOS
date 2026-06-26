"""
Signal Spawner Agent — analyzes market data and generates typed signals.
This is where raw market data becomes structured SignalGenome objects.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from .base import AgentProfile, BaseAgent, ToolExecutor
from ..llm import ToolDefinition

logger = structlog.get_logger(__name__)

SPAWNER_SYSTEM_PROMPT = """You are a Signal Intelligence Agent in TradingOS.

Your job: Analyze raw market data and generate structured trading signals.

You have access to:
- Real-time price and volume data
- On-chain metrics (whale flows, DEX volumes, exchange flows)
- Social sentiment feeds
- Macro correlation data
- Historical pattern database

Signal generation rules:
1. Only generate signals with conviction > 0.5
2. Every signal needs at least 2 corroborating data points
3. Include specific entry, target, and stop-loss levels
4. Classify the signal source type clearly
5. Higher conviction requires more corroboration

Output MUST be a valid SignalGenome JSON object or null if no signal warranted.
"""

SIGNAL_TOOLS = [
    {
        "name": "get_token_metrics",
        "description": "Get current price, volume, liquidity, and market cap for a token",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string", "description": "Token contract address or symbol"},
                "chain": {"type": "string", "description": "Blockchain: solana, ethereum, base, etc."}
            },
            "required": ["token_address", "chain"]
        }
    },
    {
        "name": "get_whale_activity",
        "description": "Get recent whale wallet movements for a token",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string"},
                "lookback_hours": {"type": "number", "default": 24}
            },
            "required": ["token_address"]
        }
    },
    {
        "name": "get_social_sentiment",
        "description": "Get social media sentiment score and mention velocity for a token",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_symbol": {"type": "string"},
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["twitter", "telegram"]
                }
            },
            "required": ["token_symbol"]
        }
    },
    {
        "name": "get_dex_flow",
        "description": "Get DEX trading volume, buy/sell ratio, and large swap history",
        "input_schema": {
            "type": "object",
            "properties": {
                "pair_address": {"type": "string"},
                "lookback_minutes": {"type": "number", "default": 60}
            },
            "required": ["pair_address"]
        }
    },
    {
        "name": "search_memory_court",
        "description": "Search historical signal patterns similar to the current setup",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern_description": {"type": "string", "description": "Natural language description of the current market setup"},
                "lookback_days": {"type": "number", "default": 90}
            },
            "required": ["pattern_description"]
        }
    },
    {
        "name": "submit_signal",
        "description": "Submit a finalized signal to the Signal Bus for Parliament processing",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_symbol": {"type": "string"},
                "asset_chain": {"type": "string"},
                "asset_address": {"type": "string"},
                "signal_direction": {
                    "type": "string",
                    "enum": ["Long", "Short", "Hold", "Exit", "Alert"]
                },
                "target_pct": {"type": "number", "description": "Expected price movement %"},
                "timeframe_hours": {"type": "number"},
                "conviction": {"type": "number", "minimum": 0, "maximum": 1},
                "reasoning": {"type": "string"},
                "indicators": {"type": "object", "description": "Key/value metric pairs"},
                "tags": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["asset_symbol", "asset_chain", "signal_direction", "conviction", "reasoning"]
        }
    }
]


SIGNAL_TOOL_DEFS: list[ToolDefinition] = [
    ToolDefinition.from_dict(t) for t in SIGNAL_TOOLS
]


class SignalSpawnerAgent(BaseAgent):
    """
    Agent that transforms market data into SignalGenome objects.

    Uses a ReAct tool-calling loop to:
    1. Gather data from multiple sources
    2. Reason about whether a signal is warranted
    3. Generate a structured signal with full provenance
    """

    def __init__(self, specialization: str = "general") -> None:
        profile = AgentProfile(
            agent_type="signal_spawner",
            name=f"SignalSpawner-{specialization.capitalize()}",
            description=f"Analyzes {specialization} market data to generate trading signals",
            skills=["signal_generation", "market_analysis", specialization],
            memory_namespace=f"spawner_{specialization}",
        )
        super().__init__(profile)

        self.specialization = specialization
        self.http = httpx.AsyncClient(timeout=30)
        self._setup_tools()

    def _setup_tools(self) -> None:
        self.executor = ToolExecutor()
        self.executor.register("get_token_metrics", self._get_token_metrics)
        self.executor.register("get_whale_activity", self._get_whale_activity)
        self.executor.register("get_social_sentiment", self._get_social_sentiment)
        self.executor.register("get_dex_flow", self._get_dex_flow)
        self.executor.register("search_memory_court", self._search_memory_court)
        self.executor.register("submit_signal", self._submit_signal)

    @property
    def system_prompt(self) -> str:
        return SPAWNER_SYSTEM_PROMPT + f"\nYou specialize in: {self.specialization} signals."

    async def process(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Process market context and potentially generate a signal.

        context should contain:
        - tokens: list of tokens to analyze
        - data_snapshot: current market data
        - focus: optional specific angle (whale_activity, social_surge, etc.)
        """
        self.reset_conversation()

        prompt = self._build_analysis_prompt(context)

        self.log.info("Starting signal analysis", tokens=context.get("tokens", []))

        result_text = await self.run_tool_loop(
            initial_message=prompt,
            tools=SIGNAL_TOOL_DEFS,
            tool_executor=self.executor,
            system=self.system_prompt,
        )

        self.log.info("Signal analysis complete")

        return {
            "agent_id": self.profile.id,
            "agent_type": self.profile.agent_type,
            "result": result_text,
            "reputation": self.profile.reputation,
        }

    def _build_analysis_prompt(self, context: dict[str, Any]) -> str:
        tokens = context.get("tokens", [])
        focus = context.get("focus", "general opportunity scan")
        data = context.get("data_snapshot", {})

        return f"""Analyze the current market for trading signals.

Focus: {focus}
Tokens to analyze: {', '.join(tokens) if tokens else 'scan for opportunities'}

Current market context:
{json.dumps(data, indent=2)}

Instructions:
1. Use available tools to gather comprehensive data on each token
2. Search memory court for similar historical patterns
3. If you find a signal with conviction > 0.5, submit it using submit_signal
4. If no signals meet the threshold, explain why and what to watch for

Be systematic. Check multiple data sources before concluding."""

    async def _get_token_metrics(self, token_address: str, chain: str) -> dict[str, Any]:
        """Fetch token metrics from DexScreener/Birdeye."""
        try:
            # DexScreener is free and comprehensive
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = await self.http.get(url)
            if response.status_code == 200:
                data = response.json()
                pairs = data.get("pairs", [])
                if pairs:
                    pair = pairs[0]
                    return {
                        "symbol": pair.get("baseToken", {}).get("symbol"),
                        "price_usd": float(pair.get("priceUsd", 0)),
                        "volume_24h_usd": float(pair.get("volume", {}).get("h24", 0)),
                        "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                        "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0)),
                        "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                        "txns_24h": pair.get("txns", {}).get("h24", {}),
                        "dex": pair.get("dexId"),
                        "chain": pair.get("chainId"),
                    }
        except Exception as e:
            self.log.warning("Failed to fetch token metrics", error=str(e))
        return {"error": "Data unavailable", "token": token_address}

    async def _get_whale_activity(self, token_address: str, lookback_hours: float = 24) -> dict[str, Any]:
        """Fetch whale wallet movements."""
        # In production: Helius enhanced transactions API
        return {
            "token": token_address,
            "whale_buyers": 0,
            "whale_sellers": 0,
            "net_whale_flow_usd": 0,
            "large_txns": [],
            "note": "Whale data requires Helius API key"
        }

    async def _get_social_sentiment(self, token_symbol: str, platforms: list[str] | None = None) -> dict[str, Any]:
        """Fetch social sentiment scores."""
        return {
            "token": token_symbol,
            "sentiment_score": 0.5,
            "mention_velocity": 0,
            "platforms_checked": platforms or ["twitter", "telegram"],
            "note": "Social data requires API credentials"
        }

    async def _get_dex_flow(self, pair_address: str, lookback_minutes: float = 60) -> dict[str, Any]:
        """Get DEX trading flow data."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"
            response = await self.http.get(url)
            if response.status_code == 200:
                data = response.json()
                pair = data.get("pair", {})
                return {
                    "pair": pair_address,
                    "volume_1h": float(pair.get("volume", {}).get("h1", 0)),
                    "buys_1h": pair.get("txns", {}).get("h1", {}).get("buys", 0),
                    "sells_1h": pair.get("txns", {}).get("h1", {}).get("sells", 0),
                    "price_usd": float(pair.get("priceUsd", 0)),
                }
        except Exception as e:
            self.log.warning("Failed to fetch DEX flow", error=str(e))
        return {"error": "DEX data unavailable"}

    async def _search_memory_court(self, pattern_description: str, lookback_days: float = 90) -> dict[str, Any]:
        """Query the Memory Court for historical similar patterns."""
        try:
            url = f"{self.signal_bus_url.replace('7700', '7703')}/memory/recall"
            response = await self.http.post(url, json={
                "description": pattern_description,
                "lookback_days": int(lookback_days),
                "top_k": 5
            })
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {
            "similar_signals": [],
            "historical_win_rate": 0.5,
            "testimony": "Memory Court unavailable — no historical context"
        }

    async def _submit_signal(
        self,
        asset_symbol: str,
        asset_chain: str,
        signal_direction: str,
        conviction: float,
        reasoning: str,
        asset_address: str | None = None,
        target_pct: float = 0.0,
        timeframe_hours: float = 24.0,
        indicators: dict[str, float] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit signal to Signal Bus."""
        payload = {
            "asset_symbol": asset_symbol,
            "asset_chain": asset_chain,
            "asset_address": asset_address,
            "signal_type": {
                "type": signal_direction,
                "target_pct": target_pct,
                "timeframe_hours": timeframe_hours,
            },
            "source_type": f"agent_{self.specialization}_spawner",
            "indicators": indicators or {},
            "tags": tags or [],
        }

        try:
            response = await self.http.post(
                f"{self.signal_bus_url}/signals",
                json=payload,
            )
            if response.status_code in (200, 201):
                signal_id = response.json().get("id")
                self.log.info(
                    "Signal submitted",
                    signal_id=signal_id,
                    asset=asset_symbol,
                    direction=signal_direction,
                    conviction=conviction,
                )
                return {"success": True, "signal_id": signal_id, "conviction": conviction}
        except Exception as e:
            self.log.error("Failed to submit signal", error=str(e))

        return {"success": False, "error": "Submission failed"}
