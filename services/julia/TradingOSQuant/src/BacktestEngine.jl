module BacktestEngine

export run_simulation

struct Trade
    ticker::String
    side::String
    entry_price::Float64
    exit_price::Float64
    entry_time::Int64
    exit_time::Int64
    pnl::Float64
end

function run_simulation(prices::Vector{Float64}, signals::Vector{Int}, initial_capital::Float64=10000.0)
    capital = initial_capital
    position = 0.0
    trades = Trade[]
    entry_price = 0.0
    entry_time = 0
    
    for i in 1:length(prices)
        signal = signals[i]
        price = prices[i]
        
        if signal == 1 && position == 0.0 # Buy
            entry_price = price
            entry_time = i
            position = capital / price
            capital = 0.0
        elseif signal == -1 && position > 0.0 # Sell
            exit_price = price
            pnl = position * exit_price - initial_capital
            push!(trades, Trade("BTCUSDT", "LONG", entry_price, exit_price, entry_time, i, pnl))
            capital = position * exit_price
            position = 0.0
        end
    end
    
    # Calculate metrics
    total_pnl = capital + (position * (length(prices) > 0 ? prices[end] : 0.0)) - initial_capital
    return (trades=trades, total_pnl=total_pnl, profit_factor=1.5) # Mocked metrics
end

end # module
