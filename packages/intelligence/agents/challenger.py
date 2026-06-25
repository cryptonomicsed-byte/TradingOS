"""
Challenger Agent — The Devil's Advocate.

Every signal gets a Challenger. The Challenger's job is to find every reason
why this signal might be wrong, manipulated, risky, or poorly timed.
A signal that survives a rigorous challenge deserves higher conviction.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from .base import AgentProfile, BaseAgent, ToolExecutor
from ..llm import ToolDefinition

logger = structlog.get_logger(__name__)

CHALLENGER_SYSTEM_PROMPT = """You are a Challenger Agent in the TradingOS Parliament.

Your sole mission: Find every reason why a proposed trading signal might fail.
You are the devil's advocate. You are NOT trying to be balanced — you are trying
to BREAK the signal. If you can't break it, that means it's strong.

Your analysis must cover:
1. LIQUIDITY RISK: Is there enough liquidity to enter/exit without major slippage?
2. SMART MONEY RISK: Could this be a trap set by sophisticated traders?
3. MARKET MANIPULATION: Signs of wash trading, coordinated pump, or rugpull setup?
4. MACRO HEADWINDS: Are broader market conditions working against this signal?
5. TIMING RISK: Are we late to the move? Is the narrative already priced in?
6. CONTRACT RISK: For DeFi tokens — honeypot, mint function, ownership risk?
7. MEV RISK: Will sandwich bots front-run this trade?
8. SENTIMENT EXTREMES: Excessive greed/fear that historically reverses?

Your output must be a conviction_impact score:
- Strongly negative (-0.3 to -0.5): Signal likely to fail, recommend rejection
- Moderately negative (-0.1 to -0.3): Real concerns, conviction should decrease
- Neutral (0.0): No significant challenges found
- Positive (+0.05 to +0.1): Challenge backfired — signal is actually stronger

