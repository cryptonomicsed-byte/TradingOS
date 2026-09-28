package adapters

import (
	"context"
	"math/rand"
	"time"
	"tradingos/ingestion/internal/domain"
)

// MockAdapter simulates an exchange connection.
type MockAdapter struct {
	ticks chan domain.Tick
}

func NewMockAdapter() *MockAdapter {
	return &MockAdapter{
		ticks: make(chan domain.Tick),
	}
}

func (m *MockAdapter) Connect(ctx context.Context) error {
	return nil
}

func (m *MockAdapter) SubscribeTicks(ctx context.Context, ticker string) (<-chan domain.Tick, error) {
	go func() {
		price := 100.0
		for {
			select {
			case <-ctx.Done():
				return
			case <-time.After(500 * time.Millisecond):
				price += (rand.Float64() - 0.5) * 2
				m.ticks <- domain.Tick{
					Ticker:    ticker,
					Price:     price,
					Size:      rand.Float64() * 10,
					Timestamp: time.Now(),
				}
			}
		}
	}()
	return m.ticks, nil
}

func (m *MockAdapter) SubscribeOrderBook(ctx context.Context, ticker string) (<-chan domain.OrderBook, error) {
	books := make(chan domain.OrderBook)
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-time.After(1 * time.Second):
				books <- domain.OrderBook{
					Ticker: ticker,
					Bids:   []domain.PriceLevel{{Price: 100.0, Size: 1.0}},
					Asks:   []domain.PriceLevel{{Price: 100.1, Size: 1.0}},
					Timestamp: time.Now(),
				}
			}
		}
	}()
	return books, nil
}

func (m *MockAdapter) Close() error {
	close(m.ticks)
	return nil
}
