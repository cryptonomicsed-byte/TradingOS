defmodule TradingOS.AgentSupervisor do
  use Supervisor

  def start_link(init_arg) do
    Supervisor.start_link(__MODULE__, init_arg, name: __MODULE__)
  end

  @impl true
  def init(_init_arg) do
    children = [
      # Registry for agent discovery
      {Registry, keys: :unique, name: TradingOS.AgentRegistry},
      # Dynamic supervisor for Kanban cards
      {DynamicSupervisor, name: TradingOS.KanbanSupervisor, strategy: :one_for_one},
      # Core Confluence Matrix
      {TradingOS.Engine.ConfluenceMatrix, %{}}
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end
end

defmodule TradingOS.Kanban.Card do
  use GenServer, restart: :transient

  def start_link(card_id) do
    GenServer.start_link(__MODULE__, card_id, name: via_tuple(card_id))
  end

  def init(card_id) do
    # Initial state: INGESTED
    {:ok, %{id: card_id, state: :ingested, context: %{}}}
  end

  def handle_cast({:move_to, new_state, agent_id}, state) do
    # Log event to database (omitted for brevity)
    {:noreply, %{state | state: new_state}}
  end

  defp via_tuple(card_id), do: {:via, Registry, {TradingOS.AgentRegistry, card_id}}
end
