defmodule TradingOs.MixProject do
  use Mix.Project

  def project do
    [
      app: :trading_os,
      version: "0.1.0",
      elixir: "~> 1.16",
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      aliases: aliases()
    ]
  end

  def application do
    [
      extra_applications: [:logger, :runtime_tools],
      mod: {TradingOs.Application, []}
    ]
  end

  defp deps do
    [
      # Web framework & WebSockets
      {:phoenix, "~> 1.7"},
      {:phoenix_pubsub, "~> 2.1"},
      {:plug_cowboy, "~> 2.7"},
      {:cors_plug, "~> 3.0"},

      # HTTP client
      {:req, "~> 0.5"},

      # Database
      {:ecto_sql, "~> 3.11"},
      {:postgrex, "~> 0.18"},

      # Redis
      {:redix, "~> 1.3"},

      # JSON
      {:jason, "~> 1.4"},

      # Distributed Elixir
      {:libcluster, "~> 3.3"},

      # Telemetry & observability
      {:telemetry, "~> 1.2"},
      {:telemetry_metrics, "~> 0.6"},
      {:telemetry_poller, "~> 1.0"},
      {:opentelemetry, "~> 1.4"},
      {:opentelemetry_exporter, "~> 1.6"},

      # UUID
      {:ecto_identifier, "~> 0.5"},

      # Task scheduling
      {:quantum, "~> 3.5"},

      # Dev/test
      {:ex_doc, "~> 0.31", only: :dev, runtime: false},
      {:credo, "~> 1.7", only: [:dev, :test], runtime: false}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get", "ecto.setup"],
      "ecto.setup": ["ecto.create", "ecto.migrate", "run priv/repo/seeds.exs"],
      "ecto.reset": ["ecto.drop", "ecto.setup"]
    ]
  end
end
