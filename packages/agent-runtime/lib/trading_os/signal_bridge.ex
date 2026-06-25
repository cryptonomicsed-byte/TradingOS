defmodule TradingOs.SignalBridge do
  @moduledoc """
  HTTP bridge from Elixir Agent Runtime to Rust Signal Bus.
  Translates Elixir agent events into Signal Bus API calls.
  Also subscribes to the Signal Bus WebSocket to receive new signals.
  """

  use GenServer
  require Logger

  @reconnect_ms 5_000

  def start_link(_) do
    GenServer.start_link(__MODULE__, %{}, name: __MODULE__)
  end

  def submit_signal(signal_data) do
    GenServer.cast(__MODULE__, {:submit_signal, signal_data})
  end

  def update_signal_state(signal_id, new_state) do
    GenServer.cast(__MODULE__, {:update_state, signal_id, new_state})
  end

  def submit_vote(signal_id, vote_data) do
    GenServer.cast(__MODULE__, {:submit_vote, signal_id, vote_data})
  end

  @impl true
  def init(_) do
    bus_url = System.get_env("SIGNAL_BUS_URL", "http://signal-bus:7700")
    Logger.info("SignalBridge connecting to Signal Bus at #{bus_url}")

    # Start WebSocket subscription in background
    Task.start(fn -> connect_ws(bus_url) end)

    {:ok, %{bus_url: bus_url}}
  end

  @impl true
  def handle_cast({:submit_signal, signal_data}, state) do
    Task.start(fn ->
      url = "#{state.bus_url}/signals"
      case Req.post(url, json: signal_data) do
        {:ok, %{status: status, body: body}} when status in [200, 201] ->
          signal_id = Map.get(body, "id")
          Logger.debug("SignalBridge: submitted signal #{signal_id}")
          # Open parliament session for new signal
          TradingOs.Parliament.open_session(signal_id, signal_data)

        {:error, reason} ->
          Logger.warning("SignalBridge: failed to submit signal: #{inspect(reason)}")
      end
    end)
    {:noreply, state}
  end

  @impl true
  def handle_cast({:update_state, signal_id, new_state}, state) do
    Task.start(fn ->
      url = "#{state.bus_url}/signals/#{signal_id}/state"
      Req.put(url, json: %{new_state: new_state})
    end)
    {:noreply, state}
  end

  @impl true
  def handle_cast({:submit_vote, signal_id, vote_data}, state) do
    Task.start(fn ->
      url = "#{state.bus_url}/signals/#{signal_id}/vote"
      Req.post(url, json: vote_data)
    end)
    {:noreply, state}
  end

  defp connect_ws(bus_url) do
    ws_url = String.replace(bus_url, "http://", "ws://") <> "/ws"
    Logger.info("SignalBridge: connecting WebSocket to #{ws_url}")
    # In production: use mint/gun for WebSocket to receive real-time bus events
    # and dispatch them to the appropriate Parliament sessions
    :ok
  end
end

defmodule TradingOs.AgentEvolution do
  @moduledoc """
  Periodically evaluates agent performance and updates reputation scores.
  Agents with consistently poor predictions get retrained or replaced.
  """

  use GenServer
  require Logger

  @evolution_interval_ms 86_400_000  # 24 hours

  def start_link(_) do
    GenServer.start_link(__MODULE__, %{}, name: __MODULE__)
  end

  @impl true
  def init(_) do
    Process.send_after(self(), :evolve, @evolution_interval_ms)
    {:ok, %{generation: 0}}
  end

  @impl true
  def handle_info(:evolve, state) do
    Logger.info("AgentEvolution: Generation #{state.generation} — evaluating agent fitness")

    agents = Registry.select(TradingOs.AgentRegistry, [{{:agent, :"$1"}, [], [:"$1"]}])

    Enum.each(agents, fn agent_key ->
      case Registry.lookup(TradingOs.AgentRegistry, {:agent, agent_key}) do
        [{_pid, meta}] ->
          reputation = Map.get(meta, :reputation, 0.5)
          if reputation < 0.3 do
            Logger.warning("AgentEvolution: Agent #{agent_key} has low reputation #{reputation} — flagging for review")
            # In production: trigger retraining or replacement
          end
        _ -> :ok
      end
    end)

    Process.send_after(self(), :evolve, @evolution_interval_ms)
    {:noreply, %{state | generation: state.generation + 1}}
  end
end
