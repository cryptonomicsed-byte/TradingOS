use crate::bus::SharedBus;
use crate::types::SignalState;
use tokio::time::{interval, Duration};
use tracing::debug;

pub async fn run_metrics_exporter(bus: SharedBus) {
    let mut ticker = interval(Duration::from_secs(15));
    loop {
        ticker.tick().await;
        let signals = bus.snapshot();

        let total = signals.len();
        let spawned = signals.iter().filter(|s| s.state == SignalState::Spawned).count();
        let in_parliament = signals.iter().filter(|s| s.state == SignalState::InParliament).count();
        let approved = signals.iter().filter(|s| s.state == SignalState::Approved).count();
        let active = signals.iter().filter(|s| s.state == SignalState::Active).count();
        let rejected = signals.iter().filter(|s| s.state == SignalState::Rejected).count();

        let avg_conviction = if !signals.is_empty() {
            signals.iter().map(|s| s.conviction).sum::<f64>() / signals.len() as f64
        } else {
            0.0
        };

        debug!(
            total_signals = total,
            spawned = spawned,
            in_parliament = in_parliament,
            approved = approved,
            active = active,
            rejected = rejected,
            avg_conviction = %format!("{:.3}", avg_conviction),
            "Signal bus metrics"
        );
    }
}
