defmodule TradingOS.Engine.ConfluenceMatrix do
  use GenServer
  require Logger

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def init(_opts) do
    # Default parameters derived from Phase 8 Strategy Forge
    {:ok, %{
      active_params: %{hma_len: 14, mom_req: 3, vol_req: 1, sl_mult: 2.0},
      signals: %{}
    }}
  end

  def inject_signal(ticker, source, score) do
    GenServer.cast(__MODULE__, {:inject_signal, ticker, source, score})
  end

  def handle_cast({:inject_signal, ticker, source, score}, state) do
    Logger.info("Received signal for #{ticker} from #{source}: #{score}")
    new_signals = Map.put(state.signals, {ticker, source}, score)
    
    # Logic to mutate parameters based on aggregate signals
    new_params = mutate_params(state.active_params, new_signals)
    
    {:noreply, %{state | signals: new_signals, active_params: new_params}}
  end

  defp mutate_params(params, _signals) do
    # Placeholder for dynamic parameter logic
    params
  end
end
