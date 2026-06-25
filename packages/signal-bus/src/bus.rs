use crate::types::*;
use dashmap::DashMap;
use std::sync::Arc;
use tokio::sync::{broadcast, mpsc, RwLock};
use tracing::{debug, error, info, warn};
use uuid::Uuid;
use std::collections::HashMap;

const BUS_CHANNEL_CAPACITY: usize = 10_000;
const SIGNAL_TTL_SECS: i64 = 3600; // 1 hour max signal lifetime

// ═══════════════════════════════════════════════════════════════
// SIGNAL BUS — Core routing engine
// ═══════════════════════════════════════════════════════════════

/// The TradingOS Signal Bus routes signals through the full
/// parliament pipeline, maintaining state and broadcasting
/// events to all interested subscribers.
pub struct SignalBus {
    /// Active signals, keyed by ID
    signals: Arc<DashMap<Uuid, SignalGenome>>,

    /// Broadcast channel — every subscriber sees all messages
    broadcast_tx: broadcast::Sender<BusMessage>,

    /// Internal command channel for serialized mutations
    cmd_tx: mpsc::Sender<BusCommand>,

    /// Registered plugin evaluators
    plugins: Arc<RwLock<HashMap<String, Box<dyn PluginEvaluator>>>>,

    /// Signal routing table — which agents handle which signal types
    routing_table: Arc<RwLock<RoutingTable>>,

    /// Bus configuration
    config: BusConfig,
}

pub struct BusConfig {
    pub conviction_threshold: f64,
    pub parliament_quorum: f64,
    pub parliament_min_votes: usize,
    pub challenger_enabled: bool,
    pub signal_ttl_secs: i64,
}

impl Default for BusConfig {
    fn default() -> Self {
        Self {
            conviction_threshold: 0.75,
            parliament_quorum: 0.67,
            parliament_min_votes: 3,
            challenger_enabled: true,
            signal_ttl_secs: SIGNAL_TTL_SECS,
        }
    }
}

/// Internal command for mutating bus state safely
enum BusCommand {
    InsertSignal(SignalGenome),
    UpdateSignalState { id: Uuid, new_state: SignalState },
    ApplyChallenge { signal_id: Uuid, challenge: ChallengeResult },
    RecordVote { signal_id: Uuid, vote: ParliamentVote },
    FinalizeParliament { signal_id: Uuid, record: ParliamentRecord },
    ExpireOldSignals,
}

/// Trait for WASM plugin evaluators
pub trait PluginEvaluator: Send + Sync {
    fn name(&self) -> &str;
    fn version(&self) -> &str;
    fn evaluate(&self, signal: &SignalGenome) -> StrategyVote;
}

/// Routes messages to specific agent types
pub struct RoutingTable {
    /// agent_type -> list of agent endpoint URLs
    pub routes: HashMap<String, Vec<String>>,
}

impl RoutingTable {
    pub fn new() -> Self {
        Self {
            routes: HashMap::new(),
        }
    }

    pub fn register(&mut self, agent_type: &str, endpoint: &str) {
        self.routes
            .entry(agent_type.to_string())
            .or_default()
            .push(endpoint.to_string());
    }

    pub fn get_endpoints(&self, agent_type: &str) -> Vec<String> {
        self.routes
            .get(agent_type)
            .cloned()
            .unwrap_or_default()
    }
}

impl SignalBus {
    pub fn new(config: BusConfig) -> (Self, broadcast::Receiver<BusMessage>) {
        let (broadcast_tx, broadcast_rx) = broadcast::channel(BUS_CHANNEL_CAPACITY);
        let (cmd_tx, cmd_rx) = mpsc::channel(1000);

        let bus = Self {
            signals: Arc::new(DashMap::new()),
            broadcast_tx,
            cmd_tx,
            plugins: Arc::new(RwLock::new(HashMap::new())),
            routing_table: Arc::new(RwLock::new(RoutingTable::new())),
            config,
        };

        // Spawn command processor
        let signals_ref = bus.signals.clone();
        let broadcast_ref = bus.broadcast_tx.clone();
        tokio::spawn(command_processor(cmd_rx, signals_ref, broadcast_ref));

        (bus, broadcast_rx)
    }

