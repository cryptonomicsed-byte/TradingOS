# Observability Stack

TradingOS uses a full observability stack for metrics, logging, and tracing.

## Components

- **Prometheus:** Metrics collection and alerting.
  - URL: `http://localhost:9090`
- **Grafana:** Visualization and dashboards.
  - URL: `http://localhost:3000`
  - Default Login: `admin/admin`
- **Loki:** Log aggregation (Grafana-integrated).
  - URL: `http://localhost:3100`
- **Jaeger:** Distributed tracing.
  - URL: `http://localhost:16686`

## Integration

All polyglot services should emit metrics via Prometheus exporters and traces via OpenTelemetry (OTLP) to Jaeger. Logs should be sent to Loki via Docker log drivers or specialized client libraries.
