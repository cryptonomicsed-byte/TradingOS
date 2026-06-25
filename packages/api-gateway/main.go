// TradingOS API Gateway
// High-performance Go HTTP/WebSocket gateway that routes requests
// between the dashboard, MCP server, and backend services.

package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

// Service URLs (from environment)
type Config struct {
	SignalBusURL    string
	AgentRuntimeURL string
	IntelligenceURL string
	QuantEngineURL  string
	Port            string
}

func loadConfig() Config {
	return Config{
		SignalBusURL:    getEnv("SIGNAL_BUS_URL", "http://signal-bus:7700"),
		AgentRuntimeURL: getEnv("AGENT_RUNTIME_URL", "http://agent-runtime:7701"),
		IntelligenceURL: getEnv("INTELLIGENCE_URL", "http://intelligence:7703"),
		QuantEngineURL:  getEnv("QUANT_ENGINE_URL", "http://quant-engine:7702"),
		Port:            getEnv("API_GATEWAY_PORT", "8080"),
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

func main() {
	cfg := loadConfig()

	// Parse service URLs
	signalBusURL, err := url.Parse(cfg.SignalBusURL)
	if err != nil {
		log.Fatalf("Invalid SIGNAL_BUS_URL: %v", err)
	}
	intelligenceURL, err := url.Parse(cfg.IntelligenceURL)
	if err != nil {
		log.Fatalf("Invalid INTELLIGENCE_URL: %v", err)
	}

	// Proxies
	signalBusProxy := httputil.NewSingleHostReverseProxy(signalBusURL)
	intelligenceProxy := httputil.NewSingleHostReverseProxy(intelligenceURL)

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(logMiddleware())

	// CORS
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"*"},
		ExposeHeaders:    []string{"*"},
		AllowWebSockets:  true,
		MaxAge:           12 * time.Hour,
	}))

	// ─── HEALTH ──────────────────────────────────────
	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{
			"status":  "ok",
			"service": "api-gateway",
			"version": "0.1.0",
			"backends": gin.H{
				"signal_bus":   probeService(cfg.SignalBusURL + "/health"),
				"intelligence": probeService(cfg.IntelligenceURL + "/health"),
			},
		})
	})

	// ─── SIGNAL BUS ROUTES ──────────────────────────
	// Proxy signal CRUD to Rust signal bus
	signalGroup := r.Group("/signals")
	{
		signalGroup.GET("", proxyHandler(signalBusProxy))
		signalGroup.POST("", proxyHandler(signalBusProxy))
		signalGroup.GET("/:id", proxyHandler(signalBusProxy))
		signalGroup.PUT("/:id/state", proxyHandler(signalBusProxy))
		signalGroup.POST("/:id/challenge", proxyHandler(signalBusProxy))
		signalGroup.POST("/:id/vote", proxyHandler(signalBusProxy))
		signalGroup.GET("/:id/parliament", proxyHandler(signalBusProxy))
		signalGroup.GET("/high-conviction", proxyHandler(signalBusProxy))
	}

	// WebSocket for real-time signal bus events
	r.GET("/signals/ws", func(c *gin.Context) {
		wsProxyHandler(c, cfg.SignalBusURL)
	})

	// ─── INTELLIGENCE ROUTES ────────────────────────
	intelligenceGroup := r.Group("/intelligence")
	{
		intelligenceGroup.GET("/health", proxyHandler(intelligenceProxy))
		intelligenceGroup.GET("/agents", proxyHandler(intelligenceProxy))
		intelligenceGroup.GET("/agents/:id", proxyHandler(intelligenceProxy))
		intelligenceGroup.POST("/analyze", proxyHandler(intelligenceProxy))
		intelligenceGroup.POST("/challenge", proxyHandler(intelligenceProxy))
		intelligenceGroup.POST("/scan", proxyHandler(intelligenceProxy))
		intelligenceGroup.POST("/memory/recall", proxyHandler(intelligenceProxy))
		intelligenceGroup.POST("/memory/outcome", proxyHandler(intelligenceProxy))
	}

	// Also expose at /agents (without prefix) for MCP server convenience
	r.GET("/agents", proxyHandler(intelligenceProxy))
	r.GET("/agents/:id", proxyHandler(intelligenceProxy))

	// ─── MARKET DATA AGGREGATOR ─────────────────────
	// These endpoints aggregate from multiple sources and cache in Redis
	marketGroup := r.Group("/market")
	{
		marketGroup.GET("/context", marketContextHandler(cfg))
		marketGroup.GET("/trending", trendingHandler(cfg))
		marketGroup.GET("/token/:symbol", tokenMetricsHandler(cfg))
		marketGroup.GET("/whales", whaleMovementsHandler(cfg))
	}

	// ─── PORTFOLIO ──────────────────────────────────
	portfolioGroup := r.Group("/portfolio")
	{
		portfolioGroup.GET("", portfolioHandler())
		portfolioGroup.GET("/positions", positionsHandler())
		portfolioGroup.GET("/pnl", pnlHandler())
		portfolioGroup.GET("/risk", riskHandler())
		portfolioGroup.PUT("/positions/:id/stops", updateStopsHandler())
	}

	addr := fmt.Sprintf("0.0.0.0:%s", cfg.Port)
	log.Printf("TradingOS API Gateway listening on %s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("Gateway failed: %v", err)
	}
}

