-- TradingOS PostgreSQL Schema
-- Initializes all tables on first startup

-- ═══════════════════════════════════════════════════════════════
-- AGENT REGISTRY
-- Any external agent (any framework) registers here
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    agent_type      TEXT NOT NULL DEFAULT 'external',
    framework       TEXT,                          -- 'langchain', 'autogen', 'crewai', 'hermes', 'custom', etc.
    description     TEXT DEFAULT '',
    skills          TEXT[]   DEFAULT '{}',
    api_key_hash    TEXT UNIQUE NOT NULL,          -- SHA-256 of raw key (never stored raw)
    api_key_prefix  TEXT NOT NULL,                 -- First 12 chars for display
    capabilities    JSONB    DEFAULT '{}',         -- Arbitrary agent capabilities declaration
    metadata        JSONB    DEFAULT '{}',         -- Framework-specific metadata
    llm_config      JSONB    DEFAULT '{}',         -- Agent's LLM configuration
    reputation      DOUBLE PRECISION DEFAULT 0.8,
    total_interactions INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_agents_framework ON agents(framework);
CREATE INDEX IF NOT EXISTS idx_agents_active    ON agents(is_active, last_seen_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- EPISODIC MEMORY
-- Timestamped event log — what the agent did, saw, decided
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_episodes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id  TEXT,
    event_type  TEXT NOT NULL,                     -- 'signal_analyzed', 'vote_cast', 'trade_opened', etc.
    content     JSONB NOT NULL,                    -- Full event payload
    outcome     TEXT DEFAULT 'pending',            -- 'success', 'failure', 'pending', 'skipped'
    importance  DOUBLE PRECISION DEFAULT 0.5,      -- 0.0-1.0 — used for memory pruning
    tags        TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodes_agent   ON agent_episodes(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON agent_episodes(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_type    ON agent_episodes(agent_id, event_type);

-- ═══════════════════════════════════════════════════════════════
-- KNOWLEDGE BASE
-- Structured facts and beliefs the agent has learned
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_knowledge (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    category    TEXT DEFAULT 'general',
    confidence  DOUBLE PRECISION DEFAULT 1.0,      -- Agent's confidence in this fact
    source      TEXT,                              -- Where this knowledge came from
    expires_at  TIMESTAMPTZ,                       -- NULL = never expires
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agent_id, key)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_agent    ON agent_knowledge(agent_id, key);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON agent_knowledge(agent_id, category);

-- ═══════════════════════════════════════════════════════════════
-- SESSIONS
-- Agent working sessions with persistent state and history
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_sessions (
    id          TEXT PRIMARY KEY,                  -- Client-provided or auto-generated
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    name        TEXT,
    purpose     TEXT,
    state       JSONB DEFAULT '{}',                -- Arbitrary mutable session state
    history     JSONB DEFAULT '[]',                -- Conversation / action history
    context     JSONB DEFAULT '{}',                -- Pinned context (system prompt, etc.)
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    is_active   BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent  ON agent_sessions(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON agent_sessions(agent_id, is_active);

-- ═══════════════════════════════════════════════════════════════
-- A2A MESSAGES
-- Persistent store for agent-to-agent messages
-- Redis is the primary inbox; this is the durable fallback
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_agent_id   TEXT NOT NULL,                 -- Sender (may not be in registry)
    from_agent_name TEXT DEFAULT 'unknown',
    to_agent_id     UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    channel         TEXT DEFAULT 'direct',
    subject         TEXT,
    content         JSONB NOT NULL,
    message_type    TEXT DEFAULT 'message',        -- 'message', 'notification', 'task', 'response', 'broadcast'
    priority        INTEGER DEFAULT 5,             -- 1 (low) to 10 (critical)
    reply_to_id     UUID,                          -- Thread support
    is_read         BOOLEAN DEFAULT FALSE,
    read_at         TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_inbox  ON agent_messages(to_agent_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_from   ON agent_messages(from_agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON agent_messages(reply_to_id);

-- ═══════════════════════════════════════════════════════════════
-- TRADING-SPECIFIC TABLES (used by core system)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS signal_outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID NOT NULL,
    pnl_pct         DOUBLE PRECISION NOT NULL,
    duration_hours  DOUBLE PRECISION NOT NULL,
    exit_reason     TEXT NOT NULL,
    notes           TEXT,
    recorded_by     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outcomes_signal ON signal_outcomes(signal_id);
