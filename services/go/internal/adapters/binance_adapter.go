package adapters

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strconv"
	"time"
	"tradingos/ingestion/internal/domain"

	"github.com/gorilla/websocket"
)

// BinanceAdapter connects to the Binance WebSocket stream.
type BinanceAdapter struct {
	conn *websocket.Conn
}

type binanceTrade struct {
	Symbol string `json:"s"`
	Price  string `json:"p"`
	Size   string `json:"q"`
	Time   int64  `json:"T"`
}

func NewBinanceAdapter() *BinanceAdapter {
	return &BinanceAdapter{}
}

func (b *BinanceAdapter) Connect(ctx context.Context) error {
	return nil // Connection is established per subscription in this simple impl
}

func (b *BinanceAdapter) SubscribeTicks(ctx context.Context, ticker string) (<-chan domain.Tick, error) {
	url := fmt.Sprintf("wss://stream.binance.com:9443/ws/%s@aggTrade", ticker)
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return nil, err
	}
	b.conn = conn

	ticks := make(chan domain.Tick)

	go func() {
		defer close(ticks)
		defer conn.Close()

		for {
			select {
			case <-ctx.Done():
				return
			default:
				_, message, err := conn.ReadMessage()
				if err != nil {
					log.Printf("Binance read error: %v", err)
					return
				}

				var trade binanceTrade
				if err := json.Unmarshal(message, &trade); err != nil {
					continue
				}

				price, _ := strconv.ParseFloat(trade.Price, 64)
				size, _ := strconv.ParseFloat(trade.Size, 64)

				ticks <- domain.Tick{
					Ticker:    trade.Symbol,
					Price:     price,
					Size:      size,
					Timestamp: time.Unix(0, trade.Time*int64(time.Millisecond)),
				}
			}
		}
	}()

	return ticks, nil
}

func (b *BinanceAdapter) SubscribeOrderBook(ctx context.Context, ticker string) (<-chan domain.OrderBook, error) {
	url := fmt.Sprintf("wss://stream.binance.com:9443/ws/%s@depth10@100ms", ticker)
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return nil, err
	}

	bookChan := make(chan domain.OrderBook)

	go func() {
		defer close(bookChan)
		defer conn.Close()

		for {
			select {
			case <-ctx.Done():
				return
			default:
				_, message, err := conn.ReadMessage()
				if err != nil {
					log.Printf("Binance depth read error: %v", err)
					return
				}

				var raw struct {
					Bids [][]string `json:"bids"`
					Asks [][]string `json:"asks"`
				}
				if err := json.Unmarshal(message, &raw); err != nil {
					continue
				}

				book := domain.OrderBook{
					Ticker:    ticker,
					Timestamp: time.Now(),
				}

				for _, bid := range raw.Bids {
					p, _ := strconv.ParseFloat(bid[0], 64)
					s, _ := strconv.ParseFloat(bid[1], 64)
					book.Bids = append(book.Bids, domain.PriceLevel{Price: p, Size: s})
				}

				for _, ask := range raw.Asks {
					p, _ := strconv.ParseFloat(ask[0], 64)
					s, _ := strconv.ParseFloat(ask[1], 64)
					book.Asks = append(book.Asks, domain.PriceLevel{Price: p, Size: s})
				}

				bookChan <- book
			}
		}
	}()

	return bookChan, nil
}

func (b *BinanceAdapter) Close() error {
	if b.conn != nil {
		return b.conn.Close()
	}
	return nil
}
