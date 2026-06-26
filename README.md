# TradingOS — Agent-Native Trading Intelligence Platform

> An Operating System for Trading Signals where AI agents are first-class citizens, not afterthoughts.

---

## The Core Insight

Every existing trading system is **human-first with AI bolted on**. TradingOS inverts this:

```
Traditional:  Data → Rules → Signal → Human Decision → Trade
TradingOS:    Signal Genome → Agent Parliament → Consensus → Autonomous Execution
```

Signals have **DNA** (provenance, fitness, lineage). Agents **debate** before execution. The system **evolves** through outcome feedback. Everything is a **discoverable MCP tool**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TradingOS Kernel                            │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────┐  │
│  │  Signal Bus  │    │  Agent Parliament │    │  Memory Courts  │  │
│  │   (Rust)     │───▶│    (Elixir OTP)  │───▶│   (Rust+Vec)   │  │
│  │              │    │                  │    │                 │  │
│  │ • Genome     │    │ • Spawner Agents │    │ • Episodic mem  │  │
│  │ • Routing    │    │ • Challengers    │    │ • Pattern DB    │  │
│  │ • WASM Bus   │    │ • Validators     │    │ • Outcome index │  │
│  │ • Sandbox    │    │ • Senate         │    │ • Temporal emb  │  │
│  └──────────────┘    └──────────────────┘    └─────────────────┘  │
│          │                    │                        │            │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Intelligence Layer (Python + Claude)             │  │
│  │  SignalSpawner │ ChallengerAgent │ MemoryCourt │ ExecSenate   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│          │                    │                        │            │
│  ┌───────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │  API Gateway  │  │   MCP Server    │  │   Quant Engine      │  │
│  │    (Go)       │  │  (TypeScript)   │  │     (Julia)         │  │
│  │ • REST API    │  │ • 40+ tools     │  │ • Backtesting       │  │
│  │ • WebSocket   │  │ • Agent disco   │  │ • ML models         │  │
│  │ • gRPC proxy  │  │ • Hot-swap      │  │ • Optimization      │  │
│  └───────────────┘  └─────────────────┘  └─────────────────────┘  │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Dashboard (Next.js 15 + WebGPU)                  │  │
│  │  Parliament Viz │ Signal DNA │ Agent Health │ Conviction Flow  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Core Innovations

### 1. Signal Genome
Every signal carries a DNA strand — not just data, but provenance:
```
SignalGenome {
  id: UUID,
  dna: { source_chain, agent_lineage, confidence_evolution },
  fitness: f64,           // evolves from outcome feedback
  temporal_embedding: Vec<f64>,  // similarity search
  challenge_history: Vec<ChallengeResult>,
  parliament_votes: ParliamentRecord,
}
```

### 2. Agent Parliament (Elixir OTP)
Signals go through a democratic process before execution:
- **Spawner Agents** — Generate typed signals from data sources
- **Challenger Agents** — Devil's advocates that try to invalidate signals
- **Memory Court Agents** — Recall similar historical patterns
- **Validator Agents** — Cross-reference corroboration
- **Execution Senate** — Final committee with MEV + risk + timing agents

### 3. Adversarial Validation
Every signal automatically spawns a Challenger that argues against it, ensuring only signals that survive scrutiny advance.

### 4. Temporal Memory Courts
Agents search vector embeddings of historical signals to recall how similar setups performed — building genuine market intuition.

### 5. Agent Evolution
Agents accumulate reputation scores based on prediction accuracy. High-reputation agents get more voting weight. Low-accuracy agents are retrained or replaced.

### 6. WASM Plugin System
Strategies are compiled to WASM and hot-swapped into the signal bus sandbox without system restart.

### 7. MCP-First Design
Every capability — signals, agents, portfolios, market data — is exposed as an MCP tool, making TradingOS natively consumable by any AI agent.

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Signal Bus | **Rust** | Lock-free channels, WASM sandbox, zero-copy |
| Agent Runtime | **Elixir/OTP** | Million concurrent processes, fault isolation |
| Intelligence | **Python + Claude** | LLM orchestration, rapid agent development |
| Quant Engine | **Julia** | Native numerical computing, ML, optimization |
| API Gateway | **Go** | Goroutine-per-connection, low-latency HTTP/WS |
| MCP Server | **TypeScript** | Tool definition, agent discovery protocol |
| Dashboard | **Next.js 15** | React Server Components, WebGPU shaders |
| Memory Store | **Rust + LMDB** | Persistent agent memory, vector search |
| Agent Comms | **Elixir Phoenix** | PubSub, A2A messaging, channels |
| Service Mesh | **gRPC + Protobuf** | Typed contracts between services |

---

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your API keys

# 2. Launch everything
make up

# 3. Open dashboard
open http://localhost:3000

# 4. Connect your AI agent to MCP
# Add to Claude Desktop / any MCP client:
# npx tradingos-mcp http://localhost:4000/mcp
```

---

## Agent-Native Usage

TradingOS is designed to be operated BY agents, not just for human traders:

```python
# Your agent can do this:
from tradingos import TradingOSClient

client = TradingOSClient(mcp_url="http://localhost:4000/mcp")

# Discover what signals are live
signals = await client.tools.get_live_signals(min_conviction=0.8)

# Ask the parliament to evaluate a specific token
evaluation = await client.tools.parliament_evaluate(
    token="SOL",
    context="Macro conditions favorable, whale accumulation detected"
)

# Get memory court recollection
memory = await client.tools.memory_court_recall(
    signal_pattern=evaluation.signal_pattern,
    lookback_days=90
)

# Submit to execution senate
if evaluation.consensus_score > 0.85 and memory.historical_win_rate > 0.65:
    await client.tools.execution_senate_submit(
        signal=evaluation,
        size_pct=0.02,  # 2% of portfolio
        max_slippage=0.005
    )
```

---

## Plugin Development

Write strategies as WASM modules — hot-swappable without downtime:

```rust
// plugins/strategies/my_strategy/src/lib.rs
use tradingos_sdk::*;

#[tradingos::strategy]
pub fn evaluate(signal: &SignalGenome, ctx: &MarketContext) -> StrategyVote {
    let momentum = signal.get_indicator("rsi_14");
    let volume_surge = ctx.volume_ratio > 2.5;
    
    if momentum > 65.0 && volume_surge {
        StrategyVote::bullish(0.78, "RSI momentum + volume confirmation")
    } else {
        StrategyVote::neutral("Conditions not met")
    }
}
```

Deploy: `make plugin-deploy name=my_strategy` — live in seconds.

---

## Directory Structure

```
TradingOS/
├── packages/
│   ├── signal-bus/        # Rust — Core signal routing + WASM sandbox
│   ├── agent-runtime/     # Elixir — OTP agent lifecycle + Parliament
│   ├── intelligence/      # Python — Claude-powered agent implementations
│   ├── mcp-server/        # TypeScript — MCP tool server (40+ tools)
│   ├── dashboard/         # TypeScript/Next.js — Real-time UI
│   ├── api-gateway/       # Go — HTTP/WebSocket gateway
│   └── quant-engine/      # Julia — Backtesting + ML optimization
├── agents/                # Agent definitions and configurations
├── plugins/               # WASM strategy plugins
├── protos/                # Protocol Buffer definitions
└── config/                # Environment configs
```

---

## License

MIT — Build freely, disrupt responsibly.
