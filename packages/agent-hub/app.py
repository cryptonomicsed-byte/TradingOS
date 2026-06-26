"""
TradingOS Agent Hub — Universal Agent Interface Layer

Any agent framework (LangChain, AutoGen, CrewAI, Hermes, OpenClaw, custom)
can plug in here to:
  - Register a persistent account with API key auth
  - Read/write working memory (ephemeral, Redis-backed)
  - Store and recall long-term memories (semantic vector search via Qdrant)
  - Log episodic memory (timestamped event history)
  - Manage a structured knowledge base
  - Send/receive messages to other agents (A2A)
  - Maintain sessions with persistent state and conversation history

Port: 7704
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncIterator

import asyncpg
import redis.asyncio as aioredis
import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

POSTGRES_DSN = os.getenv("DATABASE_URL", "postgresql://tradingos:tradingos@postgres:5432/tradingos")
REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379")
QDRANT_URL   = os.getenv("QDRANT_URL", "http://qdrant:6333")
PORT         = int(os.getenv("AGENT_HUB_PORT", "7704"))

WORKING_MEM_TTL   = int(os.getenv("WORKING_MEMORY_TTL_SECS", "3600"))   # 1 hour default
A2A_INBOX_TTL     = int(os.getenv("A2A_INBOX_TTL_SECS", "86400"))       # 24 hours
EMBED_MODEL       = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")  # fastembed default

# ═══════════════════════════════════════════════════════════════
# GLOBALS — initialized in lifespan
# ═══════════════════════════════════════════════════════════════

db_pool: asyncpg.Pool | None = None
redis_client: aioredis.Redis | None = None
qdrant_client: Any | None = None
qdrant_available = False


# ═══════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    name: str
    agent_type: str = "external"
    framework: str | None = None          # langchain, autogen, crewai, hermes, etc.
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    llm_config: dict[str, Any] = Field(default_factory=dict)

class UpdateProfileRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    skills: list[str] | None = None
    capabilities: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    llm_config: dict[str, Any] | None = None

class WorkingMemorySet(BaseModel):
    value: Any
    ttl: int | None = None                # seconds, overrides default

class RememberRequest(BaseModel):
    content: str                          # text to embed and store
    metadata: dict[str, Any] = Field(default_factory=dict)
    importance: float = 0.5
    tags: list[str] = Field(default_factory=list)
    namespace: str = ""                   # empty = personal, else shared

class RecallRequest(BaseModel):
    query: str
    limit: int = 5
    min_score: float = 0.0
    namespace: str = ""                   # empty = personal, else shared
    tags: list[str] | None = None

class EpisodeRequest(BaseModel):
    event_type: str
    content: dict[str, Any]
    session_id: str | None = None
    outcome: str = "pending"
    importance: float = 0.5
    tags: list[str] = Field(default_factory=list)

class KnowledgeSet(BaseModel):
    value: Any
    category: str = "general"
    confidence: float = 1.0
    source: str | None = None
    ttl_hours: float | None = None

class SendMessageRequest(BaseModel):
    to_agent_id: str
    content: dict[str, Any]
    subject: str | None = None
    message_type: str = "message"         # message, task, notification, response
    channel: str = "direct"
    priority: int = 5
    reply_to_id: str | None = None
    ttl_hours: float | None = None

class BroadcastRequest(BaseModel):
    channel: str
    content: dict[str, Any]
    message_type: str = "broadcast"

class CreateSessionRequest(BaseModel):
    session_id: str | None = None         # auto-generate if not provided
    name: str | None = None
    purpose: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)

class UpdateSessionRequest(BaseModel):
    state: dict[str, Any] | None = None
    name: str | None = None
    purpose: str | None = None
    context: dict[str, Any] | None = None

class HistoryAppendRequest(BaseModel):
    role: str                             # user, assistant, system, tool
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key_to_return_once, display_prefix)."""
    raw = f"tos_{secrets.token_urlsafe(32)}"
    return raw, raw[:12] + "..."

