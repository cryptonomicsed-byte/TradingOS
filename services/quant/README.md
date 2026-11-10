# services/quant -- ares-quant-julia (TradingOSQuant)

Julia HTTP backtest engine consumed by Vantage `backend/quant_client.py`.
Read-only analytics (class INTEL): it computes over the candles in the request,
makes no outbound network calls, keeps no state and places no orders.

| | |
|---|---|
| Service | `ares-quant-julia` |
| Package | `julia/TradingOSQuant` (Julia >= 1.10, HTTP.jl 1.x or 2.x, JSON3) |
| Bind | `JULIA_HOST:JULIA_PORT`, default `127.0.0.1:8083` (loopback only by default) |
| Service flag | `QUANT_JULIA_ENABLED` -- `src/server.jl` exits 0 without binding unless `1/true/yes/on` |
| Vantage flag | `QUANT_JULIA_ENABLED` in **Vantage's** env (default off). Off = `quant_client` never makes a request; `/api/intel/quant/*` return `{"enabled": false}` |
| Vantage URL | `QUANT_JULIA_URL` (default `http://127.0.0.1:8083`), `QUANT_JULIA_TIMEOUT_S` (10), `QUANT_JULIA_CACHE_S` (300) |
| Unit | `deploy/ares-quant-julia.service.example` (repo root) -- example only, not installed |

## Provenance

`julia/TradingOSQuant` started as the copy vendored in Vantage
`services/quant/julia/TradingOSQuant` (Vantage `0148f4a`, from
`cryptonomicsed-byte/kanban` `services/julia/TradingOSQuant` @ `06c0fba`); the
first commit on this branch imports it verbatim. The older stub on
`archive/apps-services-infra-layout` (`services/julia/TradingOSQuant`, mocked
metrics) is superseded and was not used. Changes on top of the vendored copy:

* `Project.toml`: fixed the `Test` UUID (the vendored one was invalid, so
  `Pkg.test()` could not resolve), dropped unused `DataFrames`/`StatsBase`/
  `BenchmarkTools`, HTTP compat `1, 2`.
* Backtest engine: short exits now fill like long exits (both at the bar close
  that triggered the locked stop/target -- the vendored long side assumed a fill
  exactly at the stop/target level even when the close had gapped past it);
  equity is marked to market while a position is open; per-trade records and
  the open position are returned; Sortino uses downside deviation; undefined
  ratios are NaN/Inf internally and `null` on the wire (JSON has no NaN/Inf, and
  the vendored server would emit invalid JSON for e.g. profit factor with no
  losing trades); optional `bars_per_year` annualisation parameter.
* HTTP layer moved into `TradingOSQuant.Server` (testable, `start(; host, port)`
  is non-blocking), with input validation (400s) and JSON 404/405/413/500.
* `src/server.jl` is now only the entry point and is default-off.

## Contract

`GET /health` -> `200 {"status":"ok","service":"julia-quant","engine":"TradingOSQuant","version":"0.2.0","endpoints":[...],"read_only":true}`

`POST /backtest` (exactly what `quant_client.candles_to_body` sends):

```json
{"ticker": "BTC",
 "params": {"hma_len": 14, "mom_req": 3, "vol_req": 1, "sl_mult": 2.0, "tp_mult": 3.0, "min_adx": 20.0},
 "open": [..], "high": [..], "low": [..], "close": [..], "volume": [..]}
```

* Arrays: equal length, 60..100000 bars, finite numbers, prices > 0, volume >= 0
  (`volume` optional, defaults to zeros).
* `params` (all optional; out-of-range -> 400, unknown keys ignored). Bounds for
  the first six match `quant_client.PARAM_BOUNDS`: `hma_len` int 2..200,
  `mom_req` int 0..4, `vol_req` int 0..2, `sl_mult` 0.1..20, `tp_mult` 0.1..50,
  `min_adx` 0..100. Direct callers may also pass `use_fib` (bool),
  `commission_pct` 0..0.1 (default 0.001 per side), `initial_capital`
  (default 10000), `bars_per_year` (default 6048 = 252*24, the original
  hourly scaling; quant_client does not forward it, so Vantage's 1d candles get
  hourly-scaled Sharpe/Sortino -- compare them relatively, not absolutely).

Response `200` -- the twelve keys `quant_client._RESULT_KEYS` reads:
`sharpe_ratio, sortino_ratio, max_drawdown_pct, profit_factor, win_rate,
total_trades, winning_trades, losing_trades, net_profit, net_profit_pct,
calmar_ratio, avg_trade_duration_bars`, plus `ticker` and extras the client
ignores: `total_return_pct, final_equity, equity_curve[], trades[]
{side, entry_bar, exit_bar, entry_price, exit_price, pnl_pct, exit_reason},
open_position, bars, warmup_bars, params (effective), engine, version`.
Percent fields are percents (`max_drawdown_pct: 8.0` = 8%); `win_rate` is a
fraction 0..1. Undefined values are `null`.

Errors: non-200 with `{"error": "..."}` -- 400 invalid JSON/fields/params or
< 60 bars, 404 unknown path, 405 wrong method, 413 body > 16 MiB, 500 engine
failure. quant_client maps any non-200 to `{"ok": false, "error": "ares-quant-julia HTTP <code>"}`.

Strategy (Ògún Master Forge v2): HMA slope + Ichimoku cloud direction + ADX
filter, gated by momentum (HMA-MACD, RSI, MFI, Stochastic) and volume (BB
middle + OBV, rolling VWAP) scores; ATR stop/target locked at entry; one
position at a time, long or short; 52 warm-up bars. Deterministic: same
request -> byte-identical response. Walk-forward and calibration/Brier are not
part of the contract and are not implemented.

## Tests

    cd services/quant/julia/TradingOSQuant
    julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.test()'

`test/runtests.jl` covers indicators, engine invariants (determinism,
PnL/equity/drawdown recomputed independently), request validation, a real HTTP
round-trip on an ephemeral 127.0.0.1 port, and that `server.jl` is default-off.

Contract test with Vantage's real client (Vantage is only imported, never modified):

    PYTHONPATH=/path/to/Vantage /opt/ares/venv/bin/python -m pytest -q test/contract

It starts `src/server.jl` on an ephemeral port with `QUANT_JULIA_ENABLED=1`
set only in the child process env.
