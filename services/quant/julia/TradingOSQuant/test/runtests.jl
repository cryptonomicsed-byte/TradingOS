using Test
using Random
using Sockets
using HTTP
using JSON3
using TradingOSQuant

# ── Fixtures ─────────────────────────────────────────────────────────────────

function synthetic_ohlcv(n::Int=300; seed::Int=1)
    rng = MersenneTwister(seed)
    close = cumsum(randn(rng, n)) .+ 100.0
    close = max.(close, 1.0)
    high  = close .+ abs.(randn(rng, n)) .* 0.5
    low   = close .- abs.(randn(rng, n)) .* 0.5
    open  = vcat([close[1]], close[1:end-1])
    vol   = abs.(randn(rng, n)) .* 1_000.0 .+ 5_000.0
    (open=open, high=high, low=low, close=close, volume=vol)
end

# ── Moving Averages ───────────────────────────────────────────────────────────

@testset "WMA" begin
    d = synthetic_ohlcv()
    wma = calculate_wma(d.close, 14)
    @test length(wma) == length(d.close)
    @test all(isnan, wma[1:13])
    @test !isnan(wma[14])
end

@testset "HMA" begin
    d = synthetic_ohlcv()
    hma = calculate_hma(d.close, 14)
    @test length(hma) == length(d.close)
    @test !all(isnan, hma)
end

@testset "HMA-MACD" begin
    d = synthetic_ohlcv()
    macd, sig = calculate_hma_macd(d.close)
    @test length(macd) == length(d.close)
    @test length(sig) == length(d.close)
end

# ── Ichimoku ─────────────────────────────────────────────────────────────────

@testset "Ichimoku" begin
    d = synthetic_ohlcv()
    conv, base, l1, l2, top, bot = calculate_ichimoku(d.high, d.low)
    @test length(conv) == length(d.close)
    # Cloud top/bot should always have top >= bot where both valid
    for i in 1:length(top)
        if !isnan(top[i]) && !isnan(bot[i])
            @test top[i] >= bot[i]
        end
    end
end

# ── Oscillators ───────────────────────────────────────────────────────────────

@testset "RSI bounds" begin
    d = synthetic_ohlcv()
    rsi = calculate_rsi(d.close)
    valid = filter(!isnan, rsi)
    @test all(0.0 .<= valid .<= 100.0)
end

@testset "Stochastic bounds" begin
    d = synthetic_ohlcv()
    k, dd = calculate_stochastic(d.high, d.low, d.close)
    valid_k = filter(!isnan, k)
    @test all(0.0 .<= valid_k .<= 100.0)
end

@testset "MFI bounds" begin
    d = synthetic_ohlcv()
    mfi = calculate_mfi(d.high, d.low, d.close, d.volume)
    valid = filter(!isnan, mfi)
    @test all(0.0 .<= valid .<= 100.0)
end

# ── Volume ────────────────────────────────────────────────────────────────────

@testset "OBV monotone direction" begin
    # Constant-up price → OBV always increases
    n = 50
    close = collect(Float64, 1:n)
    vol = fill(1000.0, n)
    obv = calculate_obv(close, vol)
    @test all(diff(obv) .>= 0)
end

@testset "Rolling VWAP" begin
    d = synthetic_ohlcv()
    vwap = calculate_rolling_vwap(d.high, d.low, d.close, d.volume)
    @test length(vwap) == length(d.close)
    valid = filter(!isnan, vwap)
    @test all(v -> v > 0, valid)
end

# ── Volatility ────────────────────────────────────────────────────────────────

@testset "ATR positive" begin
    d = synthetic_ohlcv()
    atr = calculate_atr(d.high, d.low, d.close)
    valid = filter(!isnan, atr)
    @test all(v -> v >= 0, valid)
end

@testset "Bollinger pct_b range" begin
    d = synthetic_ohlcv()
    _, _, _, _, pct_b = calculate_bollinger_bands(d.close)
    # pct_b can go outside 0–1 on extreme moves; just check it's finite
    valid = filter(!isnan, pct_b)
    @test all(isfinite, valid)