async def auth_agent(x_agent_key: str = Header(..., alias="X-Agent-Key")) -> dict[str, Any]:
    """Dependency: validates X-Agent-Key header, returns agent row."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    key_hash = hash_key(x_agent_key)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agents WHERE api_key_hash = $1 AND is_active = TRUE",
            key_hash,
        )
        if not row:
            raise HTTPException(401, "Invalid or inactive API key")
        await conn.execute(
            "UPDATE agents SET last_seen_at = NOW() WHERE id = $1",
            row["id"],
        )
        return dict(row)


# ═══════════════════════════════════════════════════════════════
# QDRANT HELPERS
# ═══════════════════════════════════════════════════════════════

def _collection_name(agent_id: str, namespace: str = "") -> str:
    if namespace:
        safe = namespace.replace("/", "_").replace("-", "_")[:40]
        return f"shared_{safe}"
    safe = str(agent_id).replace("-", "")[:32]
    return f"mem_{safe}"

def _ensure_collection(name: str) -> None:
    if not qdrant_client or not qdrant_available:
        return
    try:
        qdrant_client.get_collection(name)
    except Exception:
        try:
            from qdrant_client import models as qm
            qdrant_client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(size=384, distance=qm.Distance.COSINE),
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# LIFESPAN
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client, qdrant_client, qdrant_available

    logger.info("Agent Hub starting up")

    # PostgreSQL
    db_pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=10)
    logger.info("PostgreSQL connected")

    # Redis
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.ping()
    logger.info("Redis connected")

    # Qdrant (optional — graceful degradation without it)
    try:
        from qdrant_client import QdrantClient
        qdrant_client = QdrantClient(url=QDRANT_URL, prefer_grpc=False)
        qdrant_client.get_collections()
        qdrant_available = True
        logger.info("Qdrant connected — semantic memory enabled")
    except Exception as e:
        logger.warning("Qdrant unavailable — semantic memory disabled", error=str(e))

    logger.info("Agent Hub ready", port=PORT)
    yield

    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.close()
    logger.info("Agent Hub shutdown complete")


# ═══════════════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="TradingOS Agent Hub",
    description=(
        "Universal agent interface — register, authenticate, remember, communicate. "
        "Works with any agent framework: LangChain, AutoGen, CrewAI, Hermes, OpenClaw, and custom agents."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "agent-hub",
        "version": "1.0.0",
        "backends": {
            "postgres": db_pool is not None,
            "redis": redis_client is not None,
            "qdrant": qdrant_available,
        },
    }


# ═══════════════════════════════════════════════════════════════
# AGENT REGISTRY — /agents/*
# ═══════════════════════════════════════════════════════════════

@app.post("/agents/register", status_code=201)
async def register_agent(req: RegisterRequest) -> dict[str, Any]:
    """
    Register a new agent account.
    Returns a one-time API key — store it securely, it cannot be retrieved again.
    """
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    raw_key, prefix = generate_api_key()
    key_hash = hash_key(raw_key)
    agent_id = str(uuid.uuid4())

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agents (id, name, agent_type, framework, description, skills,
                                api_key_hash, api_key_prefix, capabilities, metadata, llm_config)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            agent_id, req.name, req.agent_type, req.framework, req.description,
            req.skills, key_hash, prefix,
            json.dumps(req.capabilities), json.dumps(req.metadata), json.dumps(req.llm_config),
        )

    logger.info("Agent registered", agent_id=agent_id, name=req.name, framework=req.framework)
    return {
        "agent_id": agent_id,
        "name": req.name,
        "api_key": raw_key,                  # shown ONCE — agent must store this
        "api_key_prefix": prefix,
        "message": "Registration successful. Store your api_key securely — it cannot be retrieved.",
    }


@app.get("/agents")
async def list_agents(
    framework: str | None = Query(None),
    skill: str | None = Query(None),
    agent_type: str | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[dict[str, Any]]:
    """Discover registered agents. Filterable by framework, skill, and type."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, agent_type, framework, description, skills,
                   api_key_prefix, capabilities, reputation, total_interactions,
                   created_at, last_seen_at
            FROM agents
            WHERE is_active = TRUE
              AND ($1::TEXT IS NULL OR framework = $1)
              AND ($2::TEXT IS NULL OR agent_type = $2)
              AND ($3::TEXT IS NULL OR $3 = ANY(skills))
            ORDER BY last_seen_at DESC
            LIMIT $4
            """,
            framework, agent_type, skill, limit,
        )
        return [_agent_row(r) for r in rows]


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, agent_type, framework, description, skills,
                   api_key_prefix, capabilities, metadata, llm_config,
                   reputation, total_interactions, created_at, last_seen_at
            FROM agents WHERE id = $1 AND is_active = TRUE
            """,
            agent_id,
        )
        if not row:
            raise HTTPException(404, "Agent not found")
        return _agent_row(row, full=True)


