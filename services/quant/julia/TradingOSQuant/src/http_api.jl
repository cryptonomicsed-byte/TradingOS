"""
HTTP API for ares-quant-julia. Contract (Vantage backend/quant_client.py):

    GET  /health    -> 200 {"status":"ok","service":"julia-quant",...}
    POST /backtest  <- {"ticker", "params", "open", "high", "low", "close", "volume"}
                    -> 200 {"ticker", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                            "profit_factor", "win_rate", "total_trades", "winning_trades",
                            "losing_trades", "net_profit", "net_profit_pct", "calmar_ratio",
                            "avg_trade_duration_bars", ...extras}

Errors are JSON objects {"error": "..."} with a non-200 status (400 bad input,
404/405 routing, 413 body too large, 500 engine failure). Undefined ratios
(NaN/Inf, e.g. profit factor with no losing trades) are serialised as null.
Read-only analytics: no network calls, no state, no orders.
"""
module Server

using HTTP
using JSON3
using Logging
using ..TradingOSQuant: BacktestParams, run_backtest, Trade, WARMUP_BARS

const SERVICE = "julia-quant"
const ENGINE = "TradingOSQuant"
const VERSION_STR = "0.2.0"
const MIN_BARS = 60           # mirrors quant_client.MIN_BARS
const MAX_BARS = 100_000
const MAX_BODY_BYTES = 16 * 1024 * 1024
const JSON_HDR = ["Content-Type" => "application/json"]

# name => (type, lo, hi). The first six are exactly quant_client.PARAM_BOUNDS.
const PARAM_SPEC = (
    hma_len         = (Int, 2, 200),
    mom_req         = (Int, 0, 4),
    vol_req         = (Int, 0, 2),
    sl_mult         = (Float64, 0.1, 20.0),
    tp_mult         = (Float64, 0.1, 50.0),
    min_adx         = (Float64, 0.0, 100.0),
    commission_pct  = (Float64, 0.0, 0.1),
    initial_capital = (Float64, 1.0, 1.0e12),
    bars_per_year   = (Float64, 1.0, 1.0e7),
)

struct BadRequest <: Exception
    msg::String
end

json_response(status::Int, payload) = HTTP.Response(status, JSON_HDR, JSON3.write(payload))
err(status::Int, msg::AbstractString) = json_response(status, Dict("error" => String(msg)))

finite_or_nothing(x::Real) = isfinite(x) ? Float64(x) : nothing

function to_float_vector(body, key::Symbol; required::Bool=true, n::Union{Nothing,Int}=nothing)
    if !haskey(body, key) || body[key] === nothing
        required && throw(BadRequest("missing field '$key'"))
        return zeros(Float64, something(n, 0))
    end
    raw = body[key]
    raw isa AbstractVector || throw(BadRequest("'$key' must be an array of numbers"))
    out = Vector{Float64}(undef, length(raw))
    for (i, v) in enumerate(raw)
        (v isa Real && !(v isa Bool)) || throw(BadRequest("'$key'[$i] is not a number"))
        isfinite(v) || throw(BadRequest("'$key'[$i] is not finite"))
        out[i] = Float64(v)
    end
    out
end

function parse_param(name::Symbol, v, spec)
    T, lo, hi = spec
    (v isa Real && !(v isa Bool)) || throw(BadRequest("param '$name' must be a number"))
    isfinite(v) || throw(BadRequest("param '$name' must be finite"))
    if T === Int
        isinteger(v) || throw(BadRequest("param '$name' must be an integer"))
        x = Int(v)
    else
        x = Float64(v)
    end
    lo <= x <= hi || throw(BadRequest("param '$name' out of range [$lo, $hi]"))
    x
end

"""Build BacktestParams from the request's `params` object (unknown keys ignored)."""
function parse_params(p)
    p === nothing && return BacktestParams(), Dict{String,Any}()
    p isa AbstractDict || throw(BadRequest("'params' must be an object"))
    kw = Dict{Symbol,Any}()
    for (name, spec) in pairs(PARAM_SPEC)
        v = get(p, name, nothing)
        v === nothing || (kw[name] = parse_param(name, v, spec))
    end
    uf = get(p, :use_fib, nothing)
    if uf !== nothing
        uf isa Bool || throw(BadRequest("param 'use_fib' must be a boolean"))
        kw[:use_fib] = uf
    end
    bp = BacktestParams(; kw...)
    effective = Dict{String,Any}(String(k) => getfield(bp, k) for k in fieldnames(BacktestParams))
    bp, effective
end

trade_json(t::Trade) = Dict(
    "side" => t.side == 1 ? "long" : "short",
    "entry_bar" => t.entry_bar,
    "exit_bar" => t.exit_bar == 0 ? nothing : t.exit_bar,
    "entry_price" => t.entry_price,
    "exit_price" => t.exit_price,
    "pnl_pct" => finite_or_nothing(t.pnl_pct),
    "exit_reason" => t.exit_reason,
)