end

@testset "ADX positive" begin
    d = synthetic_ohlcv()
    adx, _, _ = calculate_adx(d.high, d.low, d.close)
    valid = filter(!isnan, adx)
    @test all(v -> v >= 0, valid)
end

# ── Fibonacci ─────────────────────────────────────────────────────────────────

@testset "Fibonacci levels structure" begin
    d = synthetic_ohlcv(500)
    levels, dir = calculate_fibonacci_levels(d.high, d.low)
    @test dir in (-1, 0, 1)
    if !isnothing(levels)
        @test haskey(levels, "fib0618")
        @test haskey(levels, "fib10")
    end
end

# ── Backtest ──────────────────────────────────────────────────────────────────

@testset "Backtest runs without error" begin
    d = synthetic_ohlcv(500)
    params = BacktestParams()
    result = run_backtest(d.open, d.high, d.low, d.close, d.volume, params)
    @test result.total_trades >= 0
    @test 0.0 <= result.win_rate <= 1.0
    @test result.max_drawdown_pct >= 0.0
    @test length(result.equity_curve) == 500
end

# Trending fixture that reliably produces trades with the default params.
function trending_ohlcv(n::Int=400; seed::Int=7)
    rng = MersenneTwister(seed)
    # deterministic regime switches: up, down, up ...
    drift = [((i ÷ 80) % 2 == 0 ? 0.6 : -0.6) for i in 1:n]
    close = 200.0 .+ cumsum(drift .+ randn(rng, n) .* 0.8)
    high  = close .+ abs.(randn(rng, n)) .* 0.7 .+ 0.1
    low   = close .- abs.(randn(rng, n)) .* 0.7 .- 0.1
    open  = vcat([close[1]], close[1:end-1])
    vol   = abs.(randn(rng, n)) .* 1_000.0 .+ 5_000.0
    (open=open, high=high, low=low, close=close, volume=vol)
end

@testset "Backtest determinism and internal consistency" begin
    d = trending_ohlcv()
    p = BacktestParams(mom_req=2, vol_req=0, min_adx=15.0)
    r1 = run_backtest(d.open, d.high, d.low, d.close, d.volume, p)
    r2 = run_backtest(d.open, d.high, d.low, d.close, d.volume, p)
    @test r1.total_trades > 0
    @test r1.equity_curve == r2.equity_curve          # bit-identical reruns
    @test r1.sharpe_ratio === r2.sharpe_ratio
    @test r1.total_trades == length(r1.trades) == r1.winning_trades + r1.losing_trades
    @test r1.win_rate ≈ r1.winning_trades / r1.total_trades
    @test r1.final_equity == r1.equity_curve[end]
    @test r1.net_profit ≈ r1.final_equity - p.initial_capital
    @test r1.net_profit_pct ≈ r1.net_profit / p.initial_capital * 100
    # warm-up bars are flat at initial capital, no trade enters before bar 53
    @test all(==(p.initial_capital), r1.equity_curve[1:WARMUP_BARS])
    @test all(t -> t.entry_bar > WARMUP_BARS && t.exit_bar > t.entry_bar, r1.trades)
    # realised capital = product of per-trade net returns (when flat at the end)
    realised = p.initial_capital * prod(1 + t.pnl_pct / 100 for t in r1.trades)
    if r1.open_position === nothing
        @test r1.final_equity ≈ realised
    end
    # each trade's pnl matches its fill prices net of 2x commission
    for t in r1.trades
        @test t.pnl_pct / 100 ≈ t.side * (t.exit_price - t.entry_price) / t.entry_price - 2 * p.commission_pct
        @test t.exit_price == d.close[t.exit_bar] && t.entry_price == d.close[t.entry_bar]
        @test t.exit_reason in ("stop", "target")
    end
    # max drawdown recomputed independently from the equity curve
    peak = -Inf; mdd = 0.0
    for e in r1.equity_curve
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak)
    end
    @test r1.max_drawdown_pct ≈ mdd * 100
    @test 0.0 <= r1.max_drawdown_pct < 100.0
    # avg duration
    @test r1.avg_trade_duration_bars ≈ sum(t.exit_bar - t.entry_bar for t in r1.trades) / r1.total_trades
