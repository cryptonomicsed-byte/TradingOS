module github.com/tradingos/api-gateway

go 1.22

require (
	github.com/gin-contrib/cors v1.7.2
	github.com/gin-gonic/gin v1.10.0
	github.com/gorilla/websocket v1.5.3
	github.com/redis/go-redis/v9 v9.5.3
	go.opentelemetry.io/otel v1.27.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.27.0
	go.opentelemetry.io/otel/sdk v1.27.0
	go.uber.org/zap v1.27.0
)
