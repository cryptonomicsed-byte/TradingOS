use crate::types::*;
use crate::bus::{SharedBus, BusError};
use tracing::{info, warn, debug};
use uuid::Uuid;
use chrono::Utc;

// ═══════════════════════════════════════════════════════════════
// PARLIAMENT ENGINE — Distributed consensus for signals
// ═══════════════════════════════════════════════════════════════

/// The Parliament Engine orchestrates the full deliberation
/// process for a signal: spawning challengers, collecting votes,
/// applying Memory Court recollections, and reaching consensus.
pub struct ParliamentEngine {
    bus: SharedBus,
    config: ParliamentConfig,
}

pub struct ParliamentConfig {
    pub quorum_pct: f64,
    pub min_votes: usize,
    pub timeout_secs: u64,
    pub conviction_threshold: f64,
    pub challenger_rounds: u32,
}

impl Default for ParliamentConfig {
    fn default() -> Self {
        Self {
            quorum_pct: 0.67,
            min_votes: 3,
            timeout_secs: 30,
            conviction_threshold: 0.75,
            challenger_rounds: 1,
        }
    }
}

impl ParliamentEngine {
    pub fn new(bus: SharedBus, config: ParliamentConfig) -> Self {
        Self { bus, config }
    }

    /// Run the full parliament process for a signal.
    /// Returns the final conviction score and whether it was approved.
    pub async fn deliberate(&self, signal_id: Uuid) -> Result<DeliberationResult, ParliamentError> {
        let signal = self
            .bus
            .get_signal(&signal_id)
            .ok_or(ParliamentError::SignalNotFound(signal_id))?;

        info!(
            signal_id = %signal_id,
            asset = %signal.asset.symbol,
            "Parliament session opening"
        );

        // Phase 1: Challenge Round
        // (In production: dispatches to Challenger agent endpoints via A2A)
        let challenge_result = self.run_challenge_phase(&signal).await?;

        // If signal was killed by challenge, short-circuit
        if challenge_result.signal_killed {
            self.bus
                .transition_state(signal_id, SignalState::Rejected)
                .await
                .map_err(|e| ParliamentError::BusError(e.to_string()))?;

            return Ok(DeliberationResult {
                signal_id,
                approved: false,
                final_conviction: 0.0,
                reason: "Signal killed during challenge phase".to_string(),
                execution_recommendation: None,
            });
        }

        // Phase 2: Memory Court
        // (In production: queries vector store for similar historical signals)
        let memory_score = self.consult_memory_court(&signal).await;

        // Phase 3: Parliament Voting
        // (In production: dispatches to all registered Validator agents)
        let conviction_after_memory = signal.conviction * (0.5 + 0.5 * memory_score);

        // Synthesize final result
        let approved = conviction_after_memory >= self.config.conviction_threshold;

        let execution_rec = if approved {
            Some(self.build_execution_recommendation(&signal, conviction_after_memory))
        } else {
            None
        };

        let new_state = if approved {
            SignalState::Approved
        } else {
            SignalState::Rejected
        };

        self.bus
            .transition_state(signal_id, new_state)
            .await
            .map_err(|e| ParliamentError::BusError(e.to_string()))?;

        info!(
            signal_id = %signal_id,
            approved = %approved,
            conviction = %conviction_after_memory,
            "Parliament session concluded"
        );

        Ok(DeliberationResult {
            signal_id,
            approved,
            final_conviction: conviction_after_memory,
            reason: if approved {
                "Quorum reached with sufficient conviction".to_string()
            } else {
                "Insufficient conviction after deliberation".to_string()
            },
            execution_recommendation: execution_rec,
        })
    }