Be ruthless. Be specific. Cite data. A good challenge is backed by evidence.
"""

CHALLENGER_TOOLS = [
    {
        "name": "check_contract_security",
        "description": "Run security checks on a smart contract (rug check, honeypot, ownership)",
        "input_schema": {
            "type": "object",
            "properties": {
                "contract_address": {"type": "string"},
                "chain": {"type": "string"}
            },
            "required": ["contract_address", "chain"]
        }
    },
    {
        "name": "check_liquidity_depth",
        "description": "Analyze liquidity depth and estimated slippage for a position size",
        "input_schema": {
            "type": "object",
            "properties": {
                "pair_address": {"type": "string"},
                "position_size_usd": {"type": "number"}
            },
            "required": ["pair_address", "position_size_usd"]
        }
    },
    {
        "name": "check_mev_risk",
        "description": "Analyze MEV sandwich risk and bot activity for a token",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string"},
                "chain": {"type": "string"}
            },
            "required": ["token_address", "chain"]
        }
    },
    {
        "name": "get_holder_distribution",
        "description": "Check token holder concentration and insider wallet risk",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string"},
                "chain": {"type": "string"}
            },
            "required": ["token_address", "chain"]
        }
    },
    {
        "name": "check_narrative_age",
        "description": "Determine if the token's narrative is fresh or played out",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_symbol": {"type": "string"},
                "narrative_tags": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["token_symbol"]
        }
    },
    {
        "name": "submit_challenge",
        "description": "Submit the challenge result to the Signal Bus",
        "input_schema": {
            "type": "object",
            "properties": {
                "signal_id": {"type": "string"},
                "challenge_type": {
                    "type": "string",
                    "enum": [
                        "liquidity_risk", "contract_security", "market_manipulation",
                        "macro_headwind", "sentiment_extreme", "mev_risk",
                        "timing_risk", "holder_concentration"
                    ]
                },
                "arguments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of specific arguments against the signal"
                },
                "conviction_impact": {
                    "type": "number",
                    "description": "Impact on conviction: negative=bad, positive=challenge backfired"
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"]
                }
            },
            "required": ["signal_id", "challenge_type", "arguments", "conviction_impact", "severity"]
        }
    }
]


CHALLENGER_TOOL_DEFS: list[ToolDefinition] = [
    ToolDefinition.from_dict(t) for t in CHALLENGER_TOOLS
]


class ChallengerAgent(BaseAgent):
    """
    The Adversarial Validator — challenges every signal before Parliament.

    This agent runs independently for each signal session,
    attempting to find fatal flaws in the bull thesis.
    """

    def __init__(self, challenge_specialty: str = "general") -> None:
        profile = AgentProfile(
            agent_type="challenger",
            name=f"Challenger-{challenge_specialty.capitalize()}",
            description=f"Adversarial validator specializing in {challenge_specialty} risk factors",
            skills=["adversarial_analysis", "risk_assessment", challenge_specialty],
            memory_namespace=f"challenger_{challenge_specialty}",
        )
        super().__init__(profile)

        self.specialty = challenge_specialty
        self.http = httpx.AsyncClient(timeout=30)
        self._setup_tools()

    def _setup_tools(self) -> None:
        self.executor = ToolExecutor()
        self.executor.register("check_contract_security", self._check_contract_security)
        self.executor.register("check_liquidity_depth", self._check_liquidity_depth)
        self.executor.register("check_mev_risk", self._check_mev_risk)
        self.executor.register("get_holder_distribution", self._get_holder_distribution)
        self.executor.register("check_narrative_age", self._check_narrative_age)
        self.executor.register("submit_challenge", self._submit_challenge)

    @property
    def system_prompt(self) -> str:
        return CHALLENGER_SYSTEM_PROMPT + f"\nYour specialty: {self.specialty} risk factors."

    async def process(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Challenge a signal. Returns challenge results.

        context must contain:
        - signal_id: UUID of signal to challenge
        - signal_data: Full signal JSON
        - session_id: Parliament session ID (optional)
        """
        self.reset_conversation()

        signal = context.get("signal_data", {})
        signal_id = context.get("signal_id", "unknown")

        self.log.info(
            "Beginning challenge analysis",
            signal_id=signal_id,
            asset=signal.get("asset_symbol", "unknown"),
        )

        prompt = self._build_challenge_prompt(signal_id, signal)

        result = await self.run_tool_loop(
            initial_message=prompt,
            tools=CHALLENGER_TOOL_DEFS,
            tool_executor=self.executor,
            system=self.system_prompt,
        )

        return {
            "agent_id": self.profile.id,
            "agent_type": "challenger",
            "challenge_specialty": self.specialty,
            "result": result,
            "reputation": self.profile.reputation,
        }

    def _build_challenge_prompt(self, signal_id: str, signal: dict[str, Any]) -> str:
        return f"""Challenge this trading signal. Find every reason it might fail.

Signal ID: {signal_id}

Signal details:
{json.dumps(signal, indent=2)}

Your task:
1. Use the available tools to investigate every risk factor
2. Be thorough — check liquidity, security, MEV risk, holder distribution
3. After investigation, submit your challenge using submit_challenge
4. If you find the signal is actually strong (challenges don't hold up),
   submit with a positive conviction_impact to reward signal quality

Focus especially on: {self.specialty}

Be specific and data-driven. Vague concerns without evidence don't count."""

    async def _check_contract_security(self, contract_address: str, chain: str) -> dict[str, Any]:
        """Check contract security via RugCheck and GoPlus APIs."""
        results: dict[str, Any] = {
            "address": contract_address,
            "chain": chain,
            "checks": {}
        }

        # RugCheck.xyz (free for Solana)
        if chain.lower() == "solana":
            try:
                url = f"https://api.rugcheck.xyz/v1/tokens/{contract_address}/report"
                response = await self.http.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    results["rug_check"] = {
                        "score": data.get("score", 0),
                        "risks": data.get("risks", []),
                        "is_safe": data.get("score", 0) > 500,
                    }
            except Exception as e:
                results["rug_check"] = {"error": str(e)}

        # GoPlus (multi-chain)
        try:
            url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={contract_address}"
            response = await self.http.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                token_data = data.get("result", {}).get(contract_address.lower(), {})
                results["goplus"] = {
                    "is_honeypot": token_data.get("is_honeypot") == "1",
                    "cannot_sell_all": token_data.get("cannot_sell_all") == "1",
                    "is_mintable": token_data.get("is_mintable") == "1",
                    "is_proxy": token_data.get("is_proxy") == "1",
                    "hidden_owner": token_data.get("hidden_owner") == "1",
                    "buy_tax": float(token_data.get("buy_tax", 0)),
                    "sell_tax": float(token_data.get("sell_tax", 0)),
                }
        except Exception as e:
            results["goplus"] = {"error": str(e)}

        return results

    async def _check_liquidity_depth(self, pair_address: str, position_size_usd: float) -> dict[str, Any]:
        """Analyze liquidity and estimated price impact."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"
            response = await self.http.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                pair = data.get("pair", {})
                liquidity = float(pair.get("liquidity", {}).get("usd", 0))

                if liquidity > 0:
                    # Simplified price impact estimate (AMM x*y=k)
                    price_impact_pct = (position_size_usd / (liquidity * 2)) * 100

                    return {
                        "liquidity_usd": liquidity,
                        "position_size_usd": position_size_usd,
                        "estimated_price_impact_pct": round(price_impact_pct, 2),
                        "risk_level": (
                            "critical" if price_impact_pct > 5 else
                            "high" if price_impact_pct > 2 else
                            "medium" if price_impact_pct > 0.5 else
                            "low"
                        )
                    }
        except Exception as e:
            logger.warning("Failed liquidity check", error=str(e))
        return {"error": "Could not fetch liquidity data"}

    async def _check_mev_risk(self, token_address: str, chain: str) -> dict[str, Any]:
        """Assess MEV sandwich bot risk."""
        # In production: check Jito MEV data, analyze recent sandwich attacks
        return {
            "token": token_address,
            "mev_risk_level": "medium",
            "recent_sandwiches": 0,
            "recommendation": "Use Jito bundle for protection",
            "note": "Detailed MEV analysis requires Jito API"
        }

    async def _get_holder_distribution(self, token_address: str, chain: str) -> dict[str, Any]:
        """Check holder concentration risk."""
        # In production: Helius getTokenLargestAccounts
        return {
            "token": token_address,
            "top_10_holders_pct": 0,
            "insider_risk": "unknown",
            "note": "Holder data requires on-chain query"
        }

    async def _check_narrative_age(self, token_symbol: str, narrative_tags: list[str] | None = None) -> dict[str, Any]:
        """Check if narrative is fresh or exhausted."""
        return {
            "token": token_symbol,
            "narrative_age_days": 0,
            "narrative_freshness": "unknown",
            "similar_narratives": [],
        }

    async def _submit_challenge(
        self,
        signal_id: str,
        challenge_type: str,
        arguments: list[str],
        conviction_impact: float,
        severity: str,
    ) -> dict[str, Any]:
        """Submit challenge to Signal Bus."""
        payload = {
            "challenger_id": self.profile.id,
            "challenge_type": challenge_type,
            "arguments": arguments,
            "counter_evidence": [],
            "conviction_impact": conviction_impact,
        }

        try:
            response = await self.http.post(
                f"{self.signal_bus_url}/signals/{signal_id}/challenge",
                json=payload,
            )
            if response.status_code in (200, 201):
                self.log.info(
                    "Challenge submitted",
                    signal_id=signal_id,
                    type=challenge_type,
                    severity=severity,
                    impact=conviction_impact,
                )
                return {"success": True, "severity": severity, "impact": conviction_impact}
        except Exception as e:
            self.log.error("Failed to submit challenge", error=str(e))

        return {"success": False}
