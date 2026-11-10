"""
Backtesting engine for the Ògún Master Forge v2 confluence strategy.

* Indicators are computed upfront; every decision at bar `i` uses data up to
  and including bar `i` only (no lookahead). Entries fill at `close[i]`.
* ATR stops/targets are locked at entry and never recalculated mid-trade.
* Exits are detected on the bar close and filled at that close (the engine
  does not look at intrabar high/low, so it does not assume a fill at the
  stop/target level). Long and short are treated symmetrically.
* The equity curve is marked to market every bar while a position is open,
  so drawdown/Sharpe reflect open risk, not only realised PnL.
* Deterministic: no randomness anywhere in `run_backtest`.
"""

using Statistics

const WARMUP_BARS = 52        # Ichimoku leading span B needs 52 bars
const DEFAULT_BARS_PER_YEAR = 252.0 * 24.0  # original kanban scaling (1 bar = 1h)

struct BacktestParams
    hma_len::Int
    mom_req::Int
    vol_req::Int
    use_fib::Bool
    sl_mult::Float64
    tp_mult::Float64
    min_adx::Float64
    commission_pct::Float64
    initial_capital::Float64
    bars_per_year::Float64
end

BacktestParams(; hma_len=14, mom_req=3, vol_req=1, use_fib=false,
               sl_mult=2.0, tp_mult=3.0, min_adx=20.0,
               commission_pct=0.001, initial_capital=10_000.0,
               bars_per_year=DEFAULT_BARS_PER_YEAR) =
    BacktestParams(hma_len, mom_req, vol_req, use_fib,
                   sl_mult, tp_mult, min_adx, commission_pct, initial_capital,
                   bars_per_year)

"""One closed (or, for `open_position`, still-open) trade. Bars are 1-based."""
struct Trade
    side::Int              # 1 = long, -1 = short
    entry_bar::Int
    exit_bar::Int          # 0 while open
    entry_price::Float64
    exit_price::Float64    # last close while open
    pnl_pct::Float64       # net of commission, percent of position
    exit_reason::String    # "stop" | "target" | "open"
end

struct BacktestResult
    sharpe_ratio::Float64
    sortino_ratio::Float64
    max_drawdown_pct::Float64
    profit_factor::Float64
    win_rate::Float64
    total_trades::Int
    winning_trades::Int
    losing_trades::Int
    net_profit::Float64
    net_profit_pct::Float64
    calmar_ratio::Float64
    avg_trade_duration_bars::Float64
    equity_curve::Vector{Float64}
    final_equity::Float64
    trades::Vector{Trade}
    open_position::Union{Nothing,Trade}
end

"""
    run_backtest(open, high, low, close, volume, params) → BacktestResult

Run the Ògún Master Forge v2 strategy against historical OHLCV data.
All five vectors must have the same length.
"""
function run_backtest(
    open_prices::Vector{Float64},
    high::Vector{Float64},
    low::Vector{Float64},
    close::Vector{Float64},
    volume::Vector{Float64},
    params::BacktestParams
)::BacktestResult
    n = length(close)
    all(length(v) == n for v in (open_prices, high, low, volume)) ||
        throw(ArgumentError("open/high/low/close/volume must have equal length"))
    equity = fill(params.initial_capital, n)
    trades = Trade[]

    # Compute all indicators upfront (vectorized)
    hma1 = calculate_hma(open_prices, params.hma_len)
    hma2 = vcat([NaN], hma1[1:end-1])  # shift by 1

    _, _, lead1, lead2 = calculate_ichimoku(high, low)
    macd, macd_sig = calculate_hma_macd(close)
    rsi_vals = calculate_rsi(close)
    mfi_vals = calculate_mfi(high, low, close, volume)
    stoch_k, _ = calculate_stochastic(high, low, close)
    _, bb_middle, _, _, _ = calculate_bollinger_bands(close)
    atr_vals = calculate_atr(high, low, close)
    adx_vals, _, _ = calculate_adx(high, low, close)
    obv_vals = calculate_obv(close, volume)
    obv_sma = calculate_rolling_sma(obv_vals, 20)
    rolling_vwap = calculate_rolling_vwap(high, low, close, volume)

    # Scoring helpers
    mom_long_score(i) =
        ((!isnan(macd[i]) && !isnan(macd_sig[i]) && macd[i] > macd_sig[i]) ? 1 : 0) +
        ((!isnan(rsi_vals[i]) && rsi_vals[i] > 50.0) ? 1 : 0) +
        ((!isnan(mfi_vals[i]) && mfi_vals[i] > 50.0) ? 1 : 0) +
        ((!isnan(stoch_k[i]) && stoch_k[i] > 50.0) ? 1 : 0)

    vol_long_score(i) =
        ((!isnan(bb_middle[i]) && close[i] > bb_middle[i] &&
          !isnan(obv_sma[i]) && obv_vals[i] > obv_sma[i]) ? 1 : 0) +
        ((!isnan(rolling_vwap[i]) && close[i] > rolling_vwap[i]) ? 1 : 0)

    # Trade simulation
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0.0
    locked_sl = 0.0
    locked_tp = 0.0
    entry_bar = 0
    capital = params.initial_capital
    c = params.commission_pct

    for i in (WARMUP_BARS + 1):n
        # 1. Exits first (stops/targets locked at entry, checked on close)
        if position != 0
            hit_sl = position == 1 ? close[i] <= locked_sl : close[i] >= locked_sl
            hit_tp = position == 1 ? close[i] >= locked_tp : close[i] <= locked_tp
            if hit_sl || hit_tp
                net_pnl = position * (close[i] - entry_price) / entry_price - 2c
                capital *= (1.0 + net_pnl)
                push!(trades, Trade(position, entry_bar, i, entry_price, close[i],
                                    net_pnl * 100.0, hit_sl ? "stop" : "target"))
                position = 0
            end
        end

        # 2. Entries (only when flat, only once all indicators are warm)
        warm = !any(isnan, (hma1[i], hma2[i], lead1[i], lead2[i], macd[i],
                            atr_vals[i], adx_vals[i]))
        if position == 0 && warm
            core_long = hma1[i] > hma2[i] && lead1[i] > lead2[i] && adx_vals[i] > params.min_adx
            core_short = hma1[i] < hma2[i] && lead1[i] < lead2[i] && adx_vals[i] > params.min_adx
            ml = mom_long_score(i)
            vl = vol_long_score(i)
            if core_long && ml >= params.mom_req && vl >= params.vol_req
                position = 1
            elseif core_short && (4 - ml) >= params.mom_req && (2 - vl) >= params.vol_req
                position = -1
            end
            if position != 0
                entry_price = close[i]
                entry_bar = i
                locked_sl = close[i] - position * atr_vals[i] * params.sl_mult
                locked_tp = close[i] + position * atr_vals[i] * params.tp_mult
            end
        end

        # 3. Mark to market (entry commission charged while open)
        equity[i] = position == 0 ? capital :
            capital * (1.0 + position * (close[i] - entry_price) / entry_price - c)
    end

    open_pos = position == 0 ? nothing :
        Trade(position, entry_bar, 0, entry_price, close[n],
              (position * (close[n] - entry_price) / entry_price - c) * 100.0, "open")

    compute_backtest_result(equity, trades, open_pos, params)
