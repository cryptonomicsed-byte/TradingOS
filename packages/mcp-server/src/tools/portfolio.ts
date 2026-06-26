import axios from "axios";

export const portfolioTools = [
  {
    name: "portfolio_get_overview",
    description: "Get complete portfolio overview: positions, P&L, risk metrics, win rate",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "position_get_open",
    description: "Get all open positions with current P&L, stop-loss levels, and trailing TP status",
    inputSchema: {
      type: "object",
      properties: {
        include_stop_levels: { type: "boolean", default: true },
      },
    },
  },
  {
    name: "pnl_get_history",
    description: "Get historical P&L data with win/loss streaks, best/worst trades",
    inputSchema: {
      type: "object",
      properties: {
        days: { type: "number", description: "Lookback period in days", default: 30 },
        format: {
          type: "string",
          enum: ["summary", "detailed", "csv"],
          default: "summary",
        },
      },
    },
  },
  {
    name: "portfolio_get_risk",
    description: "Get current risk exposure: total deployed capital, max drawdown, Sharpe ratio",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "position_set_stop",
    description: "Update stop-loss and take-profit levels for an open position",
    inputSchema: {
      type: "object",
      properties: {
        position_id: { type: "string" },
        hard_stop_pct: { type: "number", description: "Stop loss at -X% from entry" },
        trailing_stop_pct: { type: "number", description: "Trail X% from peak" },
        take_profit_targets: {
          type: "array",
          items: {
            type: "object",
            properties: {
              pct_gain: { type: "number" },
              size_to_exit: { type: "number", description: "Fraction of position to close" },
            },
          },
        },
      },
      required: ["position_id"],
    },
  },
];

export async function handlePortfolioTool(
  name: string,
  args: Record<string, unknown>,
  apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  try {
    switch (name) {
      case "portfolio_get_overview": {
        const res = await axios.get(`${apiUrl}/portfolio`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "position_get_open": {
        const res = await axios.get(`${apiUrl}/portfolio/positions`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "pnl_get_history": {
        const res = await axios.get(`${apiUrl}/portfolio/pnl?days=${args.days || 30}`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "portfolio_get_risk": {
        const res = await axios.get(`${apiUrl}/portfolio/risk`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "position_set_stop": {
        const res = await axios.put(`${apiUrl}/portfolio/positions/${args.position_id}/stops`, args);
        return { content: [{ type: "text", text: JSON.stringify({ success: true, ...res.data }) }] };
      }
      default:
        return { content: [{ type: "text", text: `Unknown portfolio tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
}
