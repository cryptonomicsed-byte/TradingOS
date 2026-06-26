/**
 * MCP Tools — Agent Memory System
 *
 * Four memory tiers available to every agent:
 *   Working Memory  — ephemeral Redis key-value (expires after TTL)
 *   Long-term       — semantic vector store (Qdrant, searchable by meaning)
 *   Episodic        — timestamped event log (what happened, when)
 *   Knowledge Base  — structured facts the agent has learned
 *
 * All memory is namespaced per-agent. Shared namespaces allow collaboration.
 */

import axios from "axios";

const HUB_URL = process.env.AGENT_HUB_URL || "http://agent-hub:7704";

const withKey = (apiKey: string) => ({ headers: { "X-Agent-Key": apiKey } });

export const memoryTools = [
  // ── Working Memory (ephemeral)
  {
    name: "memory_working_set",
    description:
      "Store a value in working (ephemeral) memory. Auto-expires after TTL. " +
      "Use for current task context, intermediate results, scratchpad data.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string", description: "Your X-Agent-Key" },
        key: { type: "string", description: "Memory key" },
        value: { description: "Any JSON value to store" },
        ttl: { type: "number", description: "TTL in seconds (default: 3600)" },
      },
      required: ["agent_id", "api_key", "key", "value"],
    },
  },
  {
    name: "memory_working_get",
    description: "Retrieve a value from working memory by key.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        key: { type: "string" },
      },
      required: ["agent_id", "api_key", "key"],
    },
  },
  {
    name: "memory_working_list",
    description: "List all keys currently in working memory.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
      },
      required: ["agent_id", "api_key"],
    },
  },
  {
    name: "memory_working_delete",
    description: "Delete a key from working memory.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        key: { type: "string" },
      },
      required: ["agent_id", "api_key", "key"],
    },
  },

  // ── Long-term Memory (semantic vector store)
  {
    name: "memory_remember",
    description:
      "Store a long-term memory with semantic embedding. " +
      "Can be retrieved later by meaning, not just exact match. " +
      "Use for observations, decisions, patterns, and learnings you want to recall later.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        content: { type: "string", description: "Text to remember (will be embedded)" },
        importance: {
          type: "number",
          minimum: 0,
          maximum: 1,
          description: "How important is this memory? (0=trivial, 1=critical)",
          default: 0.5,
        },
        tags: { type: "array", items: { type: "string" }, description: "Tags for filtering" },
        metadata: { type: "object", description: "Additional structured data to store with this memory" },
        namespace: {
          type: "string",
          description: "Leave empty for personal memory, or set to a shared namespace name",
          default: "",
        },
      },
      required: ["agent_id", "api_key", "content"],
    },
  },
  {
    name: "memory_recall",
    description:
      "Semantically search long-term memories by natural language query. " +
      "Returns the most similar memories ranked by relevance. " +
      "Use this to find relevant past context, patterns, and learnings.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        query: { type: "string", description: "What do you want to remember?" },
        limit: { type: "number", default: 5, description: "Number of memories to return" },
        min_score: { type: "number", default: 0.0, description: "Minimum similarity score (0-1)" },
        namespace: { type: "string", default: "", description: "Search in shared namespace instead" },
      },
      required: ["agent_id", "api_key", "query"],
    },
  },
  {
    name: "memory_list",
    description: "List stored long-term memories.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        namespace: { type: "string", default: "" },
        limit: { type: "number", default: 20 },
        offset: { type: "number", default: 0 },
      },
      required: ["agent_id", "api_key"],
    },
  },

  // ── Episodic Memory (event log)
  {
    name: "memory_record_episode",
    description:
      "Log an episode to episodic memory — what happened, when, and the outcome. " +
      "Use after actions, decisions, trades, or any significant event. " +
      "Builds a queryable history of everything the agent has done.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        event_type: {
          type: "string",
          description: "Event category: signal_analyzed, vote_cast, trade_opened, memory_recalled, task_completed, etc.",
        },
        content: { type: "object", description: "Full event payload — what happened" },
        outcome: {
          type: "string",
          enum: ["success", "failure", "pending", "skipped"],
          default: "pending",
        },
        importance: { type: "number", minimum: 0, maximum: 1, default: 0.5 },
        session_id: { type: "string", description: "Associate with a session" },
        tags: { type: "array", items: { type: "string" } },
      },
      required: ["agent_id", "api_key", "event_type", "content"],
    },
  },
  {
    name: "memory_get_episodes",
    description: "Retrieve episodic memory. Filter by event type or session.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        event_type: { type: "string", description: "Filter by event type" },
        session_id: { type: "string", description: "Filter by session" },
        limit: { type: "number", default: 20 },
      },
      required: ["agent_id", "api_key"],
    },
  },

  // ── Knowledge Base (structured facts)
  {
    name: "memory_store_knowledge",
    description:
      "Store a structured fact in the knowledge base. Key-value with confidence scoring. " +
      "Use for learned facts, strategies, rules, and beliefs the agent has formed.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        key: { type: "string", description: "Fact key (unique per agent)" },
        value: { description: "Fact value (any JSON)" },
        category: {
          type: "string",
          description: "Category: market_rules, strategy, risk_parameters, learned_patterns, etc.",
          default: "general",
        },
        confidence: { type: "number", minimum: 0, maximum: 1, default: 1.0 },
        source: { type: "string", description: "Where this knowledge came from" },
        ttl_hours: { type: "number", description: "Auto-expire after N hours" },
      },
      required: ["agent_id", "api_key", "key", "value"],
    },
  },
  {
    name: "memory_get_knowledge",
    description: "Retrieve a knowledge fact by key.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        key: { type: "string" },
      },
      required: ["agent_id", "api_key", "key"],
    },
  },
  {
    name: "memory_list_knowledge",
    description: "List all knowledge facts, optionally filtered by category.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        category: { type: "string" },
      },
      required: ["agent_id", "api_key"],
    },
  },

  // ── Shared Memory
  {
    name: "memory_shared_remember",
    description:
      "Store a memory in a shared namespace that other agents can search. " +
      "Use for market observations, signals, or insights that should be shared with collaborators.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        namespace: { type: "string", description: "Shared space name, e.g. 'market-intel', 'signals-team'" },
        content: { type: "string" },
        importance: { type: "number", default: 0.5 },
        tags: { type: "array", items: { type: "string" } },
      },
      required: ["agent_id", "api_key", "namespace", "content"],
    },
  },
  {
    name: "memory_shared_recall",
    description: "Search a shared memory namespace for relevant memories from any agent.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        namespace: { type: "string" },
        query: { type: "string" },
        limit: { type: "number", default: 5 },
      },
      required: ["agent_id", "api_key", "namespace", "query"],
    },
  },
];

