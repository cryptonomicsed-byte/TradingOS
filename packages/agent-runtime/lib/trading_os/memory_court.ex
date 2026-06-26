defmodule TradingOs.MemoryCourt do
  @moduledoc """
  Memory Court — gives agents historical market intuition.

  Searches a vector store (Qdrant) for signals similar to the current one,
  returning historical performance data so the Parliament can learn from
  the past before committing to a position.

  The "court" metaphor: the Memory Court is called upon to give testimony
  about how similar situations played out historically. Its testimony
  weights the Parliament vote toward patterns that have historically
  succeeded and away from patterns that failed.
  """

  use GenServer
  require Logger

  @qdrant_collection "signal_memories"
  @embedding_dim 384  # Sentence transformer embedding dimension

  defstruct [:qdrant_url, :http_client]

  def start_link(_) do
    GenServer.start_link(__MODULE__, %{}, name: __MODULE__)
  end

  # Query for similar historical signals
  def recall_similar(signal_data, opts \\ []) do
    lookback_days = Keyword.get(opts, :lookback_days, 90)
    top_k = Keyword.get(opts, :top_k, 5)

    GenServer.call(__MODULE__, {:recall, signal_data, lookback_days, top_k}, 10_000)
  end

  # Store a completed signal with its outcome
  def store_outcome(signal_id, signal_data, pnl_pct, duration_hours) do
    GenServer.cast(__MODULE__, {:store, signal_id, signal_data, pnl_pct, duration_hours})
  end

  @impl true
  def init(_) do
    qdrant_url = System.get_env("QDRANT_URL", "http://qdrant:6333")
    Logger.info("MemoryCourt initializing, connecting to Qdrant at #{qdrant_url}")

    # Ensure collection exists
    Task.start(fn -> ensure_collection(qdrant_url) end)

    {:ok, %{qdrant_url: qdrant_url, cache: %{}}}
  end

  @impl true
  def handle_call({:recall, signal_data, lookback_days, top_k}, _from, state) do
    result = do_recall(state.qdrant_url, signal_data, lookback_days, top_k)
    {:reply, result, state}
  end

  @impl true
  def handle_cast({:store, signal_id, signal_data, pnl_pct, duration_hours}, state) do
    Task.start(fn ->
      do_store(state.qdrant_url, signal_id, signal_data, pnl_pct, duration_hours)
    end)
    {:noreply, state}
  end

  defp do_recall(qdrant_url, signal_data, lookback_days, top_k) do
    # Generate embedding for current signal
    embedding = generate_embedding(signal_data)

    # Query Qdrant for similar vectors
    payload = %{
      vector: embedding,
      limit: top_k,
      with_payload: true,
      filter: %{
        must: [
          %{
            range: %{
              key: "timestamp_unix",
              gte: DateTime.utc_now() |> DateTime.add(-lookback_days * 86400, :second) |> DateTime.to_unix()
            }
          }
        ]
      }
    }

    url = "#{qdrant_url}/collections/#{@qdrant_collection}/points/search"

    case Req.post(url, json: payload) do
      {:ok, %{status: 200, body: %{"result" => results}}} ->
        similar_signals = Enum.map(results, fn r ->
          %{
            signal_id: r["id"],
            similarity_score: r["score"],
            pnl_pct: get_in(r, ["payload", "pnl_pct"]),
            was_winning: (get_in(r, ["payload", "pnl_pct"]) || 0) > 0,
            asset: get_in(r, ["payload", "asset_symbol"]),
            duration_hours: get_in(r, ["payload", "duration_hours"])
          }
        end)

        winning = Enum.count(similar_signals, & &1.was_winning)
        historical_win_rate = if length(similar_signals) > 0, do: winning / length(similar_signals), else: 0.5

        avg_pnl = if length(similar_signals) > 0 do
          similar_signals |> Enum.map(&(&1.pnl_pct || 0)) |> Enum.sum() |> Kernel./(length(similar_signals))
        else
          0.0
        end

        %{
          similar_signals: similar_signals,
          historical_win_rate: historical_win_rate,
          avg_historical_pnl: avg_pnl,
          sample_size: length(similar_signals),
          testimony: build_testimony(similar_signals, historical_win_rate)
        }

      {:error, reason} ->
        Logger.warning("MemoryCourt: Qdrant query failed: #{inspect(reason)}")
        %{similar_signals: [], historical_win_rate: 0.5, avg_historical_pnl: 0.0, sample_size: 0, testimony: "No historical data available"}

      _ ->
        %{similar_signals: [], historical_win_rate: 0.5, avg_historical_pnl: 0.0, sample_size: 0, testimony: "Memory court unavailable"}
    end
  end

  defp do_store(qdrant_url, signal_id, signal_data, pnl_pct, duration_hours) do
    embedding = generate_embedding(signal_data)

    payload = %{
      points: [%{
        id: signal_id,
        vector: embedding,
        payload: %{
          asset_symbol: Map.get(signal_data, "asset_symbol"),
          signal_type: Map.get(signal_data, "signal_type"),
          source_type: Map.get(signal_data, "source_type"),
          indicators: Map.get(signal_data, "indicators", %{}),
          pnl_pct: pnl_pct,
          duration_hours: duration_hours,
          was_profitable: pnl_pct > 0,
          timestamp_unix: DateTime.utc_now() |> DateTime.to_unix()
        }
      }]
    }

    url = "#{qdrant_url}/collections/#{@qdrant_collection}/points"
    Req.put(url, json: payload)
  end

  defp generate_embedding(signal_data) do
    # In production: call a sentence transformer or Claude embedding endpoint
    # Here we generate a deterministic pseudo-embedding from signal features
    seed = :erlang.phash2(signal_data)
    :rand.seed(:exsss, {seed, seed + 1, seed + 2})
    for _ <- 1..@embedding_dim, do: :rand.normal()
  end

  defp ensure_collection(qdrant_url) do
    url = "#{qdrant_url}/collections/#{@qdrant_collection}"

    payload = %{
      vectors: %{
        size: @embedding_dim,
        distance: "Cosine"
      }
    }

    case Req.put(url, json: payload) do
      {:ok, _} -> Logger.info("MemoryCourt: Qdrant collection ready")
      {:error, reason} -> Logger.warning("MemoryCourt: Could not ensure collection: #{inspect(reason)}")
    end
  end

  defp build_testimony(similar_signals, win_rate) do
    if length(similar_signals) == 0 do
      "Memory Court: No similar historical patterns found."
    else
      pct = Float.round(win_rate * 100, 1)
      "Memory Court: #{length(similar_signals)} similar signals found, #{pct}% profitable historically."
    end
  end
end
