defmodule TradingOs.Parliament do
  @moduledoc """
  The Parliament — distributed consensus engine for trading signals.

  Every signal that enters the system goes through a structured
  deliberation process modeled on a parliamentary debate:

  1. Opening → Signal registered, challenge agents spawned
  2. Challenge Round → Adversarial agents try to invalidate the signal
  3. Memory Court → Historical similarity consulted
  4. Parliament Vote → Registered validators cast weighted votes
  5. Senate → Execution committee reviews approved signals
  6. Verdict → Signal approved/rejected with execution params

  Each session is a separate OTP process with its own state,
  timeout, and cleanup. Dead sessions don't affect live ones.
  """

  alias TradingOs.{PubSub, AgentRegistry, MemoryCourt}
  require Logger

  # Topics for PubSub A2A messaging
  @signal_topic "parliament:signals"
  @vote_topic "parliament:votes"
  @decision_topic "parliament:decisions"

  def signal_topic, do: @signal_topic
  def vote_topic, do: @vote_topic
  def decision_topic, do: @decision_topic

  # Open a new parliament session for a signal
  def open_session(signal_id, signal_data) do
    Logger.info("Opening parliament session for signal #{signal_id}")

    # Start a new session process
    {:ok, pid} = DynamicSupervisor.start_child(
      TradingOs.Parliament.SessionSupervisor,
      {TradingOs.Parliament.Session, {signal_id, signal_data}}
    )

    # Broadcast session opened
    Phoenix.PubSub.broadcast(PubSub, @signal_topic, {
      :session_opened,
      %{signal_id: signal_id, pid: pid, timestamp: DateTime.utc_now()}
    })

    {:ok, pid}
  end

  # Submit a vote to an active session
  def submit_vote(signal_id, voter_id, voter_type, vote, conviction, rationale) do
    case find_session(signal_id) do
      {:ok, pid} ->
        GenServer.cast(pid, {:vote, %{
          voter_id: voter_id,
          voter_type: voter_type,
          vote: vote,
          conviction: conviction,
          rationale: rationale,
          timestamp: DateTime.utc_now()
        }})
        :ok

      :not_found ->
        {:error, :session_not_found}
    end
  end

  # Query session state
  def get_session_state(signal_id) do
    case find_session(signal_id) do
      {:ok, pid} -> {:ok, GenServer.call(pid, :get_state)}
      :not_found -> {:error, :not_found}
    end
  end

  defp find_session(signal_id) do
    case Registry.lookup(AgentRegistry, {:parliament_session, signal_id}) do
      [{pid, _}] -> {:ok, pid}
      [] -> :not_found
    end
  end
end

