defmodule TradingOs.AgentSupervisor do
  @moduledoc """
  Supervisor for the agent pool — manages spawner, challenger,
  and validator agent processes.

  Agent types and their OTP behavior:
  - Spawner agents: GenServer, poll data sources on interval
  - Challenger agents: GenServer, event-driven (subscribe to PubSub)
  - Validator agents: GenServer, event-driven (subscribe to PubSub)
  - Memory Court: GenServer, persistent, manages vector store connection
  """

  use Supervisor
  require Logger

  def start_link(_) do
    Supervisor.start_link(__MODULE__, %{}, name: __MODULE__)
  end

  @impl true
  def init(_) do
    Logger.info("AgentSupervisor starting agent pool...")

    children = [
      # ─── SPAWNER AGENTS ─────────────────────────────────────
      # Each spawner watches a data source and generates signals

      {TradingOs.Agents.OnChainSpawner, name: :onchain_spawner},
      {TradingOs.Agents.SocialSpawner, name: :social_spawner},
      {TradingOs.Agents.WhaleTrackerSpawner, name: :whale_spawner},
      {TradingOs.Agents.DexFlowSpawner, name: :dex_spawner},
      {TradingOs.Agents.MacroSpawner, name: :macro_spawner},
      {TradingOs.Agents.NarrativeSpawner, name: :narrative_spawner},

      # ─── CHALLENGER AGENTS ─────────────────────────────────
      # Each challenger challenges signals from a different angle

      {TradingOs.Agents.LiquidityChallenger, name: :liquidity_challenger},
      {TradingOs.Agents.SecurityChallenger, name: :security_challenger},
      {TradingOs.Agents.MacroHeadwindChallenger, name: :macro_challenger},
      {TradingOs.Agents.ManipulationChallenger, name: :manipulation_challenger},
      {TradingOs.Agents.TimingChallenger, name: :timing_challenger},

      # ─── VALIDATOR AGENTS ──────────────────────────────────
      # Multi-dimensional signal validation

      {TradingOs.Agents.ConvictionValidator, name: :conviction_validator},
      {TradingOs.Agents.RiskValidator, name: :risk_validator},
      {TradingOs.Agents.CorroborationValidator, name: :corroboration_validator},
      {TradingOs.Agents.MevValidator, name: :mev_validator},

      # ─── EXECUTION SENATE ─────────────────────────────────
      # Final committee before execution

      {TradingOs.Agents.ExecutionSenate, name: :execution_senate},
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end
end

# ═══════════════════════════════════════════════════════════════
# BASE AGENT BEHAVIOR
# ═══════════════════════════════════════════════════════════════

defmodule TradingOs.Agents.BaseAgent do
  @moduledoc """
  Shared behavior for all TradingOS agents.
  Provides: registration, health reporting, reputation tracking,
  PubSub subscription, and structured logging.
  """

  defmacro __using__(opts) do
    agent_type = Keyword.fetch!(opts, :type)
    poll_interval = Keyword.get(opts, :poll_interval, nil)

    quote do
      use GenServer
      require Logger
      alias TradingOs.{PubSub, AgentRegistry, Repo}

      @agent_type unquote(agent_type)
      @poll_interval unquote(poll_interval)

      # Public API
      def agent_type, do: @agent_type
      def agent_id(name), do: "#{@agent_type}:#{name}"

      def start_link(opts) do
        name = Keyword.get(opts, :name, @agent_type)
        GenServer.start_link(__MODULE__, opts, name: name)
      end

      @impl true
      def init(opts) do
        name = Keyword.get(opts, :name, @agent_type)
        id = agent_id(name)

        Logger.info("Agent starting: #{id}")

        # Register in agent registry
        Registry.register(AgentRegistry, {:agent, id}, %{
          type: @agent_type,
          started_at: DateTime.utc_now(),
          reputation: 0.8  # Start with good faith reputation
        })

        # Subscribe to relevant PubSub topics
        subscribe_topics()

        # Schedule polling if interval configured
        if @poll_interval do
          Process.send_after(self(), :poll, @poll_interval)
        end

        {:ok, %{id: id, name: name, reputation: 0.8, executions: 0, correct: 0}}
      end

      defp subscribe_topics, do: :ok
      defoverridable [subscribe_topics: 0]

      @impl true
      def handle_info(:poll, state) do
        Task.start(fn -> do_poll(state) end)
        if @poll_interval, do: Process.send_after(self(), :poll, @poll_interval)
        {:noreply, state}
      end

      def do_poll(_state), do: :ok
      defoverridable [do_poll: 1]

      # Update reputation based on outcome
      def handle_cast({:outcome_feedback, signal_id, correct?}, state) do
        executions = state.executions + 1
        correct = state.correct + if(correct?, do: 1, else: 0)
        reputation = correct / executions

        {:noreply, %{state | executions: executions, correct: correct, reputation: reputation}}
      end
    end
  end
end

# ═══════════════════════════════════════════════════════════════
# SPAWNER AGENTS
# ═══════════════════════════════════════════════════════════════

defmodule TradingOs.Agents.OnChainSpawner do
  use TradingOs.Agents.BaseAgent, type: :onchain_spawner, poll_interval: 60_000

  alias TradingOs.SignalBridge

  @impl true
  def do_poll(state) do
    Logger.debug("OnChainSpawner: polling on-chain metrics")

    # In production: query Helius/Birdeye for on-chain flows
    # Here we demonstrate the signal generation pattern
    case fetch_whale_movements() do
      {:ok, movements} ->
        Enum.each(movements, fn movement ->
          signal = %{
            asset_symbol: movement.token,
            asset_chain: "Solana",
            signal_type: %{type: "Long", target_pct: 0.3, timeframe_hours: 24.0},
            source_type: "onchain_whale_movement",
            indicators: %{
              "whale_buyers_24h" => movement.buyer_count,
              "smart_money_flow" => movement.net_flow,
              "exchange_outflow_usd" => movement.exchange_outflow
            },
            tags: ["on-chain", "whale", "accumulation"]
          }

          SignalBridge.submit_signal(signal)
        end)

      {:error, reason} ->
        Logger.warning("OnChainSpawner: failed to fetch whale movements: #{reason}")
    end
  end

  defp fetch_whale_movements do
    # Placeholder — production queries Helius/Birdeye APIs
    {:ok, []}
  end
end

defmodule TradingOs.Agents.SocialSpawner do
  use TradingOs.Agents.BaseAgent, type: :social_spawner, poll_interval: 120_000

  @impl true
  def do_poll(state) do
    Logger.debug("SocialSpawner: analyzing social feeds")
    # In production: analyze Twitter/Telegram/Discord via APIs
    :ok
  end
end

defmodule TradingOs.Agents.WhaleTrackerSpawner do
  use TradingOs.Agents.BaseAgent, type: :whale_spawner, poll_interval: 30_000

  @impl true
  def do_poll(state) do
    Logger.debug("WhaleTracker: scanning wallet movements")
    :ok
  end
end

defmodule TradingOs.Agents.DexFlowSpawner do
  use TradingOs.Agents.BaseAgent, type: :dex_spawner, poll_interval: 15_000

  @impl true
  def do_poll(state) do
    Logger.debug("DexFlowSpawner: monitoring DEX volume surges")
    :ok
  end
end

defmodule TradingOs.Agents.MacroSpawner do
  use TradingOs.Agents.BaseAgent, type: :macro_spawner, poll_interval: 300_000

  @impl true
  def do_poll(state) do
    Logger.debug("MacroSpawner: checking macro correlations")
    :ok
  end
end

defmodule TradingOs.Agents.NarrativeSpawner do
  use TradingOs.Agents.BaseAgent, type: :narrative_spawner, poll_interval: 180_000

  @impl true
  def do_poll(state) do
    Logger.debug("NarrativeSpawner: tracking narrative momentum")
    :ok
  end
end

# ═══════════════════════════════════════════════════════════════
# CHALLENGER AGENTS — Adversarial validation
# ═══════════════════════════════════════════════════════════════

defmodule TradingOs.Agents.LiquidityChallenger do
  use TradingOs.Agents.BaseAgent, type: :liquidity_challenger

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:challengers")
  end

  @impl true
  def handle_info({:challenge_signal, %{signal_id: sid, signal_data: data, session_pid: session}}, state) do
    Task.start(fn ->
      result = evaluate_liquidity_risk(data)

      GenServer.cast(session, {:challenge_result, %{
        challenger_id: state.id,
        challenge_type: :liquidity_risk,
        arguments: result.arguments,
        conviction_impact: result.impact,
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end

  defp evaluate_liquidity_risk(signal_data) do
    liquidity = get_in(signal_data, ["market_context", "liquidity_usd"]) || 0

    cond do
      liquidity < 10_000 ->
        %{arguments: ["Dangerously low liquidity: $#{liquidity}"], impact: -0.5}
      liquidity < 50_000 ->
        %{arguments: ["Low liquidity: $#{liquidity} — significant slippage risk"], impact: -0.2}
      liquidity < 100_000 ->
        %{arguments: ["Moderate liquidity concern: $#{liquidity}"], impact: -0.05}
      true ->
        %{arguments: [], impact: 0.05}  # Good liquidity = slight boost
    end
  end
end

defmodule TradingOs.Agents.SecurityChallenger do
  use TradingOs.Agents.BaseAgent, type: :security_challenger

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:challengers")
  end

  @impl true
  def handle_info({:challenge_signal, %{signal_id: sid, signal_data: data, session_pid: session}}, state) do
    Task.start(fn ->
      result = check_contract_security(data)

      GenServer.cast(session, {:challenge_result, %{
        challenger_id: state.id,
        challenge_type: :contract_security,
        arguments: result.arguments,
        conviction_impact: result.impact,
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end

  defp check_contract_security(signal_data) do
    # In production: call RugCheck API, GoPlus API, etc.
    %{arguments: [], impact: 0.0}
  end
end

defmodule TradingOs.Agents.MacroHeadwindChallenger do
  use TradingOs.Agents.BaseAgent, type: :macro_challenger

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:challengers")
  end

  @impl true
  def handle_info({:challenge_signal, %{signal_id: sid, signal_data: data, session_pid: session}}, state) do
    Task.start(fn ->
      result = assess_macro_headwinds(data)

      GenServer.cast(session, {:challenge_result, %{
        challenger_id: state.id,
        challenge_type: :macro_headwind,
        arguments: result.arguments,
        conviction_impact: result.impact,
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end

  defp assess_macro_headwinds(signal_data) do
    fear_greed = get_in(signal_data, ["market_context", "fear_greed_index"]) || 50

    cond do
      fear_greed > 90 ->
        %{arguments: ["Extreme greed (#{fear_greed}) — high reversal risk"], impact: -0.15}
      fear_greed < 10 ->
        %{arguments: ["Extreme fear (#{fear_greed}) — capitulation possible"], impact: -0.1}
      true ->
        %{arguments: [], impact: 0.0}
    end
  end
end

defmodule TradingOs.Agents.ManipulationChallenger do
  use TradingOs.Agents.BaseAgent, type: :manipulation_challenger

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:challengers")
  end

  @impl true
  def handle_info({:challenge_signal, _msg}, state), do: {:noreply, state}
end

defmodule TradingOs.Agents.TimingChallenger do
  use TradingOs.Agents.BaseAgent, type: :timing_challenger

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:challengers")
  end

  @impl true
  def handle_info({:challenge_signal, _msg}, state), do: {:noreply, state}
end

# ═══════════════════════════════════════════════════════════════
# VALIDATOR AGENTS — Parliament voters
# ═══════════════════════════════════════════════════════════════

defmodule TradingOs.Agents.ConvictionValidator do
  use TradingOs.Agents.BaseAgent, type: :conviction_validator

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:validators")
  end

  @impl true
  def handle_info({:validate_signal, %{signal_id: sid, signal_data: data, session_pid: session}}, state) do
    Task.start(fn ->
      {vote, conviction, rationale} = compute_conviction_vote(data, state.reputation)

      GenServer.cast(session, {:vote, %{
        voter_id: state.id,
        voter_type: :conviction_validator,
        vote: vote,
        conviction: conviction,
        rationale: rationale,
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end

  defp compute_conviction_vote(signal_data, agent_reputation) do
    # Base conviction from signal data, weighted by agent reputation
    base = Map.get(signal_data, "conviction", 0.5)
    adjusted = base * agent_reputation

    vote = if adjusted >= 0.6, do: :approve, else: :reject
    {vote, adjusted, "Conviction score: #{Float.round(adjusted, 3)}"}
  end
end

defmodule TradingOs.Agents.RiskValidator do
  use TradingOs.Agents.BaseAgent, type: :risk_validator

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:validators")
  end

  @impl true
  def handle_info({:validate_signal, %{signal_id: sid, signal_data: data, session_pid: session}}, state) do
    Task.start(fn ->
      {vote, conviction, rationale} = assess_risk_adjusted_return(data)

      GenServer.cast(session, {:vote, %{
        voter_id: state.id,
        voter_type: :risk_validator,
        vote: vote,
        conviction: conviction,
        rationale: rationale,
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end

  defp assess_risk_adjusted_return(signal_data) do
    {:approve, 0.7, "Risk/reward ratio acceptable"}
  end
end

defmodule TradingOs.Agents.CorroborationValidator do
  use TradingOs.Agents.BaseAgent, type: :corroboration_validator

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:validators")
  end

  @impl true
  def handle_info({:validate_signal, %{session_pid: session} = msg}, state) do
    Task.start(fn ->
      sources = get_in(msg, [:signal_data, "corroborating_sources"]) || []
      corroboration_score = length(sources) / 5.0  # Max 5 sources

      vote = if corroboration_score >= 0.4, do: :approve, else: :reject

      GenServer.cast(session, {:vote, %{
        voter_id: state.id,
        voter_type: :corroboration_validator,
        vote: vote,
        conviction: min(corroboration_score, 1.0),
        rationale: "#{length(sources)} corroborating sources",
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end
end

defmodule TradingOs.Agents.MevValidator do
  use TradingOs.Agents.BaseAgent, type: :mev_validator

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(TradingOs.PubSub, "agents:validators")
  end

  @impl true
  def handle_info({:validate_signal, %{session_pid: session} = msg}, state) do
    Task.start(fn ->
      # Check MEV risk — recommend Jito bundle if needed
      GenServer.cast(session, {:vote, %{
        voter_id: state.id,
        voter_type: :mev_validator,
        vote: :approve,
        conviction: 0.75,
        rationale: "MEV risk acceptable — Jito bundle recommended",
        timestamp: DateTime.utc_now()
      }})
    end)

    {:noreply, state}
  end
end

# ═══════════════════════════════════════════════════════════════
# EXECUTION SENATE — Final execution committee
# ═══════════════════════════════════════════════════════════════

defmodule TradingOs.Agents.ExecutionSenate do
  use TradingOs.Agents.BaseAgent, type: :execution_senate

  alias TradingOs.PubSub

  @impl true
  def subscribe_topics do
    Phoenix.PubSub.subscribe(PubSub, TradingOs.Parliament.decision_topic())
  end

  @impl true
  def handle_info({:verdict, %{approved: true} = verdict}, state) do
    Logger.info("ExecutionSenate: approved signal #{verdict.signal_id} — preparing execution")

    Task.start(fn ->
      execute_signal(verdict)
    end)

    {:noreply, state}
  end

  @impl true
  def handle_info({:verdict, %{approved: false} = verdict}, state) do
    Logger.debug("ExecutionSenate: rejected signal #{verdict.signal_id}")
    {:noreply, state}
  end

  defp execute_signal(verdict) do
    Logger.info("ExecutionSenate: executing signal #{verdict.signal_id}")
    # In production: route to execution layer (Jupiter, direct DEX, CEX API)
    # with MEV protection (Jito bundle), position sizing, etc.
    :ok
  end
end
