#!/usr/bin/env node
/**
 * TradingOS MCP Server
 *
 * The universal AI-native interface to TradingOS.
 * Any agent framework (Claude, GPT, Gemini, LangChain, AutoGen, CrewAI,
 * Hermes, OpenClaw, custom) can consume the full platform via these tools.
 *
 * Transport modes:
 *   stdio — for Claude Desktop / local agents
 *   http  — for web agents, LangChain, AutoGen, etc.
 *
 * Extra endpoints (HTTP mode only):
 *   GET /tools               — all tools (MCP format)
 *   GET /openai-tools        — tools in OpenAI function calling format
 *   GET /langchain-tools     — tools in LangChain format
 *   GET /openapi.json        — OpenAPI 3.0 spec
 *   GET /health              — health check
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { createServer, IncomingMessage, ServerResponse } from "http";

import { signalTools, handleSignalTool } from "./tools/signals.js";
import { agentTools, handleAgentTool } from "./tools/agents.js";
import { marketTools, handleMarketTool } from "./tools/market.js";
import { portfolioTools, handlePortfolioTool } from "./tools/portfolio.js";
import { parliamentTools, handleParliamentTool } from "./tools/parliament.js";
import { registryTools, handleRegistryTool } from "./tools/registry.js";
import { memoryTools, handleMemoryTool } from "./tools/memory.js";
import { a2aTools, handleA2ATool } from "./tools/a2a.js";

const API_URL  = process.env.API_GATEWAY_URL  || "http://api-gateway:8080";
const HUB_URL  = process.env.AGENT_HUB_URL    || "http://agent-hub:7704";

// ═══════════════════════════════════════════════════════════════
// ALL TOOLS — merged from every module
// ═══════════════════════════════════════════════════════════════

const ALL_TOOLS = [
  ...signalTools,
  ...agentTools,
  ...marketTools,
  ...portfolioTools,
  ...parliamentTools,
  ...registryTools,
  ...memoryTools,
  ...a2aTools,
];

// ═══════════════════════════════════════════════════════════════
// MCP SERVER
// ═══════════════════════════════════════════════════════════════

const server = new Server(
  { name: "tradingos", version: "1.0.0" },
  { capabilities: { tools: {}, resources: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: ALL_TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const a = args ?? {};

  try {
    // Signal tools
    if (name.startsWith("signal_") || name === "get_live_signals" || name === "submit_signal") {
      return await handleSignalTool(name, a, API_URL);
    }
    // Agent tools (internal agents)
    if (name.startsWith("agent_") || name.startsWith("spawner_") || name.startsWith("challenger_")) {
      return await handleAgentTool(name, a, API_URL);
    }
    // Market tools
    if (name.startsWith("market_") || name.startsWith("token_") || name.startsWith("whale_")) {
      return await handleMarketTool(name, a, API_URL);
    }
    // Portfolio tools
    if (name.startsWith("portfolio_") || name.startsWith("position_") || name.startsWith("pnl_")) {
      return await handlePortfolioTool(name, a, API_URL);
    }
    // Parliament tools
    if (name.startsWith("parliament_") || name.startsWith("memory_court_")) {
      return await handleParliamentTool(name, a, API_URL);
    }
    // Agent registry (external agents)
    if (name.startsWith("registry_")) {
      return await handleRegistryTool(name, a, API_URL);
    }
    // Memory system
    if (
      name.startsWith("memory_working_") ||
      name.startsWith("memory_remember") ||
      name.startsWith("memory_recall") ||
      name.startsWith("memory_list") ||
      name.startsWith("memory_record_") ||
      name.startsWith("memory_get_") ||
      name.startsWith("memory_store_") ||
      name.startsWith("memory_shared_")
    ) {
      return await handleMemoryTool(name, a, API_URL);
    }
    // A2A messaging + sessions
    if (name.startsWith("a2a_") || name.startsWith("session_")) {
      return await handleA2ATool(name, a, API_URL);
    }

    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
      isError: true,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [{ type: "text", text: `Tool error: ${message}` }],
      isError: true,
    };
  }
});

// ═══════════════════════════════════════════════════════════════
// MCP RESOURCES
// ═══════════════════════════════════════════════════════════════

server.setRequestHandler(ListResourcesRequestSchema, async () => ({
  resources: [
    {
      uri: "tradingos://signals/live",
      name: "Live Signals",
      description: "Real-time feed of all active trading signals with conviction scores",
      mimeType: "application/json",
    },
    {
      uri: "tradingos://parliament/sessions",
      name: "Parliament Sessions",
      description: "Active parliament deliberation sessions",
      mimeType: "application/json",
    },
    {
      uri: "tradingos://agents/status",
      name: "Agent Status",
      description: "Health and reputation of all registered agents",
      mimeType: "application/json",
    },
    {
      uri: "tradingos://portfolio/overview",
      name: "Portfolio Overview",
      description: "Current positions, P&L, and risk exposure",
      mimeType: "application/json",
    },
    {
      uri: "tradingos://market/context",
      name: "Market Context",
      description: "Current macro market conditions",
      mimeType: "application/json",
    },
    {
      uri: "tradingos://hub/agents",
      name: "Registered Agents",
      description: "All externally registered agents across all frameworks",
      mimeType: "application/json",
    },
  ],
}));

server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const { uri } = request.params;
  try {
    const { default: axios } = await import("axios");
    switch (uri) {
      case "tradingos://signals/live": {
        const res = await axios.get(`${API_URL}/signals?min_conviction=0.5&limit=20`);
        return { contents: [{ uri, mimeType: "application/json", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "tradingos://agents/status": {
        const res = await axios.get(`${API_URL}/agents`);
        return { contents: [{ uri, mimeType: "application/json", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "tradingos://portfolio/overview": {
        const res = await axios.get(`${API_URL}/portfolio`);
        return { contents: [{ uri, mimeType: "application/json", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "tradingos://market/context": {
        const res = await axios.get(`${API_URL}/market/context`);
        return { contents: [{ uri, mimeType: "application/json", text: JSON.stringify(res.data, null, 2) }] };
      }
      case "tradingos://hub/agents": {
        const res = await axios.get(`${HUB_URL}/agents`);
        return { contents: [{ uri, mimeType: "application/json", text: JSON.stringify(res.data, null, 2) }] };
      }
      default:
        return { contents: [{ uri, mimeType: "text/plain", text: "Resource not found" }] };
    }
  } catch (error) {
    return { contents: [{ uri, mimeType: "text/plain", text: `Error: ${error}` }] };
  }
});

// ═══════════════════════════════════════════════════════════════
// FRAMEWORK ADAPTER HELPERS
// ═══════════════════════════════════════════════════════════════

function toOpenAIFormat(tools: typeof ALL_TOOLS) {
  return tools.map((t) => ({
    type: "function",
    function: {
      name: t.name,
      description: t.description,
      parameters: (t as any).inputSchema ?? {},
    },
  }));
}

function toLangChainFormat(tools: typeof ALL_TOOLS) {
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    args_schema: (t as any).inputSchema ?? {},
    metadata: {
      source: "tradingos-mcp",
      endpoint: `http://localhost:${PORT}/mcp`,
    },
  }));
}

function toOpenAPISpec(tools: typeof ALL_TOOLS) {
  const paths: Record<string, any> = {};
  for (const tool of tools) {
    paths[`/tools/${tool.name}`] = {
      post: {
        operationId: tool.name,
        summary: tool.description,
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: (tool as any).inputSchema ?? {} },
          },
        },
        responses: {
          "200": {
            description: "Tool result",
            content: { "application/json": { schema: { type: "object" } } },
          },
        },
      },
    };
  }
  return {
    openapi: "3.0.3",
    info: {
      title: "TradingOS MCP API",
      version: "1.0.0",
      description: "Agent-native trading intelligence platform. All tools accessible via HTTP POST.",
    },
    servers: [{ url: `http://localhost:${PORT}`, description: "Local MCP Server" }],
    paths,
  };
}

// ═══════════════════════════════════════════════════════════════
// START
// ═══════════════════════════════════════════════════════════════

const PORT = parseInt(process.env.MCP_SERVER_PORT || "4000");
const MODE = process.env.MCP_MODE || "http";

if (MODE === "stdio") {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("TradingOS MCP Server running in stdio mode");
} else {
  const httpServer = createServer(async (req: IncomingMessage, res: ServerResponse) => {
    // CORS headers for browser-based agents
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Agent-Key, Authorization");
    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }

    const url = req.url ?? "/";

    // ── Health check
    if (url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok", tools: ALL_TOOLS.length, version: "1.0.0" }));
      return;
    }

    // ── MCP protocol endpoint
    if (url === "/mcp" || url.startsWith("/mcp/")) {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => Math.random().toString(36).slice(2),
      });
      await server.connect(transport);
      await transport.handleRequest(req, res);
      return;
    }

    // ── Tool listing (MCP format)
    if (url === "/tools") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ tools: ALL_TOOLS, count: ALL_TOOLS.length }));
      return;
    }

    // ── OpenAI function calling format
    if (url === "/openai-tools") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ tools: toOpenAIFormat(ALL_TOOLS), count: ALL_TOOLS.length }));
      return;
    }

    // ── LangChain format
    if (url === "/langchain-tools") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        tools: toLangChainFormat(ALL_TOOLS),
        count: ALL_TOOLS.length,
        usage: "Load these with TradingOSToolkit(mcp_url='http://mcp-server:4000')",
      }));
      return;
    }

    // ── OpenAPI 3.0 spec
    if (url === "/openapi.json" || url === "/openapi") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(toOpenAPISpec(ALL_TOOLS), null, 2));
      return;
    }

    // ── Tool invocation (REST shortcut — no MCP client needed)
    if (url.startsWith("/tools/") && req.method === "POST") {
      const toolName = url.replace("/tools/", "").split("?")[0];
      let body = "";
      for await (const chunk of req) body += chunk;
      try {
        const args = JSON.parse(body || "{}");
        const fakeRequest = { params: { name: toolName, arguments: args } };
        const result = await server.request(
          { method: "tools/call", params: { name: toolName, arguments: args } },
          CallToolRequestSchema
        );
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(result));
      } catch (err) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: String(err) }));
      }
      return;
    }

    res.writeHead(404);
    res.end("Not found");
  });

  httpServer.listen(PORT, () => {
    console.log(`\nTradingOS MCP Server v1.0.0 — ${ALL_TOOLS.length} tools`);
    console.log(`  MCP endpoint:      http://localhost:${PORT}/mcp`);
    console.log(`  Tool listing:      http://localhost:${PORT}/tools`);
    console.log(`  OpenAI format:     http://localhost:${PORT}/openai-tools`);
    console.log(`  LangChain format:  http://localhost:${PORT}/langchain-tools`);
    console.log(`  OpenAPI spec:      http://localhost:${PORT}/openapi.json`);
    console.log(`  Health:            http://localhost:${PORT}/health`);
  });
}
