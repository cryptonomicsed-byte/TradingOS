use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

// ═══════════════════════════════════════════════════════════════
// SIGNAL GENOME — The DNA of every trading signal
// ═══════════════════════════════════════════════════════════════

/// The fundamental unit of the TradingOS system.
/// Every signal carries its full provenance, fitness score,
/// and challenge history — making signals first-class citizens.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalGenome {
    pub id: Uuid,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,

    /// What asset this signal concerns
    pub asset: AssetId,

    /// Signal direction and strength
    pub signal_type: SignalType,

    /// Current conviction score (0.0 - 1.0), updated by Parliament
    pub conviction: f64,

    /// The DNA strand — provenance and lineage
    pub dna: SignalDNA,

    /// Fitness score — evolves from historical outcome feedback
    pub fitness: f64,

    /// Temporal embedding for similarity search in Memory Courts
    pub temporal_embedding: Option<Vec<f32>>,

    /// All challenges this signal has faced
    pub challenge_history: Vec<ChallengeResult>,

    /// Parliament voting record
    pub parliament_record: Option<ParliamentRecord>,

    /// Current state in the pipeline
    pub state: SignalState,

    /// Raw market context at signal creation
    pub market_context: MarketContext,

    /// Metadata for plugin strategies
    pub indicators: HashMap<String, f64>,

    /// Tags for categorization and filtering
    pub tags: Vec<String>,
}

impl SignalGenome {
    pub fn new(asset: AssetId, signal_type: SignalType, source: SignalSource) -> Self {
        let now = Utc::now();
        Self {
            id: Uuid::new_v4(),
            created_at: now,
            updated_at: now,
            asset,
            signal_type,
            conviction: 0.0,
            dna: SignalDNA::new(source),
            fitness: 0.5, // Neutral starting fitness
            temporal_embedding: None,
            challenge_history: Vec::new(),
            parliament_record: None,
            state: SignalState::Spawned,
            market_context: MarketContext::default(),
            indicators: HashMap::new(),
            tags: Vec::new(),
        }
    }

    pub fn get_indicator(&self, name: &str) -> f64 {
        *self.indicators.get(name).unwrap_or(&0.0)
    }

    pub fn survived_challenge(&self) -> bool {
        self.challenge_history
            .iter()
            .all(|c| c.outcome == ChallengeOutcome::SignalSurvived)
    }

    pub fn parliament_approved(&self) -> bool {
        self.parliament_record
            .as_ref()
            .map(|r| r.approved)
            .unwrap_or(false)
    }

    pub fn effective_conviction(&self) -> f64 {
        self.conviction * self.fitness.sqrt()
    }
}

