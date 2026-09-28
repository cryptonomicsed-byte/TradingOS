package service

import (
	"time"
	"tradingos/ingestion/internal/domain"
)

// TickAggregator aggregates raw ticks into OHLCV candles.
type TickAggregator struct {
	duration time.Duration
	current  *domain.OHLCV
}

func NewTickAggregator(duration time.Duration) *TickAggregator {
	return &TickAggregator{
		duration: duration,
	}
}

func (a *TickAggregator) ProcessTick(tick domain.Tick) *domain.OHLCV {
	bucket := tick.Timestamp.Truncate(a.duration)

	if a.current == nil {
		a.current = &domain.OHLCV{
			Ticker:    tick.Ticker,
			Open:      tick.Price,
			High:      tick.Price,
			Low:       tick.Price,
			Close:     tick.Price,
			Volume:    tick.Size,
			Timestamp: bucket,
		}
		return nil
	}

	if bucket.After(a.current.Timestamp) {
		completed := *a.current
		a.current = &domain.OHLCV{
			Ticker:    tick.Ticker,
			Open:      tick.Price,
			High:      tick.Price,
			Low:       tick.Price,
			Close:     tick.Price,
			Volume:    tick.Size,
			Timestamp: bucket,
		}
		return &completed
	}

	// Update current candle
	if tick.Price > a.current.High {
		a.current.High = tick.Price
	}
	if tick.Price < a.current.Low {
		a.current.Low = tick.Price
	}
	a.current.Close = tick.Price
	a.current.Volume += tick.Size

	return nil
}