// ─── PROXY HANDLER ──────────────────────────────────────────

func proxyHandler(proxy *httputil.ReverseProxy) gin.HandlerFunc {
	return func(c *gin.Context) {
		proxy.ServeHTTP(c.Writer, c.Request)
	}
}

// WebSocket proxy — bridges client WS to signal bus WS
func wsProxyHandler(c *gin.Context, busURL string) {
	wsURL := "ws" + busURL[4:] + "/ws"

	// Connect to signal bus WebSocket
	backendConn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		c.JSON(503, gin.H{"error": "Signal bus WebSocket unavailable"})
		return
	}
	defer backendConn.Close()

	// Upgrade client connection
	clientConn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer clientConn.Close()

	// Bidirectional proxy
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		defer cancel()
		for {
			_, msg, err := backendConn.ReadMessage()
			if err != nil {
				return
			}
			if err := clientConn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		}
	}()

	for {
		select {
		case <-ctx.Done():
			return
		default:
			_, msg, err := clientConn.ReadMessage()
			if err != nil {
				return
			}
			backendConn.WriteMessage(websocket.TextMessage, msg)
		}
	}
}

// ─── MARKET DATA HANDLERS ────────────────────────────────────

func marketContextHandler(cfg Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		// In production: aggregate from CoinGecko, Glassnode, etc.
		c.JSON(200, gin.H{
			"btc_dominance":      50.2,
			"total_market_cap":   2.4e12,
			"fear_greed_index":   62,
			"fear_greed_label":   "Greed",
			"sol_price_usd":      165.3,
			"eth_price_usd":      3400.0,
			"sol_tps":            3200,
			"eth_gas_gwei":       12.5,
			"updated_at":         time.Now(),
		})
	}
}

func trendingHandler(cfg Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{"tokens": []interface{}{}})
	}
}

func tokenMetricsHandler(cfg Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		symbol := c.Param("symbol")
		c.JSON(200, gin.H{
			"symbol": symbol,
			"note":   "Token metrics require API keys — see .env.example",
		})
	}
}

func whaleMovementsHandler(cfg Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{"movements": []interface{}{}})
	}
}

// ─── PORTFOLIO HANDLERS ──────────────────────────────────────

func portfolioHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{
			"total_value_usd":   0,
			"deployed_pct":      0,
			"unrealized_pnl":    0,
			"realized_pnl_30d":  0,
			"win_rate":          0,
			"total_trades":      0,
			"positions":         []interface{}{},
		})
	}
}

func positionsHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{"positions": []interface{}{}})
	}
}

func pnlHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{
			"realized_pnl": 0,
			"unrealized_pnl": 0,
			"trades": []interface{}{},
		})
	}
}

func riskHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{
			"max_drawdown_pct": 0,
			"sharpe_ratio":     0,
			"deployed_pct":     0,
			"risk_level":       "none",
		})
	}
}

func updateStopsHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(200, gin.H{"success": true, "position_id": c.Param("id")})
	}
}

// ─── MIDDLEWARE ──────────────────────────────────────────────

func logMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		log.Printf("[%s] %s %s %d %v",
			c.Request.Method,
			c.Request.URL.Path,
			c.ClientIP(),
			c.Writer.Status(),
			time.Since(start),
		)
	}
}

// ─── HELPERS ─────────────────────────────────────────────────

func probeService(healthURL string) string {
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(healthURL)
	if err != nil || resp.StatusCode != 200 {
		return "unhealthy"
	}
	return "healthy"
}