@app.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    req: UpdateProfileRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Update your own agent profile. Requires X-Agent-Key."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Can only update your own profile")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        if req.name is not None:
            await conn.execute("UPDATE agents SET name=$1 WHERE id=$2", req.name, agent_id)
        if req.description is not None:
            await conn.execute("UPDATE agents SET description=$1 WHERE id=$2", req.description, agent_id)
        if req.skills is not None:
            await conn.execute("UPDATE agents SET skills=$1 WHERE id=$2", req.skills, agent_id)
        if req.capabilities is not None:
            await conn.execute("UPDATE agents SET capabilities=$1 WHERE id=$2", json.dumps(req.capabilities), agent_id)
        if req.metadata is not None:
            await conn.execute("UPDATE agents SET metadata=$1 WHERE id=$2", json.dumps(req.metadata), agent_id)
        if req.llm_config is not None:
            await conn.execute("UPDATE agents SET llm_config=$1 WHERE id=$2", json.dumps(req.llm_config), agent_id)
    return {"success": True, "agent_id": agent_id}


@app.delete("/agents/{agent_id}")
async def deregister_agent(agent_id: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Deactivate your agent account."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Can only deregister your own account")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE agents SET is_active=FALSE WHERE id=$1", agent_id)
    return {"success": True, "agent_id": agent_id, "status": "deactivated"}