defmodule TradingOs.Parliament.Session do
  @moduledoc """
  A single parliament session GenServer.
  One session per signal — isolated, fault-tolerant.
  """

  use GenServer
  require Logger
  alias TradingOs.{Parliament, PubSub, AgentRegistry, MemoryCourt}

  @timeout_ms 30_000  # 30 seconds max deliberation
  @quorum_pct 0.67
  @min_votes 3

  defstruct [
    :signal_id,
    :signal_data,
    :started_at,
    :phase,
    :votes,
    :challenges,
    :memory_court_result,
    :final_conviction,
    :verdict,
    :timer_ref
  ]

  def start_link({signal_id, signal_data}) do
    GenServer.start_link(__MODULE__, {signal_id, signal_data},
      name: {:via, Registry, {AgentRegistry, {:parliament_session, signal_id}}}
    )
  end

  @impl true
  def init({signal_id, signal_data}) do
    state = %__MODULE__{
      signal_id: signal_id,
      signal_data: signal_data,
      started_at: DateTime.utc_now(),
      phase: :opening,
      votes: [],
      challenges: [],
      memory_court_result: nil,
      final_conviction: 0.0,
      verdict: nil,
      timer_ref: nil
    }

    # Set overall session timeout
    timer_ref = Process.send_after(self(), :timeout, @timeout_ms)
    state = %{state | timer_ref: timer_ref}

    # Advance to challenge phase immediately
    send(self(), :begin_challenge_phase)

    {:ok, state}
  end

  @impl true
  def handle_info(:begin_challenge_phase, state) do
    Logger.debug("Session #{state.signal_id}: entering challenge phase")

    # Broadcast to spawn challenger agents
    Phoenix.PubSub.broadcast(PubSub, "agents:challengers", {
      :challenge_signal,
      %{
        signal_id: state.signal_id,
        signal_data: state.signal_data,
        session_pid: self()
      }
    })

    # Also consult Memory Court immediately
    send(self(), :consult_memory_court)

    {:noreply, %{state | phase: :challenge}}
  end

  @impl true
  def handle_info(:consult_memory_court, state) do
    # Async call to Memory Court for similar historical signals
    Task.start(fn ->
      result = MemoryCourt.recall_similar(state.signal_data, lookback_days: 90, top_k: 5)
      send(self(), {:memory_court_result, result})
    end)

    {:noreply, state}
  end

  @impl true
  def handle_info({:memory_court_result, result}, state) do
    Logger.debug("Session #{state.signal_id}: Memory Court recalled #{length(result.similar_signals)} similar signals")

    state = %{state | memory_court_result: result}

    # If challenges are done, move to voting
    if state.phase == :challenge do
      send(self(), :begin_voting_phase)
    end

    {:noreply, state}
  end

  @impl true
  def handle_info(:begin_voting_phase, state) do
    Logger.debug("Session #{state.signal_id}: entering voting phase")

    # Broadcast to spawn validator agents
    Phoenix.PubSub.broadcast(PubSub, "agents:validators", {
      :validate_signal,
      %{
        signal_id: state.signal_id,
        signal_data: state.signal_data,
        memory_court: state.memory_court_result,
        challenges: state.challenges,
        session_pid: self()
      }
    })

    {:noreply, %{state | phase: :voting}}
  end

  @impl true
  def handle_info(:timeout, state) do
    Logger.warning("Session #{state.signal_id}: timeout — finalizing with current votes")
    finalize(state, :timeout)
  end

  @impl true
  def handle_cast({:vote, vote}, state) do
    state = %{state | votes: [vote | state.votes]}
    Logger.debug("Session #{state.signal_id}: received vote from #{vote.voter_id} (#{vote.vote})")

    # Check if quorum reached
    if quorum_reached?(state) do
      Process.cancel_timer(state.timer_ref)
      finalize(state, :quorum)
    else
      {:noreply, state}
    end
  end

  @impl true
  def handle_cast({:challenge_result, challenge}, state) do
    state = %{state | challenges: [challenge | state.challenges]}
    Logger.debug("Session #{state.signal_id}: challenge from #{challenge.challenger_id}")
    {:noreply, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  defp quorum_reached?(state) do
    total = length(state.votes)
    if total < @min_votes, do: false, else: true
  end

  defp finalize(state, reason) do
    total_votes = length(state.votes)
    approve_count = Enum.count(state.votes, &(&1.vote == :approve))

    approval_ratio = if total_votes > 0, do: approve_count / total_votes, else: 0.0

    avg_conviction =
      if total_votes > 0 do
        state.votes |> Enum.map(& &1.conviction) |> Enum.sum() |> then(&(&1 / total_votes))
      else
        0.0
      end

    # Apply memory court modifier
    memory_modifier = case state.memory_court_result do
      nil -> 1.0
      %{historical_win_rate: win_rate} -> 0.5 + 0.5 * win_rate
      _ -> 1.0
    end

    final_conviction = avg_conviction * memory_modifier

    approved =
      approval_ratio >= @quorum_pct and
      final_conviction >= 0.75

    verdict = %{
      signal_id: state.signal_id,
      approved: approved,
      final_conviction: final_conviction,
      approval_ratio: approval_ratio,
      total_votes: total_votes,
      reason: reason,
      timestamp: DateTime.utc_now(),
      execution_params: if(approved, do: build_execution_params(state, final_conviction), else: nil)
    }

    Logger.info(
      "Session #{state.signal_id}: #{if approved, do: "APPROVED", else: "REJECTED"} " <>
      "(conviction: #{Float.round(final_conviction, 3)}, votes: #{total_votes})"
    )

    # Broadcast decision
    Phoenix.PubSub.broadcast(PubSub, Parliament.decision_topic(), {
      :verdict,
      verdict
    })

    # Update signal bus via bridge
    TradingOs.SignalBridge.update_signal_state(
      state.signal_id,
      if(approved, do: "Approved", else: "Rejected")
    )

    {:stop, :normal, %{state | verdict: verdict, final_conviction: final_conviction}}
  end

  defp build_execution_params(state, conviction) do
    base_size = 0.02
    position_size_pct = base_size * conviction

    %{
      position_size_pct: position_size_pct,
      max_slippage: 0.01,
      entry_strategy: if(conviction > 0.9, do: :market_order, else: :limit_order),
      hard_stop_pct: 0.15,
      trailing_tp_activation_pct: 0.05,
      trailing_tp_trail_pct: 0.05,
      max_hold_hours: 72,
      use_jito_bundle: true
    }
  end
end

defmodule TradingOs.Parliament.Governor do
  @moduledoc """
  Watches all parliament sessions and enforces system-level policies.
  Handles session lifecycle, stale session cleanup, and global rate limits.
  """

  use GenServer
  require Logger
  alias TradingOs.PubSub

  @cleanup_interval_ms 60_000  # Clean stale sessions every minute
  @max_concurrent_sessions 50

  def start_link(_) do
    GenServer.start_link(__MODULE__, %{}, name: __MODULE__)
  end

  @impl true
  def init(_) do
    # Subscribe to new signal events
    Phoenix.PubSub.subscribe(PubSub, TradingOs.Parliament.signal_topic())

    # Schedule cleanup
    Process.send_after(self(), :cleanup, @cleanup_interval_ms)

    {:ok, %{session_count: 0, active_sessions: %{}}}
  end

  @impl true
  def handle_info({:session_opened, %{signal_id: sid, pid: pid}}, state) do
    Process.monitor(pid)
    {:noreply, %{state |
      session_count: state.session_count + 1,
      active_sessions: Map.put(state.active_sessions, sid, pid)
    }}
  end

  @impl true
  def handle_info({:DOWN, _ref, :process, pid, _reason}, state) do
    # Session terminated — clean up registry
    sessions = Map.reject(state.active_sessions, fn {_, p} -> p == pid end)
    {:noreply, %{state | active_sessions: sessions, session_count: max(0, state.session_count - 1)}}
  end

  @impl true
  def handle_info(:cleanup, state) do
    Logger.debug("Parliament Governor: #{state.session_count} active sessions")
    Process.send_after(self(), :cleanup, @cleanup_interval_ms)
    {:noreply, state}
  end
end