/// Unique identifier for a trading asset
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct AssetId {
    pub symbol: String,
    pub chain: Chain,
    pub address: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum Chain {
    Solana,
    Ethereum,
    Base,
    Arbitrum,
    BNBChain,
    CEX(String), // e.g., "okx", "binance"
}

/// The direction and type of a trading signal
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SignalType {
    Long {
        target_pct: f64,
        timeframe_hours: f64,
    },
    Short {
        target_pct: f64,
        timeframe_hours: f64,
    },
    Hold,
    Exit {
        urgency: ExitUrgency,
    },
    Accumulate {
        dca_levels: Vec<f64>,
    },
    Alert {
        message: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExitUrgency {
    Immediate,
    OnNextPump,
    Gradual,
}

// ═══════════════════════════════════════════════════════════════
// SIGNAL DNA — Provenance and lineage
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalDNA {
    /// Primary source that spawned this signal
    pub primary_source: SignalSource,

    /// All sources that corroborated this signal
    pub corroborating_sources: Vec<SignalSource>,

    /// Agent lineage — which agents touched this signal and what they contributed
    pub agent_lineage: Vec<AgentContribution>,

    /// Parent signal ID if this was derived from another signal
    pub parent_id: Option<Uuid>,

    /// Generation number (0 = original, higher = derived)
    pub generation: u32,

    /// How conviction evolved over the signal's lifetime
    pub conviction_evolution: Vec<ConvictionPoint>,
}

impl SignalDNA {
    pub fn new(source: SignalSource) -> Self {
        Self {
            primary_source: source,
            corroborating_sources: Vec::new(),
            agent_lineage: Vec::new(),
            parent_id: None,
            generation: 0,
            conviction_evolution: Vec::new(),
        }
    }

    pub fn add_agent_contribution(&mut self, contribution: AgentContribution) {
        self.conviction_evolution.push(ConvictionPoint {
            timestamp: Utc::now(),
            value: contribution.conviction_delta,
            agent_id: contribution.agent_id.clone(),
            reason: contribution.reason.clone(),
        });
        self.agent_lineage.push(contribution);
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentContribution {
    pub agent_id: String,
    pub agent_type: AgentType,
    pub timestamp: DateTime<Utc>,
    pub conviction_delta: f64,
    pub reason: String,
    pub confidence: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum AgentType {
    SignalSpawner,
    Challenger,
    MemoryCourt,
    Validator,
    ParliamentVoter,
    ExecutionSenate,
    StrategyPlugin(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConvictionPoint {
    pub timestamp: DateTime<Utc>,
    pub value: f64,
    pub agent_id: String,
    pub reason: String,
}

/// Sources that can generate or corroborate signals
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SignalSource {
    OnChain {
        metric: String,
        value: f64,
    },
    Social {
        platform: String,
        account: String,
        sentiment_score: f64,
    },
    WhaleMover {
        wallet_address: String,
        reputation_score: f64,
        trade_size_usd: f64,
    },
    DexFlow {
        pair: String,
        volume_surge_pct: f64,
    },
    MacroCorrelation {
        indicator: String,
        correlation: f64,
    },
    Narrative {
        theme: String,
        momentum: f64,
    },
    StrategyPlugin {
        plugin_name: String,
        version: String,
    },
    MemoryRecall {
        similar_signal_id: Uuid,
        similarity_score: f64,
        historical_outcome: f64,
    },
}

// ═══════════════════════════════════════════════════════════════
// CHALLENGE SYSTEM — Adversarial validation
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChallengeResult {
    pub id: Uuid,
    pub challenger_id: String,
    pub timestamp: DateTime<Utc>,
    pub challenge_type: ChallengeType,
    pub arguments: Vec<String>,
    pub counter_evidence: Vec<String>,
    pub outcome: ChallengeOutcome,
    pub conviction_impact: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ChallengeType {
    LiquidityRisk,
    ContractSecurity,
    MarketManipulation,
    MacroHeadwind,
    SentimentContrarian,
    HistoricalCounterPattern,
    MevRisk,
    Timing,
    PositionSizing,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ChallengeOutcome {
    SignalSurvived,
    SignalKilled,
    ConvictionReduced,
    ConvictionIncreased, // Challenge backfired
}

// ═══════════════════════════════════════════════════════════════
// PARLIAMENT — Voting and consensus
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParliamentRecord {
    pub session_id: Uuid,
    pub started_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    pub votes: Vec<ParliamentVote>,
    pub quorum_reached: bool,
    pub approved: bool,
    pub final_conviction: f64,
    pub execution_recommendation: Option<ExecutionRecommendation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParliamentVote {
    pub voter_id: String,
    pub voter_type: AgentType,
    pub vote: Vote,
    pub conviction: f64,
    pub rationale: String,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Vote {
    Approve,
    Reject,
    Abstain,
    RequestMoreData(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionRecommendation {
    pub position_size_pct: f64,
    pub max_slippage: f64,
    pub entry_strategy: EntryStrategy,
    pub exit_plan: ExitPlan,
    pub priority_fee_lamports: Option<u64>,
    pub use_jito_bundle: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EntryStrategy {
    MarketOrder,
    LimitOrder { price_pct_below_market: f64 },
    DCA { tranches: u32, interval_minutes: u32 },
    TWAP { duration_minutes: u32 },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExitPlan {
    pub hard_stop_pct: f64,
    pub take_profit_targets: Vec<TakeProfitLevel>,
    pub trailing_stop_pct: Option<f64>,
    pub max_hold_hours: f64,
    pub time_stop: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TakeProfitLevel {
    pub pct_gain: f64,
    pub position_pct_to_exit: f64,
}

// ═══════════════════════════════════════════════════════════════
// SIGNAL STATE MACHINE
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum SignalState {
    /// Just created by a spawner agent
    Spawned,
    /// Being challenged by adversarial agents
    UnderChallenge,
    /// Challenge passed, submitted to parliament
    InParliament,
    /// Parliament approved, queued for execution
    Approved,
    /// Execution rejected (conviction too low, risk too high)
    Rejected,
    /// Currently being executed
    Executing,
    /// Trade open, monitoring for exit signals
    Active,
    /// Position closed, outcome recorded
    Completed { pnl_pct: f64 },
    /// Signal expired before execution
    Expired,
}

// ═══════════════════════════════════════════════════════════════
// MARKET CONTEXT
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MarketContext {
    pub price_usd: Option<f64>,
    pub volume_24h_usd: Option<f64>,
    pub market_cap_usd: Option<f64>,
    pub liquidity_usd: Option<f64>,
    pub price_change_1h: Option<f64>,
    pub price_change_24h: Option<f64>,
    pub btc_dominance: Option<f64>,
    pub fear_greed_index: Option<u8>,
    pub gas_price_gwei: Option<f64>,
    pub sol_tps: Option<f64>,
    pub mempool_congestion: Option<f64>,
}

// ═══════════════════════════════════════════════════════════════
// PLUGIN SYSTEM TYPES
// ═══════════════════════════════════════════════════════════════

/// Vote from a WASM strategy plugin
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyVote {
    pub direction: StrategyDirection,
    pub confidence: f64,
    pub reasoning: String,
    pub suggested_indicators: HashMap<String, f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum StrategyDirection {
    Bullish,
    Bearish,
    Neutral,
}

impl StrategyVote {
    pub fn bullish(confidence: f64, reasoning: &str) -> Self {
        Self {
            direction: StrategyDirection::Bullish,
            confidence,
            reasoning: reasoning.to_string(),
            suggested_indicators: HashMap::new(),
        }
    }

    pub fn bearish(confidence: f64, reasoning: &str) -> Self {
        Self {
            direction: StrategyDirection::Bearish,
            confidence,
            reasoning: reasoning.to_string(),
            suggested_indicators: HashMap::new(),
        }
    }

    pub fn neutral(reasoning: &str) -> Self {
        Self {
            direction: StrategyDirection::Neutral,
            confidence: 0.0,
            reasoning: reasoning.to_string(),
            suggested_indicators: HashMap::new(),
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// BUS MESSAGES
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BusMessage {
    SignalCreated(SignalGenome),
    SignalUpdated { id: Uuid, updates: SignalUpdate },
    SignalStateChanged { id: Uuid, new_state: SignalState },
    ChallengeReceived { signal_id: Uuid, challenge: ChallengeResult },
    VoteReceived { signal_id: Uuid, vote: ParliamentVote },
    ParliamentDecision { signal_id: Uuid, record: ParliamentRecord },
    PluginLoaded { name: String, version: String },
    PluginUnloaded { name: String },
    AgentRegistered { agent_id: String, agent_type: AgentType },
    AgentDeregistered { agent_id: String },
    SystemMetric { name: String, value: f64 },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalUpdate {
    pub conviction: Option<f64>,
    pub fitness: Option<f64>,
    pub temporal_embedding: Option<Vec<f32>>,
    pub indicators: Option<HashMap<String, f64>>,
    pub tags: Option<Vec<String>>,
}
