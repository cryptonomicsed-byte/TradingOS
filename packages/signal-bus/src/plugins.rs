use crate::bus::PluginEvaluator;
use crate::types::*;
use anyhow::Result;
use std::path::Path;
use tracing::{error, info};
use wasmtime::*;

// ═══════════════════════════════════════════════════════════════
// WASM PLUGIN HOST — Hot-swappable strategy sandbox
// ═══════════════════════════════════════════════════════════════

/// Loads and executes WASM strategy plugins in a sandboxed environment.
/// Plugins can be hot-swapped without system restart.
pub struct WasmPluginHost {
    engine: Engine,
}

impl WasmPluginHost {
    pub fn new() -> Result<Self> {
        let mut config = Config::new();
        config.wasm_memory64(false);
        config.cranelift_opt_level(OptLevel::Speed);

        let engine = Engine::new(&config)?;
        Ok(Self { engine })
    }

    pub fn load_plugin(&self, wasm_path: &Path) -> Result<Box<dyn PluginEvaluator>> {
        info!("Loading WASM plugin from {:?}", wasm_path);

        let module = Module::from_file(&self.engine, wasm_path)?;
        let plugin = WasmPlugin {
            module,
            engine: self.engine.clone(),
            name: wasm_path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("unknown")
                .to_string(),
            version: "1.0.0".to_string(),
        };

        Ok(Box::new(plugin))
    }

    pub fn load_directory(&self, dir: &Path) -> Vec<Box<dyn PluginEvaluator>> {
        let mut plugins = Vec::new();

        let read_dir = match std::fs::read_dir(dir) {
            Ok(d) => d,
            Err(e) => {
                error!("Failed to read plugin directory: {}", e);
                return plugins;
            }
        };

        for entry in read_dir.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("wasm") {
                match self.load_plugin(&path) {
                    Ok(plugin) => {
                        info!("Loaded plugin: {}", plugin.name());
                        plugins.push(plugin);
                    }
                    Err(e) => {
                        error!("Failed to load plugin {:?}: {}", path, e);
                    }
                }
            }
        }

        plugins
    }
}

struct WasmPlugin {
    module: Module,
    engine: Engine,
    name: String,
    version: String,
}

impl PluginEvaluator for WasmPlugin {
    fn name(&self) -> &str {
        &self.name
    }

    fn version(&self) -> &str {
        &self.version
    }

    fn evaluate(&self, signal: &SignalGenome) -> StrategyVote {
        // Serialize signal context for WASM
        let signal_json = match serde_json::to_vec(signal) {
            Ok(j) => j,
            Err(_) => return StrategyVote::neutral("Failed to serialize signal"),
        };

        // Create WASM store and instance
        let mut store = Store::new(&self.engine, ());
        let instance = match Instance::new(&mut store, &self.module, &[]) {
            Ok(i) => i,
            Err(e) => {
                error!("Failed to instantiate WASM plugin: {}", e);
                return StrategyVote::neutral("Plugin instantiation failed");
            }
        };

        // Write signal data to WASM memory and call evaluate function
        // This is a simplified version; production would use WASI for proper I/O
        if let Ok(evaluate_fn) = instance.get_typed_func::<(i32, i32), i32>(&mut store, "evaluate") {
            let memory = instance.get_memory(&mut store, "memory");

            if let Some(mem) = memory {
                let len = signal_json.len() as i32;
                let offset = 0_i32; // Write at start of memory

                if mem.write(&mut store, offset as usize, &signal_json).is_ok() {
                    match evaluate_fn.call(&mut store, (offset, len)) {
                        Ok(result_code) => {
                            return interpret_result_code(result_code);
                        }
                        Err(e) => {
                            error!("WASM evaluate failed: {}", e);
                        }
                    }
                }
            }
        }

        StrategyVote::neutral("Plugin execution failed")
    }
}