def _agent_row(row: Any, full: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(row["id"]),
        "name": row["name"],
        "agent_type": row["agent_type"],
        "framework": row["framework"],
        "description": row["description"],
        "skills": list(row["skills"] or []),
        "api_key_prefix": row["api_key_prefix"],
        "reputation": row["reputation"],
        "total_interactions": row["total_interactions"],
        "last_seen_at": row["last_seen_at"].isoformat() if row["last_seen_at"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
    if full:
        d["capabilities"] = _json_field(row, "capabilities")
        d["metadata"] = _json_field(row, "metadata")
        d["llm_config"] = _json_field(row, "llm_config")
    else:
        d["capabilities"] = _json_field(row, "capabilities")
    return d


def _json_field(row: Any, field: str) -> Any:
    v = row[field]
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


# ═══════════════════════════════════════════════════════════════
# WORKING MEMORY — /memory/{agent_id}/working/*
# Redis-backed ephemeral key-value store
# ═══════════════════════════════════════════════════════════════

def _wkey(agent_id: str, key: str) -> str:
    return f"wm:{agent_id}:{key}"

def _wprefix(agent_id: str) -> str:
    return f"wm:{agent_id}:*"


@app.put("/memory/{agent_id}/working/{key}")
async def working_set(
    agent_id: str, key: str, req: WorkingMemorySet,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Set a working memory value. Ephemeral — expires after TTL."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot write to another agent's memory")
    if not redis_client:
        raise HTTPException(503, "Redis unavailable")
    ttl = req.ttl or WORKING_MEM_TTL
    await redis_client.setex(_wkey(agent_id, key), ttl, json.dumps(req.value))
    return {"key": key, "ttl_secs": ttl}


@app.get("/memory/{agent_id}/working/{key}")
async def working_get(
    agent_id: str, key: str,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Get a working memory value."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot read another agent's memory")
    if not redis_client:
        raise HTTPException(503, "Redis unavailable")
    raw = await redis_client.get(_wkey(agent_id, key))
    if raw is None:
        raise HTTPException(404, f"Key '{key}' not found in working memory")
    ttl = await redis_client.ttl(_wkey(agent_id, key))
    return {"key": key, "value": json.loads(raw), "ttl_remaining": ttl}


@app.get("/memory/{agent_id}/working")
async def working_list(agent_id: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """List all working memory keys for this agent."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot list another agent's memory")
    if not redis_client:
        raise HTTPException(503, "Redis unavailable")
    keys = await redis_client.keys(_wprefix(agent_id))
    prefix_len = len(f"wm:{agent_id}:")
    entries = []
    for k in keys:
        raw = await redis_client.get(k)
        ttl = await redis_client.ttl(k)
        if raw:
            entries.append({"key": k[prefix_len:], "value": json.loads(raw), "ttl_remaining": ttl})
    return {"agent_id": agent_id, "count": len(entries), "entries": entries}


@app.delete("/memory/{agent_id}/working/{key}")
async def working_delete(agent_id: str, key: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Delete a working memory key."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot delete another agent's memory")
    if not redis_client:
        raise HTTPException(503, "Redis unavailable")
    deleted = await redis_client.delete(_wkey(agent_id, key))
    return {"key": key, "deleted": bool(deleted)}


# ═══════════════════════════════════════════════════════════════
# LONG-TERM MEMORY — /memory/{agent_id}/remember + /recall
# Qdrant vector store — semantic similarity search
# ═══════════════════════════════════════════════════════════════

@app.post("/memory/{agent_id}/remember")
async def remember(
    agent_id: str, req: RememberRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Store a memory in the long-term vector store."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot write to another agent's memory")
    if not qdrant_available or not qdrant_client:
        raise HTTPException(503, "Semantic memory (Qdrant) unavailable")

    collection = _collection_name(agent_id, req.namespace)
    _ensure_collection(collection)

    memory_id = str(uuid.uuid4())
    payload = {
        "id": memory_id,
        "agent_id": agent_id,
        "content": req.content,
        "importance": req.importance,
        "tags": req.tags,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **req.metadata,
    }

    try:
        qdrant_client.add(
            collection_name=collection,
            documents=[req.content],
            metadata=[payload],
            ids=[memory_id],
        )
    except Exception as e:
        logger.error("Failed to store memory", error=str(e))
        raise HTTPException(500, f"Failed to store memory: {e}")

    return {"memory_id": memory_id, "collection": collection}


@app.post("/memory/{agent_id}/recall")
async def recall(
    agent_id: str, req: RecallRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Semantic search over long-term memories."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot search another agent's memory")
    if not qdrant_available or not qdrant_client:
        raise HTTPException(503, "Semantic memory (Qdrant) unavailable")

    collection = _collection_name(agent_id, req.namespace)
    try:
        results = qdrant_client.query(
            collection_name=collection,
            query_text=req.query,
            limit=req.limit,
        )
        memories = [
            {
                "memory_id": r.id,
                "content": r.metadata.get("content", ""),
                "score": r.score,
                "importance": r.metadata.get("importance", 0.5),
                "tags": r.metadata.get("tags", []),
                "created_at": r.metadata.get("created_at"),
                "metadata": {k: v for k, v in r.metadata.items()
                             if k not in ("content", "importance", "tags", "created_at", "agent_id", "id")},
            }
            for r in results
            if r.score >= req.min_score
        ]
    except Exception as e:
        logger.warning("Memory recall failed", error=str(e))
        memories = []

    return {"query": req.query, "memories": memories, "count": len(memories)}


@app.get("/memory/{agent_id}/memories")
async def list_memories(
    agent_id: str,
    namespace: str = Query(""),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """List memories in this agent's collection."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot list another agent's memory")
    if not qdrant_available or not qdrant_client:
        return {"memories": [], "total": 0, "note": "Qdrant unavailable"}

    collection = _collection_name(agent_id, namespace)
    try:
        results, _next = qdrant_client.scroll(
            collection_name=collection,
            limit=limit,
            offset=offset,
            with_payload=True,
        )
        memories = [
            {"memory_id": r.id, "content": r.payload.get("content", ""), "created_at": r.payload.get("created_at")}
            for r in results
        ]
        return {"memories": memories, "count": len(memories)}
    except Exception:
        return {"memories": [], "count": 0}


@app.delete("/memory/{agent_id}/memories/{memory_id}")
async def delete_memory(agent_id: str, memory_id: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Delete a specific memory."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot delete another agent's memory")
    if not qdrant_available or not qdrant_client:
        raise HTTPException(503, "Qdrant unavailable")
    collection = _collection_name(agent_id)
    qdrant_client.delete(collection_name=collection, points_selector=[memory_id])
    return {"deleted": memory_id}


# ═══════════════════════════════════════════════════════════════
# EPISODIC MEMORY — /memory/{agent_id}/episodes
# Timestamped event log in PostgreSQL
# ═══════════════════════════════════════════════════════════════

@app.post("/memory/{agent_id}/episodes")
async def record_episode(
    agent_id: str, req: EpisodeRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Record an episode (event) in episodic memory."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot write to another agent's memory")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    ep_id = str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_episodes (id, agent_id, session_id, event_type, content, outcome, importance, tags)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            ep_id, agent_id, req.session_id, req.event_type,
            json.dumps(req.content), req.outcome, req.importance, req.tags,
        )
    return {"episode_id": ep_id, "event_type": req.event_type}


@app.get("/memory/{agent_id}/episodes")
async def get_episodes(
    agent_id: str,
    event_type: str | None = Query(None),
    session_id: str | None = Query(None),
    limit: int = Query(20, le=100),
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Retrieve episodic memory. Filter by event type or session."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot read another agent's memory")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, event_type, content, outcome, importance, tags, created_at
            FROM agent_episodes
            WHERE agent_id = $1
              AND ($2::TEXT IS NULL OR event_type = $2)
              AND ($3::TEXT IS NULL OR session_id = $3)
            ORDER BY created_at DESC
            LIMIT $4
            """,
            agent_id, event_type, session_id, limit,
        )
        episodes = [
            {
                "episode_id": str(r["id"]),
                "session_id": r["session_id"],
                "event_type": r["event_type"],
                "content": json.loads(r["content"]) if isinstance(r["content"], str) else r["content"],
                "outcome": r["outcome"],
                "importance": r["importance"],
                "tags": list(r["tags"] or []),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
        return {"agent_id": agent_id, "episodes": episodes, "count": len(episodes)}


# ═══════════════════════════════════════════════════════════════
# KNOWLEDGE BASE — /memory/{agent_id}/knowledge
# Structured key-value facts in PostgreSQL
# ═══════════════════════════════════════════════════════════════

@app.put("/memory/{agent_id}/knowledge/{key}")
async def set_knowledge(
    agent_id: str, key: str, req: KnowledgeSet,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Store or update a knowledge fact."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot write to another agent's knowledge base")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    expires_at = None
    if req.ttl_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=req.ttl_hours)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_knowledge (agent_id, key, value, category, confidence, source, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (agent_id, key) DO UPDATE SET
                value=$3, category=$4, confidence=$5, source=$6, expires_at=$7, updated_at=NOW()
            """,
            agent_id, key, json.dumps(req.value),
            req.category, req.confidence, req.source, expires_at,
        )
    return {"key": key, "category": req.category}


@app.get("/memory/{agent_id}/knowledge/{key}")
async def get_knowledge(agent_id: str, key: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Retrieve a specific knowledge fact."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot read another agent's knowledge base")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT key, value, category, confidence, source, expires_at, updated_at
            FROM agent_knowledge
            WHERE agent_id=$1 AND key=$2
              AND (expires_at IS NULL OR expires_at > NOW())
            """,
            agent_id, key,
        )
        if not row:
            raise HTTPException(404, f"Knowledge key '{key}' not found")
        return {
            "key": row["key"],
            "value": json.loads(row["value"]) if isinstance(row["value"], str) else row["value"],
            "category": row["category"],
            "confidence": row["confidence"],
            "source": row["source"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "updated_at": row["updated_at"].isoformat(),
        }


@app.get("/memory/{agent_id}/knowledge")
async def list_knowledge(
    agent_id: str,
    category: str | None = Query(None),
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """List all knowledge facts, optionally filtered by category."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot list another agent's knowledge base")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key, value, category, confidence, updated_at
            FROM agent_knowledge
            WHERE agent_id=$1
              AND ($2::TEXT IS NULL OR category=$2)
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY category, key
            """,
            agent_id, category,
        )
        facts = [
            {
                "key": r["key"],
                "value": json.loads(r["value"]) if isinstance(r["value"], str) else r["value"],
                "category": r["category"],
                "confidence": r["confidence"],
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
        return {"agent_id": agent_id, "knowledge": facts, "count": len(facts)}


@app.delete("/memory/{agent_id}/knowledge/{key}")
async def delete_knowledge(agent_id: str, key: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot delete another agent's knowledge")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM agent_knowledge WHERE agent_id=$1 AND key=$2", agent_id, key)
    return {"deleted": key}


# ═══════════════════════════════════════════════════════════════
# SHARED MEMORY — /memory/shared/{namespace}/*
# Cross-agent shared spaces (agents can collaborate)
# ═══════════════════════════════════════════════════════════════

@app.post("/memory/shared/{namespace}/remember")
async def shared_remember(
    namespace: str, req: RememberRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Store a memory in a shared namespace (readable by all agents)."""
    req.namespace = namespace
    req.metadata["author_agent_id"] = str(agent["id"])
    req.metadata["author_name"] = agent["name"]
    return await remember(str(agent["id"]), req, agent)


