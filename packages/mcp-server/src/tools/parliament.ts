/**
 * MCP Tools — Parliament & Memory Court
 * Tools for interacting with the signal deliberation system.
 */

import axios from "axios";

export const parliamentTools = [
  {
    name: "parliament_evaluate",
    description: "Ask the Agent Parliament to evaluate a trading signal or thesis. Returns a structured consensus with individual agent votes.",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: {
          type: "string",
          description: "ID of an existing signal to evaluate",
        },
        token: {
          type: "string",
          description: "Token symbol if creating a new evaluation",
        },
        thesis: {
          type: "string",
          description: "Your trading thesis to evaluate",
        },
        urgency: {
          type: "string",
          enum: ["low", "normal", "high"],
          description: "low = wait for full deliberation, high = fast consensus",
          default: "normal",
        },
      },
    },
  },
  {
    name: "parliament_get_session",
    description: "Get the current state of a parliament deliberation session for a signal",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: { type: "string" },
      },
      required: ["signal_id"],
    },
  },
  {
    name: "parliament_submit_vote",
    description: "Submit a vote to an active parliament session (for AI agents participating in the parliament)",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: { type: "string" },
        vote: {
          type: "string",
          enum: ["Approve", "Reject", "Abstain"],
        },
        conviction: {
          type: "number",
          description: "Your conviction in this vote (0.0-1.0)",
          minimum: 0,
          maximum: 1,
        },
        rationale: {
          type: "string",
          description: "Your reasoning for this vote",
        },
      },
      required: ["signal_id", "vote", "conviction", "rationale"],
    },
  },
  {
    name: "parliament_list_active",
    description: "List all active parliament sessions with their current vote counts",
    inputSchema: {
      type: "object",
      properties: {
        state_filter: {
          type: "string",
          description: "Filter by session state",
        },
      },
    },
  },
  {
    name: "memory_court_recall",
    description: "Query the Memory Court for historical signals similar to a given setup. Returns win rates and P&L statistics.",
    inputSchema: {
      type: "object",
      properties: {
        signal_pattern: {
          type: "string",
          description: "Natural language description of the trading setup",
        },
        signal_data: {
          type: "object",
          description: "Structured signal data for vector similarity search",
        },
        lookback_days: {
          type: "number",
          description: "How far back to search. Default: 90 days",
          default: 90,
        },
        top_k: {
          type: "number",
          description: "Number of similar signals to return. Default: 5",
          default: 5,
        },
      },
    },
  },
  {
    name: "memory_court_record_outcome",
    description: "Record the outcome of a trade so the Memory Court can learn from it",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: { type: "string" },
        pnl_pct: {
          type: "number",
          description: "Actual P&L percentage of the trade",
        },
        duration_hours: {
          type: "number",
          description: "How long the position was held",
        },
        exit_reason: {
          type: "string",
          enum: ["take_profit", "stop_loss", "trailing_stop", "time_exit", "manual"],
        },
        notes: {
          type: "string",
          description: "Any qualitative notes about what happened",
        },
      },
      required: ["signal_id", "pnl_pct", "duration_hours", "exit_reason"],
    },
  },
  {
    name: "parliament_challenge_signal",
    description: "Submit a challenge argument against a signal. Used by challenger agents to weaken bad signals.",
    inputSchema: {
      type: "object",
      properties: {
        signal_id: { type: "string" },
        challenge_type: {
          type: "string",
          enum: [
            "liquidity_risk", "contract_security", "market_manipulation",
            "macro_headwind", "sentiment_extreme", "mev_risk",
            "timing_risk", "holder_concentration"
          ],
        },
        arguments: {
          type: "array",
          items: { type: "string" },
          description: "Specific arguments against the signal",
        },
        conviction_impact: {
          type: "number",
          description: "Estimated conviction impact: negative=bad signal, positive=challenge failed",
          minimum: -0.5,
          maximum: 0.1,
        },
      },
      required: ["signal_id", "challenge_type", "arguments", "conviction_impact"],
    },
  },
];