fn interpret_result_code(code: i32) -> StrategyVote {
    match code {
        1 => StrategyVote::bullish(0.8, "WASM plugin: strong buy signal"),
        2 => StrategyVote::bullish(0.6, "WASM plugin: moderate buy signal"),
        3 => StrategyVote::neutral("WASM plugin: neutral"),
        4 => StrategyVote::bearish(0.6, "WASM plugin: moderate sell signal"),
        5 => StrategyVote::bearish(0.8, "WASM plugin: strong sell signal"),
        _ => StrategyVote::neutral("WASM plugin: unknown signal"),
    }
}

// ═══════════════════════════════════════════════════════════════
// BUILT-IN STRATEGY PLUGINS (Native Rust — fastest path)
// ═══════════════════════════════════════════════════════════════

/// RSI + Volume confirmation strategy
pub struct RsiVolumePlugin;

impl PluginEvaluator for RsiVolumePlugin {
    fn name(&self) -> &str {
        "rsi_volume"
    }

    fn version(&self) -> &str {
        "1.0.0"
    }

    fn evaluate(&self, signal: &SignalGenome) -> StrategyVote {
        let rsi = signal.get_indicator("rsi_14");
        let vol_ratio = signal.get_indicator("volume_ratio_24h");

        if rsi > 65.0 && rsi < 80.0 && vol_ratio > 2.5 {
            StrategyVote::bullish(
                0.78,
                "RSI in bullish momentum zone with strong volume confirmation",
            )
        } else if rsi > 80.0 {
            StrategyVote::bearish(0.65, "RSI overbought — fade the move")
        } else if rsi < 30.0 {
            StrategyVote::bullish(0.55, "RSI oversold — potential reversal")
        } else {
            StrategyVote::neutral("RSI neutral zone — insufficient signal")
        }
    }
}

/// Whale accumulation detection strategy
pub struct WhaleAccumulationPlugin;

impl PluginEvaluator for WhaleAccumulationPlugin {
    fn name(&self) -> &str {
        "whale_accumulation"
    }

    fn version(&self) -> &str {
        "1.0.0"
    }

    fn evaluate(&self, signal: &SignalGenome) -> StrategyVote {
        let whale_count = signal.get_indicator("whale_buyers_24h");
        let smart_money_flow = signal.get_indicator("smart_money_flow");
        let exchange_outflow = signal.get_indicator("exchange_outflow_usd");

        // Strong whale accumulation: multiple smart money wallets + exchange outflows
        if whale_count >= 3.0 && smart_money_flow > 0.0 && exchange_outflow > 1_000_000.0 {
            StrategyVote::bullish(
                0.85,
                "Multiple whale wallets accumulating with significant exchange outflows",
            )
        } else if whale_count >= 2.0 && smart_money_flow > 0.0 {
            StrategyVote::bullish(0.65, "Whale accumulation detected")
        } else if smart_money_flow < -0.5 {
            StrategyVote::bearish(0.70, "Smart money distributing — exit signal")
        } else {
            StrategyVote::neutral("No significant whale activity")
        }
    }
}

/// Narrative momentum strategy — rides macro/crypto narratives
pub struct NarrativeMomentumPlugin;

impl PluginEvaluator for NarrativeMomentumPlugin {
    fn name(&self) -> &str {
        "narrative_momentum"
    }

    fn version(&self) -> &str {
        "1.0.0"
    }

    fn evaluate(&self, signal: &SignalGenome) -> StrategyVote {
        let narrative_score = signal.get_indicator("narrative_momentum");
        let social_velocity = signal.get_indicator("social_velocity_score");
        let days_since_narrative = signal.get_indicator("narrative_age_days");

        if narrative_score > 0.8 && social_velocity > 0.7 && days_since_narrative < 7.0 {
            StrategyVote::bullish(
                0.72,
                "Fresh narrative with high social velocity — early momentum play",
            )
        } else if narrative_score > 0.6 && days_since_narrative > 14.0 {
            StrategyVote::bearish(
                0.55,
                "Aging narrative — late to the party, risk of reversal",
            )
        } else {
            StrategyVote::neutral("Narrative signals inconclusive")
        }
    }
}

pub fn get_builtin_plugins() -> Vec<Box<dyn PluginEvaluator>> {
    vec![
        Box::new(RsiVolumePlugin),
        Box::new(WhaleAccumulationPlugin),
        Box::new(NarrativeMomentumPlugin),
    ]
}
