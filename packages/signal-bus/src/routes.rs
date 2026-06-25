use crate::bus::{SharedBus, BusConfig, create_bus};
use crate::types::*;
use axum::{
    extract::{Path, Query, State, WebSocketUpgrade},
    extract::ws::{Message, WebSocket},
    http::StatusCode,
    response::{IntoResponse, Json},
    routing::{get, post, put},
    Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::broadcast;
use tracing::{error, info};
use uuid::Uuid;
use std::collections::HashMap;

pub type AppState = SharedBus;

pub fn create_router(bus: SharedBus) -> Router {
    Router::new()
        // Health
        .route("/health", get(health_check))

        // Signal CRUD
        .route("/signals", get(list_signals).post(submit_signal))
        .route("/signals/:id", get(get_signal))
        .route("/signals/:id/state", put(transition_state))
        .route("/signals/high-conviction", get(high_conviction_signals))

        // Parliament
        .route("/signals/:id/challenge", post(submit_challenge))
        .route("/signals/:id/vote", post(submit_vote))
        .route("/signals/:id/parliament", get(get_parliament_record))

        // Plugins
        .route("/plugins", get(list_plugins))

        // WebSocket — real-time event stream
        .route("/ws", get(ws_handler))

        .with_state(bus)
}

// ─────────────────────────────────────────────────────────────
// HEALTH
// ─────────────────────────────────────────────────────────────

async fn health_check() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "service": "signal-bus",
        "version": env!("CARGO_PKG_VERSION")
    }))
}

// ─────────────────────────────────────────────────────────────
// SIGNAL ENDPOINTS
// ─────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct ListSignalsQuery {
    state: Option<String>,
    min_conviction: Option<f64>,
    asset: Option<String>,
    limit: Option<usize>,
}

async fn list_signals(
    State(bus): State<AppState>,
    Query(params): Query<ListSignalsQuery>,
) -> Json<Vec<SignalGenome>> {
    let mut signals = if let Some(min_conv) = params.min_conviction {
        bus.get_high_conviction_signals(min_conv)
    } else {
        bus.snapshot()
    };

    if let Some(asset) = &params.asset {
        signals.retain(|s| s.asset.symbol.to_lowercase() == asset.to_lowercase());
    }

    if let Some(state_str) = &params.state {
        signals.retain(|s| format!("{:?}", s.state).to_lowercase().contains(state_str));
    }

    let limit = params.limit.unwrap_or(100);
    signals.truncate(limit);

    Json(signals)
}

#[derive(Deserialize)]
struct SubmitSignalRequest {
    asset_symbol: String,
    asset_chain: String,
    asset_address: Option<String>,
    signal_type: SignalTypeRequest,
    source_type: String,
    market_context: Option<MarketContext>,
    indicators: Option<HashMap<String, f64>>,
    tags: Option<Vec<String>>,
}

#[derive(Deserialize)]
#[serde(tag = "type")]
enum SignalTypeRequest {
    Long { target_pct: f64, timeframe_hours: f64 },
    Short { target_pct: f64, timeframe_hours: f64 },
    Hold,
    Exit { urgency: String },
    Alert { message: String },
}

async fn submit_signal(
    State(bus): State<AppState>,
    Json(req): Json<SubmitSignalRequest>,
) -> Result<Json<SignalGenome>, StatusCode> {
    let chain = parse_chain(&req.asset_chain);
    let asset = AssetId {
        symbol: req.asset_symbol,
        chain,
        address: req.asset_address,
    };

    let signal_type = match req.signal_type {
        SignalTypeRequest::Long { target_pct, timeframe_hours } => {
            SignalType::Long { target_pct, timeframe_hours }
        }
        SignalTypeRequest::Short { target_pct, timeframe_hours } => {
            SignalType::Short { target_pct, timeframe_hours }
        }
        SignalTypeRequest::Hold => SignalType::Hold,
        SignalTypeRequest::Exit { urgency } => SignalType::Exit {
            urgency: ExitUrgency::Immediate,
        },
        SignalTypeRequest::Alert { message } => SignalType::Alert { message },
    };

    let source = SignalSource::StrategyPlugin {
        plugin_name: req.source_type,
        version: "1.0.0".to_string(),
    };

    let mut signal = SignalGenome::new(asset, signal_type, source);

    if let Some(ctx) = req.market_context {
        signal.market_context = ctx;
    }
    if let Some(indicators) = req.indicators {
        signal.indicators = indicators;
    }
    if let Some(tags) = req.tags {
        signal.tags = tags;
    }

    let id = bus.submit_signal(signal.clone()).await.map_err(|e| {
        error!("Failed to submit signal: {}", e);
        StatusCode::INTERNAL_SERVER_ERROR
    })?;

    Ok(Json(signal))
}