export async function handleParliamentTool(
  name: string,
  args: Record<string, unknown>,
  apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  try {
    switch (name) {
      case "parliament_evaluate": {
        if (args.signal_id) {
          // Evaluate existing signal
          const res = await axios.get(`${apiUrl}/signals/${args.signal_id}/parliament`);
          return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
        }

        // Create and evaluate new signal
        const payload = {
          asset_symbol: args.token,
          asset_chain: "solana",
          signal_type: { type: "Long", target_pct: 0, timeframe_hours: 24 },
          source_type: "mcp_parliament_request",
          tags: ["mcp_evaluation"],
        };

        const createRes = await axios.post(`${apiUrl}/signals`, payload);
        const signalId = createRes.data.id;

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              signal_id: signalId,
              message: "Parliament session opened. Vote collection in progress.",
              status: "deliberating",
              thesis: args.thesis,
              check_status: `Use parliament_get_session with signal_id: ${signalId}`,
            }, null, 2),
          }],
        };
      }

      case "parliament_get_session": {
        const res = await axios.get(`${apiUrl}/signals/${args.signal_id}/parliament`);
        const record = res.data;

        if (!record) {
          return { content: [{ type: "text", text: JSON.stringify({ status: "no_session", signal_id: args.signal_id }) }] };
        }

        const summary = {
          signal_id: args.signal_id,
          session_id: record.session_id,
          phase: record.completed_at ? "completed" : "active",
          approved: record.approved,
          final_conviction: record.final_conviction,
          votes: {
            total: record.votes?.length || 0,
            approve: record.votes?.filter((v: any) => v.vote === "Approve").length || 0,
            reject: record.votes?.filter((v: any) => v.vote === "Reject").length || 0,
          },
          execution_recommendation: record.execution_recommendation,
        };

        return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
      }

      case "parliament_submit_vote": {
        const payload = {
          voter_id: `mcp_agent_${Date.now()}`,
          voter_type: "ExternalMCPAgent",
          vote: args.vote,
          conviction: args.conviction,
          rationale: args.rationale,
        };

        const res = await axios.post(`${apiUrl}/signals/${args.signal_id}/vote`, payload);
        return { content: [{ type: "text", text: JSON.stringify({ success: true, ...res.data }) }] };
      }

      case "parliament_list_active": {
        const res = await axios.get(`${apiUrl}/signals?state=InParliament`);
        const sessions = res.data.map((s: any) => ({
          signal_id: s.id,
          asset: s.asset?.symbol,
          conviction: s.conviction,
          votes: s.parliament_record?.votes?.length || 0,
          started_at: s.parliament_record?.started_at,
        }));
        return { content: [{ type: "text", text: JSON.stringify({ active_sessions: sessions }, null, 2) }] };
      }

      case "memory_court_recall": {
        const res = await axios.post(`${apiUrl}/intelligence/memory/recall`, {
          description: args.signal_pattern,
          signal_data: args.signal_data || {},
          lookback_days: args.lookback_days || 90,
          top_k: args.top_k || 5,
        });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_court_record_outcome": {
        const res = await axios.post(`${apiUrl}/intelligence/memory/outcome`, args);
        return { content: [{ type: "text", text: JSON.stringify({ success: true, ...res.data }) }] };
      }

      case "parliament_challenge_signal": {
        const payload = {
          challenger_id: `mcp_challenger_${Date.now()}`,
          challenge_type: args.challenge_type,
          arguments: args.arguments,
          counter_evidence: [],
          conviction_impact: args.conviction_impact,
        };

        const res = await axios.post(`${apiUrl}/signals/${args.signal_id}/challenge`, payload);
        return { content: [{ type: "text", text: JSON.stringify({ success: true, challenge_applied: true }) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown parliament tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
}