    async fn run_challenge_phase(&self, signal: &SignalGenome) -> Result<ChallengePhaseResult, ParliamentError> {
        debug!(signal_id = %signal.id, "Running challenge phase");

        // In production, this dispatches to registered Challenger agents
        // and waits for their responses. Here we run a deterministic check.
        let mut total_impact = 0.0_f64;
        let mut challenges_made = 0;

        // Liquidity check
        if let Some(liq) = signal.market_context.liquidity_usd {
            if liq < 50_000.0 {
                total_impact -= 0.3;
                challenges_made += 1;
                warn!(
                    signal_id = %signal.id,
                    liquidity = %liq,
                    "Low liquidity challenge applied"
                );
            }
        }

        // Volume surge check (ensure it's not wash trading)
        if let Some(vol) = signal.market_context.volume_24h_usd {
            if let Some(mcap) = signal.market_context.market_cap_usd {
                let vol_ratio = vol / mcap;
                if vol_ratio > 10.0 {
                    // Suspicious: volume 10x market cap in 24h
                    total_impact -= 0.2;
                    challenges_made += 1;
                }
            }
        }

        // Fear & greed extremes
        if let Some(fg) = signal.market_context.fear_greed_index {
            if fg > 90 {
                total_impact -= 0.1; // Extreme greed = contrarian signal
                challenges_made += 1;
            }
        }

        // Signal killed if total negative impact exceeds conviction
        let signal_killed = signal.conviction + total_impact <= 0.0;

        if challenges_made > 0 {
            let challenge = ChallengeResult {
                id: Uuid::new_v4(),
                challenger_id: "parliament-engine-auto".to_string(),
                timestamp: Utc::now(),
                challenge_type: ChallengeType::LiquidityRisk,
                arguments: vec![
                    format!("Automatic challenge detected {} issues", challenges_made),
                ],
                counter_evidence: vec![],
                outcome: if signal_killed {
                    ChallengeOutcome::SignalKilled
                } else {
                    ChallengeOutcome::ConvictionReduced
                },
                conviction_impact: total_impact,
            };

            self.bus
                .apply_challenge(signal.id, challenge)
                .await
                .map_err(|e| ParliamentError::BusError(e.to_string()))?;
        }

        Ok(ChallengePhaseResult {
            challenges_applied: challenges_made,
            total_conviction_impact: total_impact,
            signal_killed,
        })
    }

    async fn consult_memory_court(&self, signal: &SignalGenome) -> f64 {
        // In production: query Qdrant vector store for similar signals
        // and return weighted average historical outcome.
        // Here we return a neutral score.
        0.5_f64
    }

    fn build_execution_recommendation(
        &self,
        signal: &SignalGenome,
        conviction: f64,
    ) -> ExecutionRecommendation {
        // Scale position size with conviction
        let base_size = 0.02; // 2% base
        let position_size_pct = base_size * conviction;

        // Scale slippage tolerance with liquidity
        let max_slippage = if signal
            .market_context
            .liquidity_usd
            .map_or(false, |l| l > 1_000_000.0)
        {
            0.005 // 0.5% for liquid markets
        } else {
            0.02 // 2% for less liquid
        };

        ExecutionRecommendation {
            position_size_pct,
            max_slippage,
            entry_strategy: if conviction > 0.9 {
                EntryStrategy::MarketOrder
            } else {
                EntryStrategy::LimitOrder { price_pct_below_market: 0.005 }
            },
            exit_plan: ExitPlan {
                hard_stop_pct: 0.15,
                take_profit_targets: vec![
                    TakeProfitLevel { pct_gain: 0.25, position_pct_to_exit: 0.33 },
                    TakeProfitLevel { pct_gain: 0.50, position_pct_to_exit: 0.33 },
                    TakeProfitLevel { pct_gain: 1.00, position_pct_to_exit: 0.34 },
                ],
                trailing_stop_pct: Some(0.05),
                max_hold_hours: 72.0,
                time_stop: Some(Utc::now() + chrono::Duration::hours(72)),
            },
            priority_fee_lamports: Some(100_000),
            use_jito_bundle: true,
        }
    }
}

#[derive(Debug)]
pub struct DeliberationResult {
    pub signal_id: Uuid,
    pub approved: bool,
    pub final_conviction: f64,
    pub reason: String,
    pub execution_recommendation: Option<ExecutionRecommendation>,
}

struct ChallengePhaseResult {
    challenges_applied: u32,
    total_conviction_impact: f64,
    signal_killed: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum ParliamentError {
    #[error("Signal not found: {0}")]
    SignalNotFound(Uuid),
    #[error("Bus error: {0}")]
    BusError(String),
    #[error("Timeout: parliament deliberation exceeded {0}s")]
    Timeout(u64),
}