@app.post("/memory/shared/{namespace}/recall")
async def shared_recall(
    namespace: str, req: RecallRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Search memories in a shared namespace."""
    req.namespace = namespace
    return await recall(str(agent["id"]), req, agent)


# ═══════════════════════════════════════════════════════════════
# A2A MESSAGING — /a2a/*
# Agent-to-agent communication
# ═══════════════════════════════════════════════════════════════

@app.post("/a2a/send")
async def send_message(req: SendMessageRequest, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Send a message to another agent. Delivered via Redis + persisted in Postgres."""
    if not db_pool or not redis_client:
        raise HTTPException(503, "Database or Redis unavailable")

    msg_id = str(uuid.uuid4())
    expires_at = None
    if req.ttl_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=req.ttl_hours)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM agents WHERE id=$1 AND is_active=TRUE", req.to_agent_id)
        if not row:
            raise HTTPException(404, f"Target agent '{req.to_agent_id}' not found or inactive")

        await conn.execute(
            """
            INSERT INTO agent_messages (id, from_agent_id, from_agent_name, to_agent_id,
                                        channel, subject, content, message_type, priority,
                                        reply_to_id, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            msg_id, str(agent["id"]), agent["name"], req.to_agent_id,
            req.channel, req.subject, json.dumps(req.content), req.message_type,
            req.priority, req.reply_to_id, expires_at,
        )

    # Publish to Redis for real-time delivery
    envelope = {
        "message_id": msg_id,
        "from_agent_id": str(agent["id"]),
        "from_agent_name": agent["name"],
        "to_agent_id": req.to_agent_id,
        "channel": req.channel,
        "subject": req.subject,
        "content": req.content,
        "message_type": req.message_type,
        "priority": req.priority,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Push to inbox list (polling mode)
    await redis_client.lpush(f"a2a:inbox:{req.to_agent_id}", json.dumps(envelope))
    await redis_client.expire(f"a2a:inbox:{req.to_agent_id}", A2A_INBOX_TTL)
    # Publish for SSE subscribers
    await redis_client.publish(f"a2a:stream:{req.to_agent_id}", json.dumps(envelope))

    logger.info("Message sent", msg_id=msg_id, from_=agent["name"], to=req.to_agent_id)
    return {"message_id": msg_id, "status": "delivered"}


@app.get("/a2a/inbox/{agent_id}")
async def get_inbox(
    agent_id: str,
    limit: int = Query(20, le=100),
    unread_only: bool = Query(True),
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Get messages from the inbox. Drains the Redis list first, then queries Postgres."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot read another agent's inbox")
    if not db_pool or not redis_client:
        raise HTTPException(503, "Database or Redis unavailable")

    # Drain Redis inbox (fast path for real-time messages)
    messages = []
    while len(messages) < limit:
        raw = await redis_client.rpop(f"a2a:inbox:{agent_id}")
        if not raw:
            break
        messages.append(json.loads(raw))

    # If we need more, query Postgres
    if len(messages) < limit:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, from_agent_id, from_agent_name, channel, subject,
                       content, message_type, priority, is_read, created_at
                FROM agent_messages
                WHERE to_agent_id=$1 AND ($2=FALSE OR is_read=FALSE)
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY priority DESC, created_at ASC
                LIMIT $3
                """,
                agent_id, unread_only, limit - len(messages),
            )
            for r in rows:
                messages.append({
                    "message_id": str(r["id"]),
                    "from_agent_id": r["from_agent_id"],
                    "from_agent_name": r["from_agent_name"],
                    "channel": r["channel"],
                    "subject": r["subject"],
                    "content": json.loads(r["content"]) if isinstance(r["content"], str) else r["content"],
                    "message_type": r["message_type"],
                    "priority": r["priority"],
                    "is_read": r["is_read"],
                    "created_at": r["created_at"].isoformat(),
                })

    return {"agent_id": agent_id, "messages": messages, "count": len(messages)}


