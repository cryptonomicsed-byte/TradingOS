import axios from "axios";

export const marketTools = [
  {
    name: "market_get_context",
    description: "Get current macro market context: BTC dominance, fear/greed index, gas prices, total crypto market cap",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "token_get_metrics",
    description: "Get current price, volume, liquidity, and market cap for any token",
    inputSchema: {
      type: "object",
      properties: {
        token: { type: "string", description: "Token address or symbol" },
        chain: { type: "string", default: "solana" },
      },
      required: ["token"],
    },
  },
  {
    name: "token_get_trending",
    description: "Get trending tokens by volume surge, social mentions, or new listings",
    inputSchema: {
      type: "object",
      properties: {
        sort_by: {
          type: "string",
          enum: ["volume_surge", "social_velocity", "new_listing", "whale_buying"],
          default: "volume_surge",
        },
        chain: { type: "string", description: "Filter by chain", default: "solana" },
        limit: { type: "number", default: 20 },
      },
    },
  },
  {
    name: "whale_get_recent_moves",
    description: "Get recent large wallet movements (whale trades) across tracked wallets",
    inputSchema: {
      type: "object",
      properties: {
        min_usd: { type: "number", description: "Minimum trade size in USD", default: 100000 },
        lookback_hours: { type: "number", default: 24 },
        chain: { type: "string", default: "solana" },
      },
    },
  },
  {
    name: "market_get_dex_boosts",
    description: "Get tokens with DexScreener boosts — paid promotion signals (be skeptical, but useful for radar)",
    inputSchema: {
      type: "object",
      properties: {
        chain: { type: "string", default: "solana" },
      },
    },
  },
];

export async function handleMarketTool(
  name: string,
  args: Record<string, unknown>,
  apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  try {
    switch (name) {
      case "market_get_context": {
        const res = await axios.get(`${apiUrl}/market/context`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "token_get_metrics": {
        const res = await axios.get(`${apiUrl}/market/token/${args.token}?chain=${args.chain || "solana"}`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "token_get_trending": {
        const res = await axios.get(
          `${apiUrl}/market/trending?sort_by=${args.sort_by || "volume_surge"}&chain=${args.chain || "solana"}&limit=${args.limit || 20}`
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "whale_get_recent_moves": {
        const res = await axios.get(
          `${apiUrl}/market/whales?min_usd=${args.min_usd || 100000}&lookback_hours=${args.lookback_hours || 24}`
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "market_get_dex_boosts": {
        const res = await axios.get(`https://api.dexscreener.com/token-boosts/latest/v1`);
        const filtered = (res.data || [])
          .filter((b: any) => !args.chain || b.chainId === args.chain)
          .slice(0, 20);
        return { content: [{ type: "text", text: JSON.stringify(filtered, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown market tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
}