end

@testset "Backtest hand-checkable: flat market never trades" begin
    n = 120
    c = fill(100.0, n)
    r = run_backtest(copy(c), c .+ 1, c .- 1, c, fill(1000.0, n), BacktestParams())
    @test r.total_trades == 0
    @test r.net_profit == 0.0 && r.max_drawdown_pct == 0.0 && r.sharpe_ratio == 0.0
    @test isnan(r.profit_factor)          # undefined, serialised as null
    @test r.open_position === nothing
end

@testset "Backtest rejects ragged input" begin
    d = synthetic_ohlcv(100)
    @test_throws ArgumentError run_backtest(d.open[1:99], d.high, d.low, d.close, d.volume, BacktestParams())
end

# ── HTTP layer (pure) ─────────────────────────────────────────────────────────

const S = TradingOSQuant.Server

contract_body(d; params=Dict()) = Dict("ticker" => "BTC", "params" => params,
    "open" => d.open, "high" => d.high, "low" => d.low, "close" => d.close, "volume" => d.volume)

const RESULT_KEYS = ("sharpe_ratio", "sortino_ratio", "max_drawdown_pct", "profit_factor", "win_rate",
                     "total_trades", "winning_trades", "losing_trades", "net_profit", "net_profit_pct",
                     "calmar_ratio", "avg_trade_duration_bars")

@testset "backtest_payload contract + validation" begin
    d = trending_ohlcv()
    body = JSON3.read(JSON3.write(contract_body(d; params=Dict("mom_req" => 2, "vol_req" => 0, "min_adx" => 15.0))))
    out = S.backtest_payload(body)
    @test all(k -> haskey(out, k), RESULT_KEYS)
    @test out["ticker"] == "BTC" && out["bars"] == 400 && length(out["equity_curve"]) == 400
    direct = run_backtest(d.open, d.high, d.low, d.close, d.volume, BacktestParams(mom_req=2, vol_req=0, min_adx=15.0))
    @test out["total_trades"] == direct.total_trades
    @test out["net_profit"] == direct.net_profit
    @test out["params"]["mom_req"] == 2 && out["params"]["hma_len"] == 14

    bad(b) = try S.backtest_payload(JSON3.read(JSON3.write(b))); nothing catch e; e end
    short = contract_body(trending_ohlcv(59))
    @test bad(short) isa S.BadRequest
    ragged = contract_body(d); ragged["high"] = d.high[1:end-1]
    @test bad(ragged) isa S.BadRequest
    @test bad(contract_body(d; params=Dict("hma_len" => 9999))) isa S.BadRequest
    @test bad(contract_body(d; params=Dict("hma_len" => 2.5))) isa S.BadRequest
    @test bad(contract_body(d; params=Dict("sl_mult" => "2"))) isa S.BadRequest
    neg = contract_body(d); neg["close"] = vcat(-1.0, d.close[2:end])
    @test bad(neg) isa S.BadRequest
    nostr = contract_body(d); nostr["close"] = vcat("x", d.close[2:end])
    @test bad(nostr) isa S.BadRequest
    @test bad([1, 2]) isa S.BadRequest
    # volume optional; unknown params ignored
    nov = contract_body(d; params=Dict("evil" => 1)); delete!(nov, "volume")
    @test S.backtest_payload(JSON3.read(JSON3.write(nov)))["bars"] == 400
end

# ── HTTP round-trip on an ephemeral port ──────────────────────────────────────

function free_port()
    port, sock = Sockets.listenany(ip"127.0.0.1", 20000)
    close(sock)
    Int(port)
end

bytes(b) = copy(TradingOSQuant.Server.body_bytes(b))  # never let String() steal the buffer
rjson(r) = JSON3.read(bytes(r.body))
rtext(r) = String(bytes(r.body))