    /// Submit a new signal into the pipeline
    pub async fn submit_signal(&self, signal: SignalGenome) -> Result<Uuid, BusError> {
        let id = signal.id;

        info!(
            signal_id = %id,
            asset = %signal.asset.symbol,
            "Signal submitted to bus"
        );

        self.cmd_tx
            .send(BusCommand::InsertSignal(signal.clone()))
            .await
            .map_err(|_| BusError::ChannelClosed)?;

        // Broadcast creation event
        let _ = self.broadcast_tx.send(BusMessage::SignalCreated(signal));

        Ok(id)
    }

    /// Get a signal by ID
    pub fn get_signal(&self, id: &Uuid) -> Option<SignalGenome> {
        self.signals.get(id).map(|s| s.clone())
    }

    /// Get all signals in a given state
    pub fn get_signals_by_state(&self, state: &SignalState) -> Vec<SignalGenome> {
        self.signals
            .iter()
            .filter(|s| &s.state == state)
            .map(|s| s.clone())
            .collect()
    }

    /// Get all active signals above a conviction threshold
    pub fn get_high_conviction_signals(&self, min_conviction: f64) -> Vec<SignalGenome> {
        self.signals
            .iter()
            .filter(|s| s.effective_conviction() >= min_conviction)
            .map(|s| s.clone())
            .collect()
    }

    /// Apply a challenge result to a signal
    pub async fn apply_challenge(
        &self,
        signal_id: Uuid,
        challenge: ChallengeResult,
    ) -> Result<(), BusError> {
        self.cmd_tx
            .send(BusCommand::ApplyChallenge { signal_id, challenge: challenge.clone() })
            .await
            .map_err(|_| BusError::ChannelClosed)?;

        let _ = self
            .broadcast_tx
            .send(BusMessage::ChallengeReceived { signal_id, challenge });

        Ok(())
    }

    /// Record a parliament vote
    pub async fn record_vote(
        &self,
        signal_id: Uuid,
        vote: ParliamentVote,
    ) -> Result<(), BusError> {
        self.cmd_tx
            .send(BusCommand::RecordVote { signal_id, vote: vote.clone() })
            .await
            .map_err(|_| BusError::ChannelClosed)?;

        let _ = self
            .broadcast_tx
            .send(BusMessage::VoteReceived { signal_id, vote });

        // Check if we can finalize parliament
        self.check_parliament_completion(signal_id).await?;

        Ok(())
    }

    /// Transition signal state
    pub async fn transition_state(
        &self,
        signal_id: Uuid,
        new_state: SignalState,
    ) -> Result<(), BusError> {
        self.cmd_tx
            .send(BusCommand::UpdateSignalState {
                id: signal_id,
                new_state: new_state.clone(),
            })
            .await
            .map_err(|_| BusError::ChannelClosed)?;

        let _ = self.broadcast_tx.send(BusMessage::SignalStateChanged {
            id: signal_id,
            new_state,
        });

        Ok(())
    }

    /// Run all registered WASM plugins against a signal
    pub async fn run_plugins(&self, signal: &SignalGenome) -> Vec<StrategyVote> {
        let plugins = self.plugins.read().await;
        plugins.values().map(|p| p.evaluate(signal)).collect()
    }

    /// Register a new plugin evaluator
    pub async fn register_plugin(&self, plugin: Box<dyn PluginEvaluator>) {
        let name = plugin.name().to_string();
        let version = plugin.version().to_string();
        let mut plugins = self.plugins.write().await;
        plugins.insert(name.clone(), plugin);
        info!(plugin = %name, version = %version, "Plugin registered");
        let _ = self.broadcast_tx.send(BusMessage::PluginLoaded { name, version });
    }

    /// Subscribe to all bus events
    pub fn subscribe(&self) -> broadcast::Receiver<BusMessage> {
        self.broadcast_tx.subscribe()
    }

    /// Get a snapshot of all signals
    pub fn snapshot(&self) -> Vec<SignalGenome> {
        self.signals.iter().map(|s| s.clone()).collect()
    }

