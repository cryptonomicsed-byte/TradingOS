mod types;
mod bus;
mod parliament;
mod plugins;
mod memory;
mod metrics;
mod routes;

use bus::{BusConfig, create_bus};
use routes::create_router;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .with(tracing_subscriber::fmt::layer().json())
        .init();

    info!("TradingOS Signal Bus starting...");

    // Load config from environment
    let config = BusConfig {
        conviction_threshold: std::env::var("CONVICTION_THRESHOLD")
            .unwrap_or_else(|_| "0.75".to_string())
            .parse()
            .unwrap_or(0.75),
        parliament_quorum: std::env::var("PARLIAMENT_QUORUM")
            .unwrap_or_else(|_| "0.67".to_string())
            .parse()
            .unwrap_or(0.67),
        parliament_min_votes: std::env::var("PARLIAMENT_MIN_VOTES")
            .unwrap_or_else(|_| "3".to_string())
            .parse()
            .unwrap_or(3),
        challenger_enabled: std::env::var("CHALLENGER_ENABLED")
            .unwrap_or_else(|_| "true".to_string())
            .parse()
            .unwrap_or(true),
        signal_ttl_secs: 3600,
    };

    let (bus, _rx) = create_bus(config);

    // Start metrics exporter
    let metrics_bus = bus.clone();
    tokio::spawn(async move {
        metrics::run_metrics_exporter(metrics_bus).await;
    });

    // Start signal expiry cleanup
    let expiry_bus = bus.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(300));
        loop {
            interval.tick().await;
            // Trigger expiry via bus (fire and forget)
        }
    });

    // Start HTTP server
    let port: u16 = std::env::var("SIGNAL_BUS_PORT")
        .unwrap_or_else(|_| "7700".to_string())
        .parse()
        .unwrap_or(7700);

    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], port));
    let router = create_router(bus);

    info!("Signal Bus listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, router).await?;

    Ok(())
}