@testset "HTTP round-trip (ephemeral port)" begin
    @test S.warmup() === nothing
    port = free_port()
    server = S.start(; host="127.0.0.1", port=port)
    base = "http://127.0.0.1:$port"
    try
        h = HTTP.get("$base/health"; status_exception=false)
        @test h.status == 200
        hj = rjson(h)
        @test hj.status == "ok" && hj.service == "julia-quant"

        d = trending_ohlcv()
        body = JSON3.write(contract_body(d; params=Dict("hma_len" => 21, "sl_mult" => 2.5)))
        r = HTTP.post("$base/backtest", ["Content-Type" => "application/json"], body; status_exception=false)
        @test r.status == 200
        j = rjson(r)
        @test all(k -> haskey(j, Symbol(k)), RESULT_KEYS)
        direct = run_backtest(d.open, d.high, d.low, d.close, d.volume, BacktestParams(hma_len=21, sl_mult=2.5))
        @test j.total_trades == direct.total_trades
        @test j.net_profit_pct ≈ direct.net_profit_pct
        @test length(j.equity_curve) == 400
        # same request -> byte-identical response (deterministic)
        r2 = HTTP.post("$base/backtest", ["Content-Type" => "application/json"], body; status_exception=false)
        @test rtext(r2) == rtext(r)

        e = HTTP.post("$base/backtest", ["Content-Type" => "application/json"], "{not json"; status_exception=false)
        @test e.status == 400 && haskey(rjson(e), :error)
        e = HTTP.post("$base/backtest", ["Content-Type" => "application/json"],
                      JSON3.write(contract_body(trending_ohlcv(30))); status_exception=false)
        @test e.status == 400 && occursin("insufficient", rjson(e).error)
        e = HTTP.get("$base/nope"; status_exception=false)
        @test e.status == 404 && haskey(rjson(e), :error)
        e = HTTP.get("$base/backtest"; status_exception=false)
        @test e.status == 405
        # flat series -> undefined profit factor is JSON null, never NaN/Inf text
        c = fill(100.0, 80)
        fb = JSON3.write(Dict("ticker" => "FLAT", "open" => c, "high" => c .+ 1, "low" => c .- 1,
                              "close" => c, "volume" => fill(1.0, 80)))
        f = HTTP.post("$base/backtest", ["Content-Type" => "application/json"], fb; status_exception=false)
        @test f.status == 200
        @test !occursin("NaN", rtext(f)) && !occursin("Inf", rtext(f))
        @test rjson(f).profit_factor === nothing
    finally
        close(server)
    end
end

@testset "server.jl is default-off" begin
    jl = Base.julia_cmd()
    proj = dirname(@__DIR__)
    out = read(addenv(`$jl --project=$proj $(joinpath(proj, "src", "server.jl"))`,
                      "QUANT_JULIA_ENABLED" => "0"), String)
    @test occursin("QUANT_JULIA_ENABLED off", out)
    src = read(joinpath(proj, "src", "server.jl"), String)
    @test occursin("get(ENV, \"JULIA_HOST\", \"127.0.0.1\")", src)
end

# ── Risk Metrics ──────────────────────────────────────────────────────────────

@testset "Sharpe of constant returns" begin
    returns = fill(0.001, 100)
    sr = sharpe_ratio(returns)
    @test sr > 0
end

@testset "Max drawdown of monotone equity" begin
    equity = collect(Float64, 1:100)
    dd = max_drawdown(equity)
    @test dd == 0.0
end

@testset "Profit factor" begin
    pnl = [0.1, -0.05, 0.08, -0.03, 0.12]
    pf = profit_factor(pnl)
    @test pf > 1.0
end

# ── Position Sizing ───────────────────────────────────────────────────────────

@testset "Kelly fraction clamped" begin
    f = kelly_fraction(0.6, 0.1, 0.05)
    @test 0.0 <= f <= 0.25
end

@testset "ATR size positive" begin
    sz = atr_based_size(10_000.0, 100.0, 2.0, 2.0; risk_pct=0.01)
    @test sz > 0.0 && sz <= 1.0
end
