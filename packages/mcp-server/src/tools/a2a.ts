/**
 * MCP Tools — A2A Messaging + Session Management
 *
 * A2A: Agents send/receive typed messages to each other
 * Sessions: Persistent working context with state + conversation history
 */

import axios from "axios";

const HUB_URL = process.env.AGENT_HUB_URL || "http://agent-hub:7704";

export const a2aTools = [
  // ── A2A Messaging
  {
    name: "a2a_send",
    description:
      "Send a message to another registered agent. " +
      "Supports direct messages, tasks, notifications, and responses. " +
      "The recipient can poll their inbox or receive it via SSE stream.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string", description: "Your X-Agent-Key" },
        to_agent_id: { type: "string", description: "Recipient agent ID" },
        content: { type: "object", description: "Message payload (any JSON)" },
        subject: { type: "string", description: "Short message subject" },
        message_type: {
          type: "string",
          enum: ["message", "task", "notification", "response"],
          default: "message",
        },
        channel: {
          type: "string",
          description: "Channel name for routing (default: direct)",
          default: "direct",
        },
        priority: {
          type: "number",
          description: "Priority 1 (low) to 10 (critical). Default: 5",
          minimum: 1,
          maximum: 10,
          default: 5,
        },
        reply_to_id: { type: "string", description: "Message ID this is replying to (for threads)" },
        ttl_hours: { type: "number", description: "Auto-expire message after N hours" },
      },
      required: ["api_key", "to_agent_id", "content"],
    },
  },
  {
    name: "a2a_inbox",
    description:
      "Check this agent's message inbox. Returns pending messages from other agents. " +
      "Drains the real-time Redis queue first, then falls back to persistent storage.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        limit: { type: "number", default: 10 },
        unread_only: { type: "boolean", default: true },
      },
      required: ["agent_id", "api_key"],
    },
  },
  {
    name: "a2a_ack",
    description: "Acknowledge a message (mark as read). Use after processing a message from your inbox.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        api_key: { type: "string" },
        message_id: { type: "string" },
      },
      required: ["agent_id", "api_key", "message_id"],
    },
  },
  {
    name: "a2a_broadcast",
    description:
      "Broadcast a message to all agents subscribed to a channel. " +
      "Use for market alerts, coordination signals, or announcements.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        channel: { type: "string", description: "Channel to broadcast on: market-alerts, risk-events, etc." },
        content: { type: "object" },
        message_type: { type: "string", default: "broadcast" },
      },
      required: ["api_key", "channel", "content"],
    },
  },

  // ── Session Management
  {
    name: "session_create",
    description:
      "Create a persistent agent session. Sessions store mutable state, conversation history, " +
      "and pinned context (like a system prompt) that persist across calls. " +
      "Use to maintain continuity across multiple interactions.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        session_id: {
          type: "string",
          description: "Custom session ID. Auto-generated if not provided.",
        },
        name: { type: "string", description: "Human-readable session name" },
        purpose: { type: "string", description: "What is this session for?" },
        context: {
          type: "object",
          description: "Pinned context (system prompt, agent config, etc.)",
        },
        initial_state: {
          type: "object",
          description: "Initial mutable session state",
        },
      },
      required: ["api_key"],
    },
  },
  {
    name: "session_get",
    description: "Get current state and metadata for a session.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        session_id: { type: "string" },
      },
      required: ["api_key", "session_id"],
    },
  },
  {
    name: "session_update_state",
    description:
      "Update the mutable state of a session. " +
      "Use to track task progress, decisions made, intermediate results, etc.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        session_id: { type: "string" },
        state: { type: "object", description: "New state to merge/replace" },
        name: { type: "string" },
        purpose: { type: "string" },
      },
      required: ["api_key", "session_id", "state"],
    },
  },
  {
    name: "session_history_append",
    description:
      "Append a message to the session's conversation history. " +
      "Use after each turn to build a persistent, retrievable conversation record.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        session_id: { type: "string" },
        role: {
          type: "string",
          enum: ["user", "assistant", "system", "tool"],
          description: "Role of the message author",
        },
        content: { type: "string", description: "Message content" },
        metadata: { type: "object", description: "Optional metadata (tool name, token count, etc.)" },
      },
      required: ["api_key", "session_id", "role", "content"],
    },
  },
  {
    name: "session_history_get",
    description: "Retrieve the conversation history for a session.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        session_id: { type: "string" },
        limit: { type: "number", default: 50, description: "Number of most recent turns to return" },
      },
      required: ["api_key", "session_id"],
    },
  },
  {
    name: "session_list",
    description: "List all active sessions for this agent.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        active_only: { type: "boolean", default: true },
      },
      required: ["api_key"],
    },
  },
  {
    name: "session_end",
    description: "End a session. State and history are preserved for later review.",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        session_id: { type: "string" },
      },
      required: ["api_key", "session_id"],
    },
  },
];

export async function handleA2ATool(
  name: string,
  args: Record<string, unknown>,
  _apiUrl: string
): Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }> {
  const apiKey = args.api_key as string;
  const headers = { "X-Agent-Key": apiKey };
  const agentId = args.agent_id as string | undefined;

  try {
    switch (name) {
      // A2A
      case "a2a_send": {
        const res = await axios.post(
          `${HUB_URL}/a2a/send`,
          {
            to_agent_id: args.to_agent_id,
            content: args.content,
            subject: args.subject,
            message_type: args.message_type ?? "message",
            channel: args.channel ?? "direct",
            priority: args.priority ?? 5,
            reply_to_id: args.reply_to_id,
            ttl_hours: args.ttl_hours,
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "a2a_inbox": {
        const params = new URLSearchParams({
          limit: String(args.limit ?? 10),
          unread_only: String(args.unread_only ?? true),
        });
        const res = await axios.get(`${HUB_URL}/a2a/inbox/${agentId}?${params}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "a2a_ack": {
        const res = await axios.delete(
          `${HUB_URL}/a2a/inbox/${agentId}/${args.message_id}`,
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "a2a_broadcast": {
        const res = await axios.post(
          `${HUB_URL}/a2a/broadcast/${args.channel}`,
          { channel: args.channel, content: args.content, message_type: args.message_type ?? "broadcast" },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      // Sessions
      case "session_create": {
        const res = await axios.post(
          `${HUB_URL}/sessions`,
          {
            session_id: args.session_id,
            name: args.name,
            purpose: args.purpose,
            context: args.context ?? {},
            initial_state: args.initial_state ?? {},
          },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "session_get": {
        const res = await axios.get(`${HUB_URL}/sessions/${args.session_id}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "session_update_state": {
        const res = await axios.put(
          `${HUB_URL}/sessions/${args.session_id}`,
          { state: args.state, name: args.name, purpose: args.purpose },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "session_history_append": {
        const res = await axios.post(
          `${HUB_URL}/sessions/${args.session_id}/history`,
          { role: args.role, content: args.content, metadata: args.metadata ?? {} },
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "session_history_get": {
        const res = await axios.get(
          `${HUB_URL}/sessions/${args.session_id}/history?limit=${args.limit ?? 50}`,
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "session_list": {
        const res = await axios.get(
          `${HUB_URL}/sessions?active_only=${args.active_only ?? true}`,
          { headers }
        );
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      case "session_end": {
        const res = await axios.delete(`${HUB_URL}/sessions/${args.session_id}`, { headers });
        return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown A2A/session tool: ${name}` }], isError: true };
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text", text: `A2A/session error: ${msg}` }], isError: true };
  }
}