export async function handleMemoryTool(
  name: string,
  args: Record<string, unknown>,
  _apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  const agentId = args.agent_id as string;
  const apiKey = args.api_key as string;
  const headers = { "X-Agent-Key": apiKey };

  try {
    switch (name) {
      // Working Memory
      case "memory_working_set": {
        const res = await axios.put(
          `${HUB_URL}/memory/${agentId}/working/${args.key}`,
          { value: args.value, ttl: args.ttl },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_working_get": {
        const res = await axios.get(`${HUB_URL}/memory/${agentId}/working/${args.key}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_working_list": {
        const res = await axios.get(`${HUB_URL}/memory/${agentId}/working`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_working_delete": {
        const res = await axios.delete(`${HUB_URL}/memory/${agentId}/working/${args.key}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      // Long-term Memory
      case "memory_remember": {
        const res = await axios.post(
          `${HUB_URL}/memory/${agentId}/remember`,
          {
            content: args.content,
            importance: args.importance ?? 0.5,
            tags: args.tags ?? [],
            metadata: args.metadata ?? {},
            namespace: args.namespace ?? "",
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_recall": {
        const res = await axios.post(
          `${HUB_URL}/memory/${agentId}/recall`,
          {
            query: args.query,
            limit: args.limit ?? 5,
            min_score: args.min_score ?? 0.0,
            namespace: args.namespace ?? "",
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_list": {
        const params = new URLSearchParams({
          namespace: (args.namespace as string) || "",
          limit: String(args.limit ?? 20),
          offset: String(args.offset ?? 0),
        });
        const res = await axios.get(`${HUB_URL}/memory/${agentId}/memories?${params}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      // Episodic Memory
      case "memory_record_episode": {
        const res = await axios.post(
          `${HUB_URL}/memory/${agentId}/episodes`,
          {
            event_type: args.event_type,
            content: args.content,
            session_id: args.session_id,
            outcome: args.outcome ?? "pending",
            importance: args.importance ?? 0.5,
            tags: args.tags ?? [],
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_get_episodes": {
        const params = new URLSearchParams();
        if (args.event_type) params.set("event_type", args.event_type as string);
        if (args.session_id) params.set("session_id", args.session_id as string);
        params.set("limit", String(args.limit ?? 20));
        const res = await axios.get(`${HUB_URL}/memory/${agentId}/episodes?${params}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      // Knowledge Base
      case "memory_store_knowledge": {
        const res = await axios.put(
          `${HUB_URL}/memory/${agentId}/knowledge/${args.key}`,
          {
            value: args.value,
            category: args.category ?? "general",
            confidence: args.confidence ?? 1.0,
            source: args.source,
            ttl_hours: args.ttl_hours,
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_get_knowledge": {
        const res = await axios.get(`${HUB_URL}/memory/${agentId}/knowledge/${args.key}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_list_knowledge": {
        const params = new URLSearchParams();
        if (args.category) params.set("category", args.category as string);
        const res = await axios.get(`${HUB_URL}/memory/${agentId}/knowledge?${params}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      // Shared Memory
      case "memory_shared_remember": {
        const res = await axios.post(
          `${HUB_URL}/memory/shared/${args.namespace}/remember`,
          {
            content: args.content,
            importance: args.importance ?? 0.5,
            tags: args.tags ?? [],
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "memory_shared_recall": {
        const res = await axios.post(
          `${HUB_URL}/memory/shared/${args.namespace}/recall`,
          { query: args.query, limit: args.limit ?? 5 },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown memory tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `Memory error: ${msg}` }], isError: true };
  }
}
