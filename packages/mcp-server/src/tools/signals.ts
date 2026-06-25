/**
 * MCP Tools — Signal Intelligence
 * Everything an AI agent needs to work with trading signals.
 */

import axios from "axios";

export const signalTools = [
  {
    name: "get_live_signals",
    description: "Get all active trading signals above a conviction threshold. Returns SignalGenome objects with full provenance.",
    inputSchema: {
      type: "object",
      properties: {
        min_conviction: {
          type: "number",
          description: "Minimum conviction score (0.0-1.0). Default: 0.5",
          default: 0.5,
        },
        asset: {
          type: "string",
          description: "Filter by asset symbol (e.g. 'SOL', 'ETH')",
        },
        state: {
          type: "string",
          description: "Filter by signal state: Spawned, InParliament, Approved, Active",
        },
        limit: {
          type: "number",
          description: "Max results to return. Default: 20",
          default: 20,
        },
      },
    },
  },
  {
    name: "get_signal_by_id",
    description: "Get full details of a specific signal including its DNA, challenge history, and parliament record",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: {
          type: "string",
          description: "UUID of the signal",
        },
      },
      required: ["signal_id"],
    },
  },
  {
    name: "signal_get_high_conviction",
    description: "Get signals that have passed parliament with high conviction scores — these are the best trade candidates",
    inputSchema: {
      type: "object",
      properties: {
        min_conviction: {
          type: "number",
          description: "Minimum conviction. Default: 0.75 (parliament threshold)",
          default: 0.75,
        },
        include_dna: {
          type: "boolean",
          description: "Include full Signal DNA provenance chain",
          default: false,
        },
      },
    },
  },
  {
    name: "submit_signal",
    description: "Submit a new trading signal into the TradingOS pipeline. It will automatically go through Challenge and Parliament.",
    inputSchema: {
      type: "object",
      properties: {
        asset_symbol: {
          type: "string",
          description: "Token symbol (e.g. 'SOL', 'BONK')",
        },
        asset_chain: {
          type: "string",
          description: "Blockchain: solana, ethereum, base, arbitrum",
        },
        asset_address: {
          type: "string",
          description: "Contract address (optional but recommended)",
        },
        direction: {
          type: "string",
          enum: ["Long", "Short", "Hold", "Exit", "Alert"],
        },
        target_pct: {
          type: "number",
          description: "Expected price movement percentage",
        },
        timeframe_hours: {
          type: "number",
          description: "Expected timeframe in hours",
        },
        reasoning: {
          type: "string",
          description: "Your analysis and reasoning for this signal",
        },
        indicators: {
          type: "object",
          description: "Key market indicators (rsi_14, volume_ratio, whale_count, etc.)",
        },
        tags: {
          type: "array",
          items: { type: "string" },
        },
      },
      required: ["asset_symbol", "asset_chain", "direction", "reasoning"],
    },
  },
  {
    name: "signal_trigger_analysis",
    description: "Ask the AI spawner agents to analyze a specific token or list of tokens for signals",
    inputSchema: {
      type: "object",
      properties: {
        tokens: {
          type: "array",
          items: { type: "string" },
          description: "Token symbols or addresses to analyze",
        },
        focus: {
          type: "string",
          description: "Analysis focus: whale_activity, social_surge, dex_flow, narrative, general",
          default: "general",
        },
        spawner_type: {
          type: "string",
          description: "Which spawner agent to use: onchain, social, whale, dex, macro, narrative",
          default: "onchain",
        },
      },
      required: ["tokens"],
    },
  },
  {
    name: "signal_get_dna",
    description: "Get the full DNA (provenance chain, agent lineage, conviction evolution) of a signal",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: { type: "string" },
        include_challenge_history: {
          type: "boolean",
          default: true,
        },
      },
      required: ["signal_id"],
    },
  },
  {
    name: "signal_scan_now",
    description: "Trigger an immediate full signal scan across all spawner agents",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
];

export async function handleSignalTool(
  name: string,
  args: Record<string, unknown>,
  apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  try {
    switch (name) {
      case "get_live_signals": {
        const params = new URLSearchParams();
        if (args.min_conviction) params.set("min_conviction", String(args.min_conviction));
        if (args.asset) params.set("asset", String(args.asset));
        if (args.state) params.set("state", String(args.state));
        if (args.limit) params.set("limit", String(args.limit));

        const res = await axios.get(`${apiUrl}/signals?${params}`);
        const signals = res.data;

        const summary = signals.map((s: any) => ({
          id: s.id,
          asset: s.asset?.symbol,
          chain: s.asset?.chain,
          type: s.signal_type,
          conviction: s.conviction?.toFixed(3),
          effective_conviction: s.effective_conviction?.toFixed(3),
          state: s.state,
          tags: s.tags,
          created_at: s.created_at,
        }));

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              count: signals.length,
              signals: summary,
            }, null, 2),
          }],
        };
      }

      case "get_signal_by_id": {
        const res = await axios.get(`${apiUrl}/signals/${args.signal_id}`);
        return {
          content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }],
        };
      }

      case "signal_get_high_conviction": {
        const res = await axios.get(`${apiUrl}/signals/high-conviction?min_conviction=${args.min_conviction || 0.75}`);
        return {
          content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }],
        };
      }

      case "submit_signal": {
        const payload = {
          asset_symbol: args.asset_symbol,
          asset_chain: args.asset_chain,
          asset_address: args.asset_address,
          signal_type: {
            type: args.direction,
            target_pct: args.target_pct || 0,
            timeframe_hours: args.timeframe_hours || 24,
          },
          source_type: "mcp_agent_submission",
          indicators: args.indicators || {},
          tags: args.tags || [],
        };

        const res = await axios.post(`${apiUrl}/signals`, payload);
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              success: true,
              signal_id: res.data.id,
              message: "Signal submitted to parliament pipeline",
              state: res.data.state,
            }, null, 2),
          }],
        };
      }

      case "signal_trigger_analysis": {
        const res = await axios.post(`${apiUrl}/intelligence/analyze`, {
          tokens: args.tokens,
          focus: args.focus || "general",
          spawner_type: args.spawner_type || "onchain",
        });
        return {
          content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }],
        };
      }

      case "signal_get_dna": {
        const res = await axios.get(`${apiUrl}/signals/${args.signal_id}`);
        const signal = res.data;
        const dna = {
          signal_id: signal.id,
          asset: signal.asset,
          dna: signal.dna,
          fitness: signal.fitness,
          conviction_evolution: signal.dna?.conviction_evolution,
          challenge_history: args.include_challenge_history ? signal.challenge_history : undefined,
          parliament_record: signal.parliament_record,
        };
        return {
          content: [{ type: "text", text: JSON.stringify(dna, null, 2) }],
        };
      }

      case "signal_scan_now": {
        const res = await axios.post(`${apiUrl}/intelligence/scan`);
        return {
          content: [{ type: "text", text: JSON.stringify({ status: "scan_started", ...res.data }) }],
        };
      }

      default:
        return { content: [{ type: "text", text: `Unknown signal tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
}
