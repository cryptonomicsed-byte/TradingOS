package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"
	"tradingos/ingestion/internal/adapters"
	"tradingos/ingestion/internal/domain"
	"tradingos/ingestion/internal/infrastructure/kafka"
	"tradingos/ingestion/internal/service"
)

func main() {
	fmt.Println("🚀 Starting TradingOS Robust Market Data Ingestion...")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Kafka Setup
	kafkaBroker := os.Getenv("KAFKA_BROKER")
	if kafkaBroker == "" {
		kafkaBroker = "localhost:9092"
	}
	tickProducer := kafka.NewProducer(kafkaBroker, "market.ticks")
	defer tickProducer.Close()

	// Handle graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigChan
		fmt.Println("\n🛑 Shutting down...")
		cancel()
	}()

	// Initialize Adapter (Production Binance Adapter with Fallback)
	var adapter domain.ExchangeAdapter
	adapter = adapters.NewBinanceAdapter()
	
	// Subscribe to ticks
	ticker := "btcusdt"
	ticks, err := adapter.SubscribeTicks(ctx, ticker)
	if err != nil {
		log.Printf("⚠️ Binance subscribe failed: %v. Falling back to Mock.", err)
		adapter = adapters.NewMockAdapter()
		ticks, _ = adapter.SubscribeTicks(ctx, ticker)
	}

	// Subscribe to order book
	books, err := adapter.SubscribeOrderBook(ctx, ticker)
	if err != nil {
		log.Printf("⚠️ Binance order book subscribe failed: %v.", err)
	}

	// Initialize Aggregator (1 minute buckets)
	aggregator := service.NewTickAggregator(1 * time.Minute)

	fmt.Printf("📡 Subscribed to %s market data streams...\n", ticker)

	for {
		select {
		case <-ctx.Done():
			return
		case tick := <-ticks:
			// Publish raw tick to Kafka
			_ = tickProducer.Publish(ctx, ticker, tick)

			// Process tick into OHLCV
			if candle := aggregator.ProcessTick(tick); candle != nil {
				fmt.Printf("📊 New Candle: %s | C: %.2f | V: %.2f\n",
					candle.Ticker, candle.Close, candle.Volume)
			}
		case book := <-books:
			if book.Ticker != "" && len(book.Bids) > 0 {
				// Log top of book occasionally
				if time.Now().Unix() % 10 == 0 {
					fmt.Printf("📖 Book %s: Bid: %.2f | Ask: %.2f\n", 
						book.Ticker, book.Bids[0].Price, book.Asks[0].Price)
				}
			}
		}
	}
}