async fn get_signal(
    State(bus): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<SignalGenome>, StatusCode> {
    bus.get_signal(&id)
        .map(Json)
        .ok_or(StatusCode::NOT_FOUND)
}

#[derive(Deserialize)]
struct TransitionStateRequest {
    new_state: String,
}

async fn transition_state(
    State(bus): State<AppState>,
    Path(id): Path<Uuid>,
    Json(req): Json<TransitionStateRequest>,
) -> Result<StatusCode, StatusCode> {
    // Parse state from string (simplified)
    let new_state = match req.new_state.as_str() {
        "UnderChallenge" => SignalState::UnderChallenge,
        "InParliament" => SignalState::InParliament,
        "Approved" => SignalState::Approved,
        "Rejected" => SignalState::Rejected,
        "Executing" => SignalState::Executing,
        "Expired" => SignalState::Expired,
        _ => return Err(StatusCode::BAD_REQUEST),
    };

    bus.transition_state(id, new_state)
        .await
        .map(|_| StatusCode::OK)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)
}

async fn high_conviction_signals(
    State(bus): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Json<Vec<SignalGenome>> {
    let min_conviction = params
        .get("min_conviction")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0.75);
    Json(bus.get_high_conviction_signals(min_conviction))
}

// ─────────────────────────────────────────────────────────────
// PARLIAMENT ENDPOINTS
// ─────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct SubmitChallengeRequest {
    challenger_id: String,
    challenge_type: String,
    arguments: Vec<String>,
    counter_evidence: Vec<String>,
    conviction_impact: f64,
}

async fn submit_challenge(
    State(bus): State<AppState>,
    Path(signal_id): Path<Uuid>,
    Json(req): Json<SubmitChallengeRequest>,
) -> Result<StatusCode, StatusCode> {
    let challenge = ChallengeResult {
        id: Uuid::new_v4(),
        challenger_id: req.challenger_id,
        timestamp: chrono::Utc::now(),
        challenge_type: ChallengeType::MarketManipulation,
        arguments: req.arguments,
        counter_evidence: req.counter_evidence,
        outcome: if req.conviction_impact < 0.0 {
            ChallengeOutcome::ConvictionReduced
        } else {
            ChallengeOutcome::SignalSurvived
        },
        conviction_impact: req.conviction_impact,
    };

    bus.apply_challenge(signal_id, challenge)
        .await
        .map(|_| StatusCode::CREATED)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)
}

#[derive(Deserialize)]
struct SubmitVoteRequest {
    voter_id: String,
    voter_type: String,
    vote: String,
    conviction: f64,
    rationale: String,
}

async fn submit_vote(
    State(bus): State<AppState>,
    Path(signal_id): Path<Uuid>,
    Json(req): Json<SubmitVoteRequest>,
) -> Result<StatusCode, StatusCode> {
    let vote = Vote::Approve; // Simplified; parse from req.vote
    let vote = match req.vote.as_str() {
        "Approve" => Vote::Approve,
        "Reject" => Vote::Reject,
        "Abstain" => Vote::Abstain,
        _ => Vote::Abstain,
    };

    let parliament_vote = ParliamentVote {
        voter_id: req.voter_id,
        voter_type: AgentType::ParliamentVoter,
        vote,
        conviction: req.conviction,
        rationale: req.rationale,
        timestamp: chrono::Utc::now(),
    };

    bus.record_vote(signal_id, parliament_vote)
        .await
        .map(|_| StatusCode::CREATED)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)
}

async fn get_parliament_record(
    State(bus): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<Option<ParliamentRecord>>, StatusCode> {
    let signal = bus.get_signal(&id).ok_or(StatusCode::NOT_FOUND)?;
    Ok(Json(signal.parliament_record))
}

// ─────────────────────────────────────────────────────────────
// PLUGINS
// ─────────────────────────────────────────────────────────────

async fn list_plugins() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "plugins": [] }))
}

// ─────────────────────────────────────────────────────────────
// WEBSOCKET — Real-time event stream
// ─────────────────────────────────────────────────────────────

async fn ws_handler(
    ws: WebSocketUpgrade,
    State(bus): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, bus))
}

async fn handle_ws(mut socket: WebSocket, bus: SharedBus) {
    let mut rx = bus.subscribe();
    info!("WebSocket client connected to signal bus");

    loop {
        match rx.recv().await {
            Ok(msg) => {
                let json = match serde_json::to_string(&msg) {
                    Ok(j) => j,
                    Err(e) => {
                        error!("Failed to serialize bus message: {}", e);
                        continue;
                    }
                };

                if socket.send(Message::Text(json)).await.is_err() {
                    break; // Client disconnected
                }
            }
            Err(broadcast::error::RecvError::Lagged(n)) => {
                error!("WebSocket client lagged {} messages", n);
            }
            Err(broadcast::error::RecvError::Closed) => break,
        }
    }

    info!("WebSocket client disconnected");
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

fn parse_chain(s: &str) -> Chain {
    match s.to_lowercase().as_str() {
        "solana" | "sol" => Chain::Solana,
        "ethereum" | "eth" => Chain::Ethereum,
        "base" => Chain::Base,
        "arbitrum" | "arb" => Chain::Arbitrum,
        "bnb" | "bsc" => Chain::BNBChain,
        cex => Chain::CEX(cex.to_string()),
    }
}
