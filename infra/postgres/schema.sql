-- TradingOS Core Schema

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "timescaledb";

-- Users & Workspaces
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    tier TEXT DEFAULT 'free',
    stripe_customer_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    settings_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agents
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    runtime TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT DEFAULT 'idle',
    profile_json JSONB DEFAULT '{}',
    memory_namespace TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Kanban System (Event Sourced)
CREATE TABLE IF NOT EXISTS kanban_cards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    state TEXT NOT NULL,
    context_json JSONB DEFAULT '{}',
    risk_rating INTEGER,
    rug_score INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kanban_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    card_id UUID REFERENCES kanban_cards(id) ON DELETE CASCADE,
    from_state TEXT,
    to_state TEXT NOT NULL,
    triggered_by_agent_id UUID REFERENCES agents(id),
    payload_json JSONB DEFAULT '{}',
    event_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategies & Backtests
CREATE TABLE IF NOT EXISTS strategies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    params_json JSONB DEFAULT '{}',
    indicators_json JSONB DEFAULT '{}',
    git_commit_sha TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID REFERENCES strategies(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    sharpe NUMERIC,
    sortino NUMERIC,
    max_drawdown NUMERIC,
    profit_factor NUMERIC,
    win_rate NUMERIC,
    total_trades INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Trades & Auditing
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    strategy_id UUID REFERENCES strategies(id),
    agent_id UUID REFERENCES agents(id),
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    entry_price NUMERIC,
    exit_price NUMERIC,
    stop_loss NUMERIC,
    take_profit NUMERIC,
    pnl NUMERIC,
    audit_hash TEXT NOT NULL,
    reason_json JSONB DEFAULT '{}',
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id),
    action TEXT NOT NULL,
    payload_json JSONB DEFAULT '{}',
    event_hash TEXT NOT NULL,
    prev_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Time-series (TimescaleDB)
CREATE TABLE IF NOT EXISTS ohlcv_ticks (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL
);

SELECT create_hypertable('ohlcv_ticks', 'time', if_not_exists => TRUE);
-- Set retention policy for OHLCV ticks: 30 days
SELECT add_retention_policy('ohlcv_ticks', INTERVAL '30 days', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS sentiment_signals (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    score INTEGER NOT NULL,
    raw_text TEXT,
    expires_at TIMESTAMPTZ
);

SELECT create_hypertable('sentiment_signals', 'time', if_not_exists => TRUE);
-- Set retention policy for sentiment signals: 7 days (high velocity)
SELECT add_retention_policy('sentiment_signals', INTERVAL '7 days', if_not_exists => TRUE);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_kanban_cards_state ON kanban_cards(state);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_audit_log_hash ON audit_log(event_hash);

-- Row Level Security (Basic)
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE kanban_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Policies (Example: users can only see their own workspace data)
-- Assuming workspace_id is present in all tables
CREATE POLICY workspace_isolation_policy ON workspaces FOR ALL TO PUBLIC USING (user_id = current_setting('app.current_user_id')::uuid);
