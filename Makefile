# TradingOS Makefile — One-command operations

.PHONY: up down logs build dev clean install plugin-deploy test lint

# ─── FULL STACK ──────────────────────────────────────────────

up:
	@echo "🚀 Launching TradingOS..."
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up -d --build
	@echo ""
	@echo "✅ TradingOS is running:"
	@echo "   Dashboard:    http://localhost:3000"
	@echo "   API Gateway:  http://localhost:8080"
	@echo "   MCP Server:   http://localhost:4000/mcp"
	@echo "   Signal Bus:   http://localhost:7700"
	@echo "   Grafana:      http://localhost:3001"
	@echo ""
	@echo "Connect your AI agent to MCP: http://localhost:4000/mcp"

down:
	docker compose down

restart:
	docker compose restart $(service)

# ─── LOGS ────────────────────────────────────────────────────

logs:
	docker compose logs -f --tail=100

logs-signal-bus:
	docker compose logs -f signal-bus --tail=100

logs-intelligence:
	docker compose logs -f intelligence --tail=100

logs-parliament:
	docker compose logs -f agent-runtime --tail=100

# ─── BUILD ───────────────────────────────────────────────────

build:
	docker compose build --parallel

build-signal-bus:
	docker compose build signal-bus

build-dashboard:
	docker compose build dashboard

# ─── DEV MODE ────────────────────────────────────────────────

dev-signal-bus:
	cd packages/signal-bus && cargo run

dev-intelligence:
	cd packages/intelligence && python orchestrator.py

dev-mcp:
	cd packages/mcp-server && npm run dev

dev-dashboard:
	cd packages/dashboard && npm run dev

dev-gateway:
	cd packages/api-gateway && go run main.go

# ─── INSTALL ─────────────────────────────────────────────────

install:
	cd packages/mcp-server && npm install
	cd packages/dashboard && npm install
	cd packages/signal-bus && cargo fetch

# ─── WASM PLUGIN DEPLOYMENT ──────────────────────────────────

plugin-deploy:
ifndef name
	$(error "Usage: make plugin-deploy name=<plugin_name>")
endif
	@echo "Compiling $(name) to WASM..."
	cd plugins/strategies/$(name) && cargo build --release --target wasm32-unknown-unknown
	cp plugins/strategies/$(name)/target/wasm32-unknown-unknown/release/$(name).wasm plugins/strategies/
	@echo "✅ Plugin $(name) deployed — hot-reloaded by signal bus"

# ─── SIGNAL BUS COMMANDS ─────────────────────────────────────

scan:
	curl -s -X POST http://localhost:4000/mcp \
		-H "Content-Type: application/json" \
		-d '{"method":"tools/call","params":{"name":"signal_scan_now","arguments":{}}}' | jq .

signals:
	curl -s "http://localhost:8080/signals?min_conviction=0.5" | jq '.[] | {id: .id[:8], asset: .asset.symbol, conviction: .conviction, state: .state}'

parliament:
	curl -s "http://localhost:8080/signals?state=InParliament" | jq '.[] | {id: .id[:8], asset: .asset.symbol, votes: (.parliament_record.votes | length)}'

# ─── STATUS ──────────────────────────────────────────────────

status:
	@echo "=== TradingOS Service Status ==="
	@curl -s http://localhost:8080/health | jq . || echo "API Gateway: DOWN"
	@curl -s http://localhost:7700/health | jq . || echo "Signal Bus: DOWN"
	@curl -s http://localhost:7703/health | jq . || echo "Intelligence: DOWN"
	@curl -s http://localhost:4000/health | jq . || echo "MCP Server: DOWN"

# ─── TEST ────────────────────────────────────────────────────

test:
	cd packages/signal-bus && cargo test
	cd packages/intelligence && python -m pytest

test-signal-bus:
	cd packages/signal-bus && cargo test -- --nocapture

# ─── CLEAN ───────────────────────────────────────────────────

clean:
	docker compose down -v
	cd packages/signal-bus && cargo clean
	rm -rf packages/dashboard/.next packages/mcp-server/dist

# ─── DATABASE ────────────────────────────────────────────────

db-reset:
	docker compose exec postgres psql -U tradingos -c "DROP DATABASE IF EXISTS tradingos; CREATE DATABASE tradingos;"

db-shell:
	docker compose exec postgres psql -U tradingos tradingos

# ─── OBSERVABILITY ───────────────────────────────────────────

grafana:
	open http://localhost:3001

prometheus:
	open http://localhost:9090
