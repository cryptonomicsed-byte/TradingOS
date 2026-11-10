"""
ares-quant-julia entry point: HTTP server for the TradingOSQuant backtest engine.

    QUANT_JULIA_ENABLED=1 julia --project=. src/server.jl

Default OFF: unless QUANT_JULIA_ENABLED is 1/true/yes/on this exits 0 without
binding anything. Bind address from JULIA_HOST (default 127.0.0.1, never
0.0.0.0 by default) and JULIA_PORT (default 8083).
"""

using TradingOSQuant

flag_on(v) = lowercase(strip(v)) in ("1", "true", "yes", "on")

function main()
    if !flag_on(get(ENV, "QUANT_JULIA_ENABLED", "0"))
        println("QUANT_JULIA_ENABLED off; ares-quant-julia not starting")
        return 0
    end
    host = get(ENV, "JULIA_HOST", "127.0.0.1")
    port = parse(Int, get(ENV, "JULIA_PORT", "8083"))
    TradingOSQuant.Server.warmup()   # JIT before binding: /health up == fast /backtest
    server = TradingOSQuant.Server.start(; host=host, port=port)
    try
        wait(server)
    catch e
        e isa InterruptException || rethrow()
    finally
        close(server)
    end
    return 0
end

if abspath(PROGRAM_FILE) == @__FILE__
    exit(main())
end
