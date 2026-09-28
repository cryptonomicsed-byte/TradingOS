package domain

import (
	"context"
	"time"
)

// Tick represents a single price update from an exchange.
type Tick struct {
	Ticker    string    `json:"ticker"`
	Price     float64   `json:"price"`
	Size      float64   `json:"size"`
	Timestamp time.Time `json:"timestamp"`
}

// OHLCV represents a single candlestick.
type OHLCV struct {
	Ticker    string    `json:"ticker"`
	Open      float64   `json:"open"`
	High      float64   `json:"high"`
	Low       float64   `json:"low"`
	Close     float64   `json:"close"`
	Volume    float64   `json:"volume"`
	Timestamp time.Time `json:"timestamp"`
}

// OrderBook represents the depth of the market.
type OrderBook struct {
	Ticker    string    `json:"ticker"`
	Bids      []PriceLevel `json:"bids"`
	Asks      []PriceLevel `json:"asks"`
	Timestamp time.Time `json:"timestamp"`
}

type PriceLevel struct {
	Price float64 `json:"price"`
	Size  float64 `json:"size"`
}

// ExchangeAdapter defines the interface for exchange connectors.
type ExchangeAdapter interface {
	Connect(ctx context.Context) error
	SubscribeTicks(ctx context.Context, ticker string) (<-chan Tick, error)
	SubscribeOrderBook(ctx context.Context, ticker string) (<-chan OrderBook, error)
	Close() error
}