@app.delete("/a2a/inbox/{agent_id}/{message_id}")
async def ack_message(agent_id: str, message_id: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Acknowledge (mark as read) or delete a message."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot modify another agent's inbox")
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent_messages SET is_read=TRUE, read_at=NOW() WHERE id=$1 AND to_agent_id=$2",
            message_id, agent_id,
        )
    return {"message_id": message_id, "status": "acknowledged"}


@app.post("/a2a/broadcast/{channel}")
async def broadcast(channel: str, req: BroadcastRequest, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Broadcast a message to all subscribers of a channel."""
    if not redis_client:
        raise HTTPException(503, "Redis unavailable")
    envelope = {
        "from_agent_id": str(agent["id"]),
        "from_agent_name": agent["name"],
        "channel": channel,
        "content": req.content,
        "message_type": req.message_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    recipients = await redis_client.publish(f"a2a:broadcast:{channel}", json.dumps(envelope))
    return {"channel": channel, "recipients": recipients}


@app.get("/a2a/stream/{agent_id}")
async def stream_inbox(agent_id: str, agent: dict = Depends(auth_agent)) -> StreamingResponse:
    """Server-Sent Events stream for real-time message delivery."""
    if str(agent["id"]) != agent_id:
        raise HTTPException(403, "Cannot stream another agent's inbox")
    if not redis_client:
        raise HTTPException(503, "Redis unavailable")

    async def event_generator() -> AsyncIterator[str]:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"a2a:stream:{agent_id}")
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe(f"a2a:stream:{agent_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════
# SESSIONS — /sessions/*
# Persistent working sessions with state + history
# ═══════════════════════════════════════════════════════════════

@app.post("/sessions", status_code=201)
async def create_session(req: CreateSessionRequest, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Create a new agent session with persistent state."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    session_id = req.session_id or f"sess_{str(uuid.uuid4())[:8]}"
    agent_id = str(agent["id"])
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_sessions (id, agent_id, name, purpose, state, context)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (id) DO UPDATE SET
                updated_at=NOW(), is_active=TRUE
            """,
            session_id, agent_id, req.name, req.purpose,
            json.dumps(req.initial_state), json.dumps(req.context),
        )
    return {"session_id": session_id, "agent_id": agent_id}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Get session state."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agent_sessions WHERE id=$1 AND agent_id=$2",
            session_id, str(agent["id"]),
        )
        if not row:
            raise HTTPException(404, "Session not found")
        return {
            "session_id": row["id"],
            "agent_id": str(row["agent_id"]),
            "name": row["name"],
            "purpose": row["purpose"],
            "state": _parse_json(row["state"]),
            "context": _parse_json(row["context"]),
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }


