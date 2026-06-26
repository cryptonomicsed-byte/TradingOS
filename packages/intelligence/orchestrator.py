"""
TradingOS Intelligence Orchestrator
FastAPI service that manages agent lifecycle and coordinates
signal spawning, challenging, and parliament voting.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents.signal_spawner import SignalSpawnerAgent
from agents.challenger import ChallengerAgent
from agents.base import AgentProfile

logger = structlog.get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# AGENT POOL
# ═══════════════════════════════════════════════════════════════

class AgentPool:
    """Manages a pool of agent instances."""

    def __init__(self) -> None:
        self.spawners: dict[str, SignalSpawnerAgent] = {}
        self.challengers: dict[str, ChallengerAgent] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        logger.info("Initializing agent pool")

        # Create spawner agents for each signal source type
        specializations = ["onchain", "social", "whale", "dex", "macro", "narrative"]
        for spec in specializations:
            self.spawners[spec] = SignalSpawnerAgent(specialization=spec)
            logger.info(f"Spawner agent ready: {spec}")

        # Create challenger agents
        challenge_specs = ["liquidity", "security", "manipulation", "macro", "timing"]
        for spec in challenge_specs:
            self.challengers[spec] = ChallengerAgent(challenge_specialty=spec)
            logger.info(f"Challenger agent ready: {spec}")

        self._initialized = True
        logger.info("Agent pool initialized", spawners=len(self.spawners), challengers=len(self.challengers))

    def get_spawner(self, specialization: str = "onchain") -> SignalSpawnerAgent:
        return self.spawners.get(specialization, list(self.spawners.values())[0])

    def get_challengers(self) -> list[ChallengerAgent]:
        return list(self.challengers.values())

    def get_all_agents(self) -> list[dict[str, Any]]:
        agents = []
        for spec, agent in self.spawners.items():
            agents.append({
                "id": agent.profile.id,
                "type": "spawner",
                "specialization": spec,
                "reputation": agent.profile.reputation,
                "accuracy": agent.profile.accuracy,
                "predictions": agent.profile.total_predictions,
            })
        for spec, agent in self.challengers.items():
            agents.append({
                "id": agent.profile.id,
                "type": "challenger",
                "specialization": spec,
                "reputation": agent.profile.reputation,
                "accuracy": agent.profile.accuracy,
                "predictions": agent.profile.total_predictions,
            })
        return agents


agent_pool = AgentPool()
scheduler = AsyncIOScheduler()

# ═══════════════════════════════════════════════════════════════
# SCHEDULED TASKS
# ═══════════════════════════════════════════════════════════════

async def run_signal_scan() -> None:
    """Periodic signal scan across all spawner agents."""
    logger.info("Running scheduled signal scan")

    market_context = {
        "tokens": [],  # In production: load from trending/radar data
        "data_snapshot": {},
        "focus": "opportunity_scan",
    }

    tasks = []
    for spec, spawner in agent_pool.spawners.items():
        context = {**market_context, "focus": f"{spec}_signals"}
        tasks.append(spawner.process(context))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for spec, result in zip(agent_pool.spawners.keys(), results):
        if isinstance(result, Exception):
            logger.error(f"Spawner {spec} failed", error=str(result))
        else:
            logger.info(f"Spawner {spec} complete", result_type=type(result).__name__)


async def run_challenge_sweep() -> None:
    """Challenge any signals in 'Spawned' state."""
    logger.info("Running challenge sweep")
    # In production: query Signal Bus for signals in Spawned state
    # and assign challenger agents
    pass


# ═══════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent_pool.initialize()

    # Schedule recurring tasks
    scheduler.add_job(run_signal_scan, "interval", minutes=5, id="signal_scan")
    scheduler.add_job(run_challenge_sweep, "interval", minutes=1, id="challenge_sweep")
    scheduler.start()

    logger.info("Intelligence orchestrator ready")
    yield

    scheduler.shutdown()
    logger.info("Intelligence orchestrator shutting down")


app = FastAPI(
    title="TradingOS Intelligence",
    description="Agent-native signal intelligence layer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "intelligence",
        "agents": {
            "spawners": len(agent_pool.spawners),
            "challengers": len(agent_pool.challengers),
        }
    }

# ─────────────────────────────────────────────────────────────
# AGENT ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    return agent_pool.get_all_agents()

@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    for agent in agent_pool.get_all_agents():
        if agent["id"] == agent_id:
            return agent
    raise HTTPException(status_code=404, detail="Agent not found")

# ─────────────────────────────────────────────────────────────
# SIGNAL ANALYSIS
# ─────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    tokens: list[str] = []
    focus: str = "general"
    spawner_type: str = "onchain"
    data_snapshot: dict[str, Any] = {}

@app.post("/analyze")
async def trigger_analysis(req: AnalysisRequest) -> dict[str, Any]:
    """Trigger a signal analysis run."""
    spawner = agent_pool.get_spawner(req.spawner_type)

    result = await spawner.process({
        "tokens": req.tokens,
        "focus": req.focus,
        "data_snapshot": req.data_snapshot,
    })

    return result

# ─────────────────────────────────────────────────────────────
# CHALLENGE ENDPOINT
# ─────────────────────────────────────────────────────────────

class ChallengeRequest(BaseModel):
    signal_id: str
    signal_data: dict[str, Any]
    challenge_types: list[str] = ["liquidity", "security", "manipulation"]

@app.post("/challenge")
async def challenge_signal(req: ChallengeRequest) -> dict[str, Any]:
    """Run adversarial challenge against a signal."""
    selected_challengers = [
        agent_pool.challengers[ct]
        for ct in req.challenge_types
        if ct in agent_pool.challengers
    ]

    if not selected_challengers:
        selected_challengers = agent_pool.get_challengers()[:3]

    context = {
        "signal_id": req.signal_id,
        "signal_data": req.signal_data,
    }

    tasks = [c.process(context) for c in selected_challengers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        "signal_id": req.signal_id,
        "challenges": [r for r in results if not isinstance(r, Exception)],
        "errors": [str(r) for r in results if isinstance(r, Exception)],
    }

# ─────────────────────────────────────────────────────────────
# MEMORY COURT
# ─────────────────────────────────────────────────────────────

class MemoryRecallRequest(BaseModel):
    description: str
    signal_data: dict[str, Any] = {}
    lookback_days: int = 90
    top_k: int = 5

@app.post("/memory/recall")
async def memory_recall(req: MemoryRecallRequest) -> dict[str, Any]:
    """Query the Memory Court for similar historical signals."""
    # This delegates to the Qdrant vector store
    return {
        "similar_signals": [],
        "historical_win_rate": 0.5,
        "testimony": "Memory Court returning neutral — building history",
        "sample_size": 0,
    }

# ─────────────────────────────────────────────────────────────
# SCAN TRIGGER
# ─────────────────────────────────────────────────────────────

@app.post("/scan")
async def trigger_scan() -> dict[str, Any]:
    """Manually trigger a full signal scan."""
    asyncio.create_task(run_signal_scan())
    return {"status": "scan_started"}

if __name__ == "__main__":
    port = int(os.getenv("INTELLIGENCE_PORT", "7703"))
    uvicorn.run(
        "orchestrator:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