end

# Undefined ratios are NaN/Inf here; the HTTP layer serialises them as null.
function compute_backtest_result(
    equity::Vector{Float64},
    trades::Vector{Trade},
    open_pos::Union{Nothing,Trade},
    params::BacktestParams
)::BacktestResult
    initial_capital = params.initial_capital
    pnl = [t.pnl_pct / 100.0 for t in trades]
    winning = filter(p -> p > 0, pnl)
    losing = filter(p -> p <= 0, pnl)
    ntr = length(pnl)
    win_rate = ntr == 0 ? 0.0 : length(winning) / ntr

    gross_profit = sum(winning; init=0.0)
    gross_loss = abs(sum(losing; init=0.0))
    pf = ntr == 0 ? NaN : (gross_loss == 0.0 ? Inf : gross_profit / gross_loss)

    final_equity = isempty(equity) ? initial_capital : equity[end]
    net_profit = final_equity - initial_capital
    net_profit_pct = net_profit / initial_capital * 100.0

    # Per-bar returns of the marked-to-market curve after warm-up.
    live = length(equity) > WARMUP_BARS ? equity[WARMUP_BARS:end] : equity
    returns = length(live) < 2 ? Float64[] : diff(live) ./ live[1:end-1]
    ann = sqrt(params.bars_per_year)
    sharpe = if length(returns) < 2
        0.0
    else
        σ = std(returns)
        σ < 1e-12 ? 0.0 : mean(returns) / σ * ann
    end
    sortino = if length(returns) < 2
        0.0
    else
        dd = sqrt(mean(min.(returns, 0.0) .^ 2))  # downside deviation, target 0
        dd < 1e-12 ? (mean(returns) > 0 ? Inf : 0.0) : mean(returns) / dd * ann
    end

    max_dd = max_drawdown(equity)
    calmar = max_dd == 0.0 ? (net_profit > 0 ? Inf : 0.0) : (net_profit_pct / 100.0) / max_dd
    avg_duration = ntr == 0 ? 0.0 : mean(t.exit_bar - t.entry_bar for t in trades)

    BacktestResult(
        sharpe, sortino, max_dd * 100.0, pf, win_rate,
        ntr, length(winning), length(losing),
        net_profit, net_profit_pct, calmar, avg_duration, equity,
        final_equity, trades, open_pos
    )
end

# Helper not in other modules
function calculate_rolling_sma(series::Vector{Float64}, period::Int)::Vector{Float64}
    n = length(series)
    result = fill(NaN, n)
    for i in period:n
        window = filter(!isnan, series[(i - period + 1):i])
        if length(window) == period
            result[i] = mean(window)
        end
    end
    result
end