    async fn check_parliament_completion(&self, signal_id: Uuid) -> Result<(), BusError> {
        let signal = match self.get_signal(&signal_id) {
            Some(s) => s,
            None => return Ok(()),
        };

        let record = match &signal.parliament_record {
            Some(r) => r,
            None => return Ok(()),
        };

        if record.completed_at.is_some() {
            return Ok(());
        }

        let approve_votes = record.votes.iter().filter(|v| v.vote == Vote::Approve).count();
        let total_votes = record.votes.len();

        if total_votes < self.config.parliament_min_votes {
            return Ok(());
        }

        let approval_ratio = approve_votes as f64 / total_votes as f64;
        let quorum_reached = approval_ratio >= self.config.parliament_quorum;
        let avg_conviction = record.votes.iter().map(|v| v.conviction).sum::<f64>()
            / total_votes as f64;

        if quorum_reached && avg_conviction >= self.config.conviction_threshold {
            info!(
                signal_id = %signal_id,
                approval_ratio = %approval_ratio,
                avg_conviction = %avg_conviction,
                "Parliament approved signal"
            );

            self.transition_state(signal_id, SignalState::Approved).await?;
        } else if total_votes >= self.config.parliament_min_votes * 2 {
            // Enough votes to reject definitively
            warn!(
                signal_id = %signal_id,
                approval_ratio = %approval_ratio,
                "Parliament rejected signal"
            );
            self.transition_state(signal_id, SignalState::Rejected).await?;
        }

        Ok(())
    }
}

async fn command_processor(
    mut rx: mpsc::Receiver<BusCommand>,
    signals: Arc<DashMap<Uuid, SignalGenome>>,
    broadcast: broadcast::Sender<BusMessage>,
) {
    while let Some(cmd) = rx.recv().await {
        match cmd {
            BusCommand::InsertSignal(signal) => {
                debug!(id = %signal.id, "Inserting signal");
                signals.insert(signal.id, signal);
            }

            BusCommand::UpdateSignalState { id, new_state } => {
                if let Some(mut signal) = signals.get_mut(&id) {
                    signal.state = new_state;
                    signal.updated_at = chrono::Utc::now();
                }
            }

            BusCommand::ApplyChallenge { signal_id, challenge } => {
                if let Some(mut signal) = signals.get_mut(&signal_id) {
                    signal.conviction += challenge.conviction_impact;
                    signal.conviction = signal.conviction.clamp(0.0, 1.0);
                    signal.challenge_history.push(challenge);
                    signal.updated_at = chrono::Utc::now();

                    // Kill signal if conviction drops to zero
                    if signal.conviction <= 0.0 {
                        signal.state = SignalState::Rejected;
                    }
                }
            }

            BusCommand::RecordVote { signal_id, vote } => {
                if let Some(mut signal) = signals.get_mut(&signal_id) {
                    if let Some(ref mut record) = signal.parliament_record {
                        record.votes.push(vote);
                    } else {
                        signal.parliament_record = Some(ParliamentRecord {
                            session_id: Uuid::new_v4(),
                            started_at: chrono::Utc::now(),
                            completed_at: None,
                            votes: vec![vote],
                            quorum_reached: false,
                            approved: false,
                            final_conviction: 0.0,
                            execution_recommendation: None,
                        });
                        signal.state = SignalState::InParliament;
                    }
                    signal.updated_at = chrono::Utc::now();
                }
            }

            BusCommand::FinalizeParliament { signal_id, record } => {
                if let Some(mut signal) = signals.get_mut(&signal_id) {
                    signal.conviction = record.final_conviction;
                    signal.parliament_record = Some(record);
                    signal.updated_at = chrono::Utc::now();
                }
            }

            BusCommand::ExpireOldSignals => {
                let cutoff = chrono::Utc::now() - chrono::Duration::seconds(SIGNAL_TTL_SECS);
                signals.retain(|_, s| {
                    s.created_at > cutoff || matches!(s.state, SignalState::Active)
                });
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// ERRORS
// ═══════════════════════════════════════════════════════════════

#[derive(Debug, thiserror::Error)]
pub enum BusError {
    #[error("Internal channel closed")]
    ChannelClosed,
    #[error("Signal not found: {0}")]
    SignalNotFound(Uuid),
    #[error("Invalid state transition from {from:?} to {to:?}")]
    InvalidTransition { from: SignalState, to: SignalState },
    #[error("Plugin error: {0}")]
    PluginError(String),
}

// ═══════════════════════════════════════════════════════════════
// SHARED STATE — Arc wrapper for use across Axum handlers
// ═══════════════════════════════════════════════════════════════

pub type SharedBus = Arc<SignalBus>;

pub fn create_bus(config: BusConfig) -> (SharedBus, broadcast::Receiver<BusMessage>) {
    let (bus, rx) = SignalBus::new(config);
    (Arc::new(bus), rx)
}