@app.put("/sessions/{session_id}")
async def update_session(
    session_id: str, req: UpdateSessionRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Update session state or metadata."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM agent_sessions WHERE id=$1 AND agent_id=$2",
            session_id, str(agent["id"]),
        )
        if not row:
            raise HTTPException(404, "Session not found")
        if req.state is not None:
            await conn.execute(
                "UPDATE agent_sessions SET state=$1, updated_at=NOW() WHERE id=$2",
                json.dumps(req.state), session_id,
            )
        if req.name is not None:
            await conn.execute("UPDATE agent_sessions SET name=$1 WHERE id=$2", req.name, session_id)
        if req.purpose is not None:
            await conn.execute("UPDATE agent_sessions SET purpose=$1 WHERE id=$2", req.purpose, session_id)
        if req.context is not None:
            await conn.execute(
                "UPDATE agent_sessions SET context=$1 WHERE id=$2",
                json.dumps(req.context), session_id,
            )
    return {"session_id": session_id, "updated": True}


@app.post("/sessions/{session_id}/history")
async def append_history(
    session_id: str, req: HistoryAppendRequest,
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Append a message to session conversation history."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT history FROM agent_sessions WHERE id=$1 AND agent_id=$2",
            session_id, str(agent["id"]),
        )
        if not row:
            raise HTTPException(404, "Session not found")
        history = _parse_json(row["history"])
        if not isinstance(history, list):
            history = []
        history.append({
            "role": req.role,
            "content": req.content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **req.metadata,
        })
        await conn.execute(
            "UPDATE agent_sessions SET history=$1, updated_at=NOW() WHERE id=$2",
            json.dumps(history), session_id,
        )
    return {"session_id": session_id, "history_length": len(history)}


@app.get("/sessions/{session_id}/history")
async def get_history(
    session_id: str,
    limit: int = Query(50, le=500),
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """Get conversation history for a session."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT history FROM agent_sessions WHERE id=$1 AND agent_id=$2",
            session_id, str(agent["id"]),
        )
        if not row:
            raise HTTPException(404, "Session not found")
        history = _parse_json(row["history"])
        if not isinstance(history, list):
            history = []
        return {
            "session_id": session_id,
            "history": history[-limit:],
            "total_turns": len(history),
        }


@app.delete("/sessions/{session_id}")
async def end_session(session_id: str, agent: dict = Depends(auth_agent)) -> dict[str, Any]:
    """Mark a session as ended."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent_sessions SET is_active=FALSE, ended_at=NOW() WHERE id=$1 AND agent_id=$2",
            session_id, str(agent["id"]),
        )
    return {"session_id": session_id, "status": "ended"}


