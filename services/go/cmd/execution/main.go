package main

import (
	"fmt"
	"sync"
	"time"
)

// OrderManager handles trade execution logic.
type OrderManager struct {
	mu           sync.Mutex
	dailyPnL     float64
	maxDailyLoss float64
	isHalted     bool
}

type Position struct {
	Ticker    string
	Quantity  float64
	Entry     float64
	LockedSL  float64
	LockedTP  float64
}

func (om *OrderManager) ExecuteOrder(ticker string, side string, quantity float64, price float64, atr float64) {
	om.mu.Lock()
	defer om.mu.Unlock()

	if om.isHalted {
		fmt.Printf("🚫 System Halted. Order for %s rejected.\n", ticker)
		return
	}

	fmt.Printf("⚔️ Executing %s order for %.4f %s at %.2f...\n", side, quantity, ticker, price)
	
	// The Shield: ATR-locked SL/TP
	sl := price - (atr * 2.0)
	tp := price + (atr * 3.0)
	
	if side == "SELL" {
		sl = price + (atr * 2.0)
		tp = price - (atr * 3.0)
	}

	fmt.Printf("🛡️ Shield Activated: SL: %.2f | TP: %.2f\n", sl, tp)
}

func (om *OrderManager) UpdatePnL(pnl float64) {
	om.mu.Lock()
	defer om.mu.Unlock()

	om.dailyPnL += pnl
	fmt.Printf("📊 Daily PnL Update: %.2f\n", om.dailyPnL)

	// Circuit Breaker
	if om.dailyPnL <= -om.maxDailyLoss {
		fmt.Printf("🚨 CIRCUIT BREAKER TRIGGERED: Daily Loss %.2f exceeds limit %.2f. HALTING.\n", om.dailyPnL, om.maxDailyLoss)
		om.isHalted = true
	}
}

func main() {
	om := &OrderManager{maxDailyLoss: 1000.0}
	
	// Simulation
	om.ExecuteOrder("BTCUSDT", "BUY", 0.1, 60000.0, 500.0)
	om.UpdatePnL(-1100.0)
	om.ExecuteOrder("ETHUSDT", "BUY", 1.0, 3000.0, 50.0)
}
