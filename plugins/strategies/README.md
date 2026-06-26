# TradingOS Strategy Plugins

WASM-compiled strategy plugins. Hot-swappable without system restart.

## Creating a Plugin

```bash
# 1. Scaffold a new plugin
mkdir -p my_strategy/src
cd my_strategy
```

Create `Cargo.toml`:
```toml
[package]
name = "my_strategy"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
tradingos-sdk = { git = "https://github.com/tradingos/sdk" }
serde_json = "1"
```

Create `src/lib.rs`:
```rust
use tradingos_sdk::prelude::*;

/// Your strategy logic — receives a signal, returns a vote
#[no_mangle]
pub extern "C" fn evaluate(signal_ptr: *const u8, signal_len: i32) -> i32 {
    let signal_bytes = unsafe { std::slice::from_raw_parts(signal_ptr, signal_len as usize) };
    let signal: SignalContext = serde_json::from_slice(signal_bytes).unwrap_or_default();

    let rsi = signal.get_indicator("rsi_14");
    let volume_ratio = signal.get_indicator("volume_ratio_24h");

    // Your logic here
    if rsi > 65.0 && volume_ratio > 2.0 {
        1 // Bullish strong
    } else if rsi < 35.0 {
        2 // Bullish moderate (oversold bounce)
    } else {
        3 // Neutral
    }
}

/// Return codes:
/// 1 = Bullish strong (0.8 confidence)
/// 2 = Bullish moderate (0.6 confidence)
/// 3 = Neutral
/// 4 = Bearish moderate (0.6 confidence)
/// 5 = Bearish strong (0.8 confidence)
```

Compile & deploy:
```bash
cargo build --release --target wasm32-unknown-unknown
make plugin-deploy name=my_strategy
```

The signal bus will hot-reload the plugin within seconds.

## Built-in Plugins

| Plugin | Strategy | Edge |
|--------|----------|------|
| `rsi_volume` | RSI momentum + volume confirmation | Trend confirmation |
| `whale_accumulation` | Smart money wallet tracking | Information edge |
| `narrative_momentum` | Fresh narrative detection | Early mover advantage |

## Plugin Safety

All plugins run in a WASM sandbox with:
- **Memory limit**: 64MB per plugin
- **CPU timeout**: 100ms per evaluation
- **No network access**: Plugins receive data, can't make external calls
- **No file system**: Pure computational logic only