@app.get("/sessions")
async def list_sessions(
    active_only: bool = Query(True),
    agent: dict = Depends(auth_agent),
) -> dict[str, Any]:
    """List all sessions for this agent."""
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, purpose, is_active, created_at, updated_at
            FROM agent_sessions
            WHERE agent_id=$1 AND ($2=FALSE OR is_active=TRUE)
            ORDER BY updated_at DESC LIMIT 100
            """,
            str(agent["id"]), active_only,
        )
        return {
            "sessions": [
                {
                    "session_id": r["id"],
                    "name": r["name"],
                    "purpose": r["purpose"],
                    "is_active": r["is_active"],
                    "created_at": r["created_at"].isoformat(),
                    "updated_at": r["updated_at"].isoformat(),
                }
                for r in rows
            ]
        }


def _parse_json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


# ═══════════════════════════════════════════════════════════════
# FRAMEWORK ADAPTER ENDPOINTS
# These let any agent framework consume TradingOS without MCP
# ═══════════════════════════════════════════════════════════════

@app.get("/adapters/openai-tools")
async def openai_tools_spec() -> dict[str, Any]:
    """
    Returns all TradingOS tools in OpenAI function calling format.
    Use with any OpenAI-compatible agent framework (LangChain, AutoGen, etc.)
    """
    tools = _get_openai_tool_specs()
    return {"tools": tools, "count": len(tools)}


@app.get("/adapters/langchain-tools")
async def langchain_tools_spec() -> dict[str, Any]:
    """
    Returns tool specs in LangChain StructuredTool format.
    Import and wrap these with BaseTool in your LangChain agent.
    """
    tools = _get_openai_tool_specs()
    lc_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "args_schema": t["function"]["parameters"],
            "mcp_endpoint": "http://agent-hub:7704",
            "mcp_tool": t["function"]["name"],
        }
        for t in tools
    ]
    return {
        "tools": lc_tools,
        "integration": "Use TradingOSToolkit from tradingos-langchain-adapter",
        "endpoint": "http://agent-hub:7704",
    }


@app.get("/adapters/openapi")
async def openapi_spec() -> dict[str, Any]:
    """Returns the full OpenAPI 3.0 spec for this service."""
    return app.openapi()


def _get_openai_tool_specs() -> list[dict[str, Any]]:
    """Returns agent-hub endpoints in OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": "register_agent",
                "description": "Register a new agent account on TradingOS. Returns a persistent API key.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Agent's display name"},
                        "framework": {"type": "string", "description": "Agent framework: langchain, autogen, crewai, custom"},
                        "description": {"type": "string"},
                        "skills": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_working_set",
                "description": "Store a value in working (ephemeral) memory. Auto-expires after TTL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "key": {"type": "string"},
                        "value": {"description": "Any JSON-serializable value"},
                        "ttl": {"type": "integer", "description": "TTL in seconds"},
                    },
                    "required": ["agent_id", "key", "value"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_remember",
                "description": "Store a long-term memory that can be recalled semantically later.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "content": {"type": "string", "description": "Text to remember"},
                        "importance": {"type": "number", "minimum": 0, "maximum": 1},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["agent_id", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_recall",
                "description": "Semantically search long-term memories by natural language query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["agent_id", "query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "a2a_send",
                "description": "Send a message to another registered agent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to_agent_id": {"type": "string"},
                        "content": {"type": "object"},
                        "subject": {"type": "string"},
                        "message_type": {"type": "string", "enum": ["message", "task", "notification", "response"]},
                    },
                    "required": ["to_agent_id", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "a2a_inbox",
                "description": "Check this agent's message inbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "session_create",
                "description": "Create a new persistent agent session with state and conversation history.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "purpose": {"type": "string"},
                        "context": {"type": "object"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "session_history_append",
                "description": "Append a message to a session's conversation history.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "role": {"type": "string", "enum": ["user", "assistant", "system", "tool"]},
                        "content": {"type": "string"},
                    },
                    "required": ["session_id", "role", "content"],
                },
            },
        },
    ]


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False, log_level="info")
