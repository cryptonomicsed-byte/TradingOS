defmodule TradingOSWeb.KanbanChannel do
  use Phoenix.Channel
  require Logger

  def join("kanban:lobby", _payload, socket) do
    {:ok, socket}
  end

  def join("kanban:" <> workspace_id, _payload, socket) do
    # In a hardened system, verify workspace_id access here
    {:ok, assign(socket, :workspace_id, workspace_id)}
  end

  def handle_in("card_move", %{"card_id" => card_id, "to_state" => to_state}, socket) do
    Logger.info("Manual card move: #{card_id} to #{to_state}")
    
    # Trigger the state machine transition in the core engine
    # TradingOS.Kanban.Card.move(card_id, to_state)

    # Broadcast to all clients in the workspace
    broadcast!(socket, "card_moved", %{
      card_id: card_id,
      to_state: to_state,
      timestamp: DateTime.utc_now()
    })

    {:reply, :ok, socket}
  end
end