"""Pure request -> response-dict function (no HTTP); throws BadRequest on bad input."""
function backtest_payload(body)
    body isa AbstractDict || throw(BadRequest("request body must be a JSON object"))
    tk = get(body, :ticker, "UNKNOWN")
    ticker = tk isa AbstractString ? first(String(tk), 32) : throw(BadRequest("'ticker' must be a string"))
    bp, effective = parse_params(get(body, :params, nothing))

    close_v = to_float_vector(body, :close)
    n = length(close_v)
    n >= MIN_BARS || throw(BadRequest("insufficient bars: got $n, need >= $MIN_BARS"))
    n <= MAX_BARS || throw(BadRequest("too many bars: got $n, max $MAX_BARS"))
    open_v = to_float_vector(body, :open)
    high_v = to_float_vector(body, :high)
    low_v = to_float_vector(body, :low)
    volume_v = to_float_vector(body, :volume; required=false, n=n)
    for (k, v) in ((:open, open_v), (:high, high_v), (:low, low_v), (:volume, volume_v))
        length(v) == n || throw(BadRequest("'$k' has $(length(v)) values, 'close' has $n"))
    end
    for (k, v) in ((:open, open_v), (:high, high_v), (:low, low_v), (:close, close_v))
        all(>(0.0), v) || throw(BadRequest("'$k' must be strictly positive"))
    end
    all(>=(0.0), volume_v) || throw(BadRequest("'volume' must be non-negative"))

    r = run_backtest(open_v, high_v, low_v, close_v, volume_v, bp)
    Dict{String,Any}(
        "ticker"                  => ticker,
        # ── contract keys read by quant_client._RESULT_KEYS ──
        "sharpe_ratio"            => finite_or_nothing(r.sharpe_ratio),
        "sortino_ratio"           => finite_or_nothing(r.sortino_ratio),
        "max_drawdown_pct"        => finite_or_nothing(r.max_drawdown_pct),
        "profit_factor"           => finite_or_nothing(r.profit_factor),
        "win_rate"                => finite_or_nothing(r.win_rate),
        "total_trades"            => r.total_trades,
        "winning_trades"          => r.winning_trades,
        "losing_trades"           => r.losing_trades,
        "net_profit"              => finite_or_nothing(r.net_profit),
        "net_profit_pct"          => finite_or_nothing(r.net_profit_pct),
        "calmar_ratio"            => finite_or_nothing(r.calmar_ratio),
        "avg_trade_duration_bars" => finite_or_nothing(r.avg_trade_duration_bars),
        # ── extras (ignored by quant_client, useful to direct callers) ──
        "total_return_pct"        => finite_or_nothing(r.net_profit_pct),
        "final_equity"            => finite_or_nothing(r.final_equity),
        "equity_curve"            => [finite_or_nothing(x) for x in r.equity_curve],
        "trades"                  => [trade_json(t) for t in r.trades],
        "open_position"           => r.open_position === nothing ? nothing : trade_json(r.open_position),
        "bars"                    => n,
        "warmup_bars"             => WARMUP_BARS,
        "params"                  => effective,
        "engine"                  => ENGINE,
        "version"                 => VERSION_STR,
    )
end

handle_health(::HTTP.Request) = json_response(200, Dict(
    "status" => "ok", "service" => SERVICE, "engine" => ENGINE, "version" => VERSION_STR,
    "endpoints" => ["GET /health", "POST /backtest"], "read_only" => true))

# HTTP.jl 1.x hands handlers a Vector{UInt8}; 2.x a BytesBody wrapper (whose
# `.data` is the vector). JSON3.read has no method for the wrapper.
function body_bytes(b)::Vector{UInt8}
    b isa AbstractVector{UInt8} && return b
    hasproperty(b, :data) && getproperty(b, :data) isa AbstractVector{UInt8} && return getproperty(b, :data)
    Vector{UInt8}(b)
end

function handle_backtest(req::HTTP.Request)
    raw = try
        body_bytes(req.body)
    catch
        return err(400, "unreadable request body")
    end
    length(raw) > MAX_BODY_BYTES && return err(413, "request body too large")
    isempty(raw) && return err(400, "empty request body")
    body = try
        JSON3.read(raw)
    catch
        return err(400, "invalid JSON body")
    end
    try
        json_response(200, backtest_payload(body))
    catch e
        e isa BadRequest && return err(400, e.msg)
        e isa ArgumentError && return err(400, e.msg)
        @error "backtest failed" exception = (e, catch_backtrace())
        err(500, "backtest failed: $(typeof(e))")
    end
end

function router()
    r = HTTP.Router(_ -> err(404, "not found"), _ -> err(405, "method not allowed"))
    HTTP.register!(r, "GET", "/health", handle_health)
    HTTP.register!(r, "POST", "/backtest", handle_backtest)
    r
end

"""
Compile the backtest path before listening, so the first real request is not
eaten by JIT time (quant_client's default timeout is 10 s). Uses a fixed
synthetic series; the result is discarded.
"""
function warmup()
    n = 120
    c = [100.0 + 10.0 * sin(i / 9) + i / 10 for i in 1:n]
    body = Dict("ticker" => "WARMUP", "params" => Dict("hma_len" => 14),
                "open" => c, "high" => c .+ 1.0, "low" => c .- 1.0, "close" => c, "volume" => fill(1.0, n))
    JSON3.write(backtest_payload(JSON3.read(JSON3.write(body))))
    nothing
end

"""Start a non-blocking server; returns the HTTP.Server (close with `close(server)`)."""
function start(; host::AbstractString="127.0.0.1", port::Integer=8083)
    @info "ares-quant-julia listening" host = host port = port
    HTTP.serve!(router(), host, port)
end

end # module Server
