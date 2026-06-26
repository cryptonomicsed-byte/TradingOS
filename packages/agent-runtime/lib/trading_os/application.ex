defmodule TradingOs.Application do
  @moduledoc """
  TradingOS Agent Runtime — OTP Application root.

  Supervision tree:
    Application
    ├── TradingOs.Repo               (database)
    ├── TradingOs.PubSub             (A2A messaging bus)
    ├── TradingOs.AgentRegistry      (agent discovery)
    ├── TradingOs.Parliament.Supervisor
    │   ├── TradingOs.Parliament.Session (dynamic, per-signal)
    │   └── TradingOs.Parliament.Governor
    ├── TradingOs.AgentSupervisor
    │   ├── Spawner agents (dynamic)
    │   ├── Challenger agents (dynamic)
    │   └── Validator agents (dynamic)
    ├── TradingOs.MemoryCourt        (vector similarity search)
    ├── TradingOs.SignalBridge       (HTTP bridge to Rust signal bus)
    └── TradingOs.Endpoint           (Phoenix HTTP/WS endpoint)
  """

  use Application
  require Logger

  @impl true
  def start(_type, _args) do
    Logger.info("TradingOS Agent Runtime starting...")

    children = [
      # Database
      TradingOs.Repo,

      # PubSub — Agent-to-Agent messaging backbone
      {Phoenix.PubSub, name: TradingOs.PubSub},

      # Agent registry — all agents register here for discovery
      {Registry, keys: :unique, name: TradingOs.AgentRegistry},

      # Dynamic supervisor for parliament sessions
      {DynamicSupervisor, name: TradingOs.Parliament.SessionSupervisor, strategy: :one_for_one},

      # Parliament Governor — orchestrates sessions
      TradingOs.Parliament.Governor,

      # Agent pools
      TradingOs.AgentSupervisor,

      # Memory Court — vector similarity search
      TradingOs.MemoryCourt,

      # Bridge to Rust Signal Bus
      TradingOs.SignalBridge,

      # Evolution scheduler — agent reputation updates
      TradingOs.AgentEvolution,

      # Phoenix endpoint
      TradingOs.Endpoint,
    ]

    opts = [strategy: :one_for_one, name: TradingOs.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    TradingOs.Endpoint.config_change(changed, removed)
    :ok
  end
end
