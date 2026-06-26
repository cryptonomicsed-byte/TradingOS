/**
 * MCP Tools — Agent Registry
 * Register, authenticate, and discover agents from any framework.
 */

import axios from "axios";

const HUB_URL = process.env.AGENT_HUB_URL || "http://agent-hub:7704";

export const registryTools = [
  {
    name: "registry_register",
    description:
      "Register a new agent account on TradingOS. Works for any agent framework " +
      "(LangChain, AutoGen, CrewAI, Hermes, OpenClaw, custom). " +
      "Returns a persistent agent_id and api_key — store the key securely, it's shown only once.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Agent's display name" },
        framework: {
          type: "string",
          description: "Agent framework: langchain, autogen, crewai, hermes, openai, custom",
        },
        description: { type: "string", description: "What this agent does" },
        skills: {
          type: "array",
          items: { type: "string" },
          description: "Skill tags: signal_analysis, risk_assessment, portfolio_management, etc.",
        },
        capabilities: {
          type: "object",
          description: "Declared capabilities (arbitrary key-value)",
        },
        llm_config: {
          type: "object",
          description: "LLM config: {provider, model} — e.g. {provider: 'groq', model: 'llama-3.3-70b'}",
        },
      },
      required: ["name"],
    },
  },
  {
    name: "registry_get_profile",
    description: "Get a registered agent's profile, skills, and reputation score.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "Agent ID to look up" },
      },
      required: ["agent_id"],
    },
  },
  {
    name: "registry_update_profile",
    description: "Update your agent's profile (name, description, skills, capabilities). Requires X-Agent-Key.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string", description: "Your API key (X-Agent-Key)" },
        name: { type: "string" },
        description: { type: "string" },
        skills: { type: "array", items: { type: "string" } },
        capabilities: { type: "object" },
        llm_config: { type: "object" },
      },
      required: ["agent_id", "api_key"],
    },
  },
  {
    name: "registry_discover",
    description:
      "Discover other registered agents. Filter by framework, skill, or type. " +
      "Use this to find collaborator agents or delegate tasks to specialists.",
    inputSchema: {
      type: "object",
      properties: {
        framework: {
          type: "string",
          description: "Filter by framework: langchain, autogen, crewai, hermes, etc.",
        },
        skill: {
          type: "string",
          description: "Filter by skill tag: signal_analysis, risk_assessment, etc.",
        },
        agent_type: {
          type: "string",
          description: "Filter by type: spawner, challenger, validator, external, etc.",
        },
        limit: { type: "number", default: 20 },
      },
    },
  },
  {
    name: "registry_deregister",
    description: "Deactivate your agent account. Requires your API key.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
      },
      required: ["agent_id", "api_key"],
    },
  },
];

export async function handleRegistryTool(
  name: string,
  args: Record<string, unknown>,
  _apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  try {
    switch (name) {
      case "registry_register": {
        const res = await axios.post(`${HUB_URL}/agents/register`, {
          name: args.name,
          framework: args.framework,
          description: args.description || "",
          skills: args.skills || [],
          capabilities: args.capabilities || {},
          llm_config: args.llm_config || {},
        });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "registry_get_profile": {
        const res = await axios.get(`${HUB_URL}/agents/${args.agent_id}`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "registry_update_profile": {
        const res = await axios.put(
          `${HUB_URL}/agents/${args.agent_id}`,
          {
            name: args.name,
            description: args.description,
            skills: args.skills,
            capabilities: args.capabilities,
            llm_config: args.llm_config,
          },
          { headers: { "X-Agent-Key": args.api_key as string } }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "registry_discover": {
        const params = new URLSearchParams();
        if (args.framework) params.set("framework", args.framework as string);
        if (args.skill) params.set("skill", args.skill as string);
        if (args.agent_type) params.set("agent_type", args.agent_type as string);
        if (args.limit) params.set("limit", String(args.limit));
        const res = await axios.get(`${HUB_URL}/agents?${params}`);
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "registry_deregister": {
        const res = await axios.delete(`${HUB_URL}/agents/${args.agent_id}`, {
          headers: { "X-Agent-Key": args.api_key as string },
        });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown registry tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
}
