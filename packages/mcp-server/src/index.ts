#!/usr/bin/env node
/**
 * TradingOS MCP Server
 *
 * Exposes the full TradingOS trading intelligence platform as MCP tools.
 * Any AI agent (Claude, GPT, Gemini, etc.) can consume signals, interact
 * with the parliament, query memory, and manage positions via these tools.
 *
 * This is the primary AI-native interface to TradingOS.
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
import { createServer } from "http";
import { z } from "zod";

import { signalTools, handleSignalTool } from "./tools/signals.js";
import { agentTools, handleAgentTool } from "./tools/agents.js";
import { marketTools, handleMarketTool } from "./tools/market.js";
import { portfolioTools, handlePortfolioTool } from "./tools/portfolio.js";
import { parliamentTools, handleParliamentTool } from "./tools/parliament.js";

const API_URL = process.env.API_GATEWAY_URL || "http://api-gateway:8080";

// ═══════════════════════════════════════════════════════════════
// SERVER SETUP
// ═══════════════════════════════════════════════════════════════

const server = new Server(
  {
    name: "tradingos",
    version: "0.1.0",
  },
  {
    capabilities: {
      tools: {},
      resources: {},
    },
  }
);

// Merge all tool definitions
const ALL_TOOLS = [
  ...signalTools,
  ...agentTools,
  ...marketTools,
  ...portfolioTools,
  ...parliamentTools,
];

// ═══════════════════════════════════════════════════════════════
// TOOL LISTING
// ═══════════════════════════════════════════════════════════════

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: ALL_TOOLS,
}));

// ═══════════════════════════════════════════════════════════════
// TOOL EXECUTION — Route to appropriate handler
// ═══════════════════════════════════════════════════════════════

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    // Route to signal tools
    if (name.startsWith("signal_") || name === "get_live_signals" || name === "submit_signal") {
      return await handleSignalTool(name, args ?? {}, API_URL);
    }

    // Route to agent tools
    if (name.startsWith("agent_") || name.startsWith("spawner_") || name.startsWith("challenger_")) {
      return await handleAgentTool(name, args ?? {}, API_URL);
    }

    // Route to market tools
    if (name.startsWith("market_") || name.startsWith("token_") || name.startsWith("whale_")) {
      return await handleMarketTool(name, args ?? {}, API_URL);
    }

    // Route to portfolio tools
    if (name.startsWith("portfolio_") || name.startsWith("position_") || name.startsWith("pnl_")) {
      return await handlePortfolioTool(name, args ?? {}, API_URL);
    }

    // Route to parliament tools
    if (name.startsWith("parliament_") || name.startsWith("memory_")) {
      return await handleParliamentTool(name, args ?? {}, API_URL);
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
// RESOURCES — Live data the agent can read
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
      description: "Current macro market conditions (BTC dominance, fear/greed, gas)",
      mimeType: "application/json",
    },
  ],
}));

server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const { uri } = request.params;

  try {
    const axios = (await import("axios")).default;

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
      default:
        return { contents: [{ uri, mimeType: "text/plain", text: "Resource not found" }] };
    }
  } catch (error) {
    return { contents: [{ uri, mimeType: "text/plain", text: `Error: ${error}` }] };
  }
});

// ═══════════════════════════════════════════════════════════════
// START — HTTP (for web agents) or stdio (for Claude Desktop)
// ═══════════════════════════════════════════════════════════════

const PORT = parseInt(process.env.MCP_SERVER_PORT || "4000");
const MODE = process.env.MCP_MODE || "http";

if (MODE === "stdio") {
  // Claude Desktop / local agent mode
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("TradingOS MCP Server running in stdio mode");
} else {
  // HTTP mode for web-based agents
  const httpServer = createServer(async (req, res) => {
    // Health check
    if (req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok", tools: ALL_TOOLS.length }));
      return;
    }

    // MCP endpoint
    if (req.url === "/mcp" || req.url?.startsWith("/mcp/")) {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => Math.random().toString(36).slice(2),
      });

      await server.connect(transport);
      await transport.handleRequest(req, res);
      return;
    }

    // Tool discovery endpoint (for non-MCP agents)
    if (req.url === "/tools") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ tools: ALL_TOOLS }));
      return;
    }

    res.writeHead(404);
    res.end("Not found");
  });

  httpServer.listen(PORT, () => {
    console.log(`TradingOS MCP Server listening on port ${PORT}`);
    console.log(`  MCP endpoint: http://localhost:${PORT}/mcp`);
    console.log(`  Health: http://localhost:${PORT}/health`);
    console.log(`  Tools: http://localhost:${PORT}/tools (${ALL_TOOLS.length} tools)`);
  });
}
