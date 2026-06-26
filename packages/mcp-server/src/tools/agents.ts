import axios from "axios";

export const agentTools = [
  {
    name: "agent_list",
    description: "List all registered agents with their types, specializations, and reputation scores",
    inputSchema: {
      type: "object",
      properties: {
        type_filter: {
          type: "string",
          description: "Filter by agent type: spawner, challenger, validator, executor",
        },
        min_reputation: {
          type: "number",
          description: "Filter agents by minimum reputation score",
        },
      },
    },
  },
  {
    name: "agent_get_profile",
    description: "Get detailed profile of a specific agent including accuracy, predictions, and skills",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
      },
      required: ["agent_id"],
    },
  },
  {
    name: "agent_spawn_analysis",
    description: "Spawn a specialized analysis agent for a specific task (on-chain, social, narrative, etc.)",
    inputSchema: {
      type: "object",
      properties: {
        agent_type: {
          type: "string",
          enum: ["onchain", "social", "whale", "dex", "macro", "narrative"],
        },
        task: {
          type: "string",
          description: "Specific analysis task for the agent",
        },
        tokens: {
          type: "array",
          items: { type: "string" },
        },
      },
      required: ["agent_type", "task"],
    },
  },
  {
    name: "spawner_run_onchain",
    description: "Run the on-chain spawner agent to analyze whale movements, exchange flows, and DEX volumes",
    inputSchema: {
      type: "object",
      properties: {
        tokens: {
          type: "array",
          items: { type: "string" },
        },
        focus: {
          type: "string",
          description: "What to focus on: whale_accumulation, exchange_outflow, dex_volume_surge",
          default: "whale_accumulation",
        },
      },
    },
  },
  {
    name: "challenger_run_security",
    description: "Run security challenger against a token — checks for honeypot, rug risk, holder concentration",
    inputSchema: {
      type: "object",
      properties: {
        token_address: { type: "string" },
        chain: { type: "string", default: "solana" },
        signal_id: { type: "string", description: "Optional: attach challenge to signal" },
      },
      required: ["token_address"],
    },
  },
];

export async function handleAgentTool(
  name: string,
  args: Record<string, unknown>,
  apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  try {
    switch (name) {
      case "agent_list": {
        const res = await axios.get(`${apiUrl}/agents`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "agent_get_profile": {
        const res = await axios.get(`${apiUrl}/agents/${args.agent_id}`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "agent_spawn_analysis":
      case "spawner_run_onchain": {
        const res = await axios.post(`${apiUrl}/intelligence/analyze`, {
          tokens: args.tokens || [],
          focus: args.focus || args.task || "general",
          spawner_type: args.agent_type || "onchain",
        });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "challenger_run_security": {
        const res = await axios.post(`${apiUrl}/intelligence/challenge`, {
          signal_id: args.signal_id || "manual",
          signal_data: {
            asset_address: args.token_address,
            asset_chain: args.chain || "solana",
          },
          challenge_types: ["security"],
        });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown agent tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
}
