"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Cpu, TrendingUp, Shield, Brain, Zap, ChevronRight } from "lucide-react";
import Link from "next/link";

// ═══════════════════════════════════════════════════════════════
// TRADINGOS DASHBOARD — Root Page
// Agent Parliament Visualization with Glassmorphism 2.0 UI
// ═══════════════════════════════════════════════════════════════

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: Activity },
  { href: "/signals", label: "Signals", icon: TrendingUp },
  { href: "/parliament", label: "Parliament", icon: Brain },
  { href: "/portfolio", label: "Portfolio", icon: Shield },
  { href: "/agents", label: "Agents", icon: Cpu },
  { href: "/system", label: "System", icon: Zap },
];

export default function Home() {
  const [stats, setStats] = useState({
    activeSignals: 0,
    parliamentSessions: 0,
    approvedToday: 0,
    agentCount: 0,
    totalConviction: 0,
    systemHealth: "initializing",
  });

  const [recentSignals, setRecentSignals] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [liveActivity, setLiveActivity] = useState<string[]>([]);
  const [wsConnected, setWsConnected] = useState(false);

  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
  const WS = (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8080").replace("http", "ws");

  useEffect(() => {
    // Fetch initial data
    fetchData();
    const interval = setInterval(fetchData, 15_000);

    // WebSocket for real-time events
    const ws = new WebSocket(`${WS}/signals/ws`);
    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        handleBusEvent(msg);
      } catch {}
    };

    return () => {
      clearInterval(interval);
      ws.close();
    };
  }, []);

  async function fetchData() {
    try {
      const [signalsRes, agentsRes] = await Promise.allSettled([
        fetch(`${API}/signals?limit=10`).then(r => r.json()),
        fetch(`${API}/agents`).then(r => r.json()),
      ]);

      if (signalsRes.status === "fulfilled") {
        const signals = signalsRes.value;
        setRecentSignals(signals.slice(0, 6));
        setStats(prev => ({
          ...prev,
          activeSignals: signals.length,
          approvedToday: signals.filter((s: any) => s.state === "Approved" || s.state === "Active").length,
          totalConviction: signals.length > 0
            ? signals.reduce((sum: number, s: any) => sum + (s.conviction || 0), 0) / signals.length
            : 0,
          systemHealth: "operational",
        }));
      }

      if (agentsRes.status === "fulfilled") {
        const agents = agentsRes.value;
        setAgents(agents.slice(0, 8));
        setStats(prev => ({ ...prev, agentCount: agents.length }));
      }
    } catch (e) {
      setStats(prev => ({ ...prev, systemHealth: "degraded" }));
    }
  }

  function handleBusEvent(msg: any) {
    const eventText = formatBusEvent(msg);
    if (eventText) {
      setLiveActivity(prev => [eventText, ...prev.slice(0, 19)]);
    }
  }

  function formatBusEvent(msg: any): string | null {
    switch (msg.type || Object.keys(msg)[0]) {
      case "SignalCreated": return `⚡ New signal: ${msg.SignalCreated?.asset?.symbol}`;
      case "ParliamentDecision": return `⚖️ Parliament: ${msg.ParliamentDecision?.record?.approved ? "APPROVED" : "REJECTED"}`;
      case "ChallengeReceived": return `🛡️ Challenge received`;
      case "VoteReceived": return `🗳️ Vote cast: ${msg.VoteReceived?.vote?.vote}`;
      default: return null;
    }
  }

  const convictionColor = (c: number) => {
    if (c >= 0.85) return "var(--neon-cyan)";
    if (c >= 0.7) return "var(--neon-green)";
    if (c >= 0.5) return "var(--neon-gold)";
    if (c >= 0.3) return "var(--neon-orange)";
    return "var(--neon-red)";
  };

  const stateColor: Record<string, string> = {
    Spawned: "badge-spawned",
    InParliament: "badge-parliament",
    Approved: "badge-approved",
    Active: "badge-active",
    Rejected: "badge-rejected",
  };

  return (
    <div className="relative min-h-screen" style={{ background: "var(--bg-void)" }}>
      {/* Atmospheric background */}
      <div className="particle-field" />
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          background: "radial-gradient(ellipse 60% 60% at 50% -20%, rgba(139,92,246,0.08) 0%, transparent 70%)",
        }}
      />

      {/* ─── SIDEBAR ─────────────────────────────── */}
      <aside className="fixed left-0 top-0 h-full w-64 z-30 flex flex-col" style={{ borderRight: "1px solid rgba(255,255,255,0.06)" }}>
        <div className="glass h-full flex flex-col py-6 px-5">
          {/* Logo */}
          <div className="mb-10">
            <div className="flex items-center gap-3 mb-1">
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center"
                style={{ background: "linear-gradient(135deg, #8b5cf6, #00f5ff)" }}
              >
                <Brain size={18} color="white" />
              </div>
              <div>
                <div className="text-sm font-bold tracking-tight">TradingOS</div>
                <div className="data-label" style={{ fontSize: "0.6rem" }}>Agent Parliament v0.1</div>
              </div>
            </div>
          </div>

          {/* Nav */}
          <nav className="flex-1 space-y-1">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200 group"
                style={{
                  background: href === "/" ? "rgba(139,92,246,0.12)" : "transparent",
                  color: href === "/" ? "#8b5cf6" : "rgba(255,255,255,0.5)",
                  border: href === "/" ? "1px solid rgba(139,92,246,0.25)" : "1px solid transparent",
                }}
              >
                <Icon size={15} />
                <span className="font-medium">{label}</span>
                {href === "/" && <ChevronRight size={12} className="ml-auto opacity-50" />}
              </Link>
            ))}
          </nav>

          {/* System status */}
          <div className="glass-liquid rounded-xl p-3 mt-4">
            <div className="data-label mb-2">System Status</div>
            <div className="flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-full"
                style={{
                  background: stats.systemHealth === "operational" ? "var(--neon-green)" : "var(--neon-orange)",
                  boxShadow: `0 0 6px ${stats.systemHealth === "operational" ? "rgba(0,255,136,0.8)" : "rgba(255,107,53,0.8)"}`,
                }}
              />
              <span className="text-xs capitalize" style={{ color: stats.systemHealth === "operational" ? "var(--neon-green)" : "var(--neon-orange)" }}>
                {stats.systemHealth}
              </span>
              {wsConnected && (
                <span className="ml-auto text-xs" style={{ color: "rgba(0,245,255,0.6)" }}>⚡ Live</span>
              )}
            </div>
          </div>
        </div>
      </aside>

      {/* ─── MAIN CONTENT ─────────────────────────── */}
      <main className="pl-64 min-h-screen relative z-10">
        <div className="p-8">
          {/* Header */}
          <div className="mb-8 flex items-start justify-between">
            <div>
              <h1 className="text-2xl font-bold mb-1" style={{ letterSpacing: "-0.03em" }}>
                Agent Parliament
              </h1>
              <p className="text-sm" style={{ color: "rgba(255,255,255,0.4)" }}>
                {new Date().toLocaleString()} — {stats.agentCount} agents active
              </p>
            </div>
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="px-4 py-2 rounded-xl text-sm font-semibold"
              style={{
                background: "linear-gradient(135deg, rgba(139,92,246,0.3), rgba(0,245,255,0.2))",
                border: "1px solid rgba(139,92,246,0.4)",
                color: "white",
              }}
            >
              ⚡ Trigger Scan
            </motion.button>
          </div>

          {/* ─── STAT CARDS ─── */}
          <div className="grid grid-cols-4 gap-4 mb-8">
            {[
              { label: "Active Signals", value: stats.activeSignals, color: "var(--neon-cyan)", icon: "⚡" },
              { label: "In Parliament", value: stats.parliamentSessions, color: "var(--neon-purple)", icon: "⚖️" },
              { label: "Approved Today", value: stats.approvedToday, color: "var(--neon-green)", icon: "✅" },
              { label: "Avg Conviction", value: `${(stats.totalConviction * 100).toFixed(1)}%`, color: convictionColor(stats.totalConviction), icon: "🎯" },
            ].map(({ label, value, color, icon }) => (
              <motion.div
                key={label}
                className="glass-liquid rounded-2xl p-5"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                <div className="flex items-start justify-between mb-3">
                  <span className="data-label">{label}</span>
                  <span className="text-lg">{icon}</span>
                </div>
                <div className="data-value text-3xl font-bold" style={{ color }}>
                  {value}
                </div>
              </motion.div>
            ))}
          </div>

          {/* ─── MAIN GRID ─── */}
          <div className="grid grid-cols-12 gap-4">
            {/* Signal Feed — 7 cols */}
            <div className="col-span-7">
              <div className="glass-liquid rounded-2xl p-5 h-full">
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-sm font-semibold">Signal Feed</h2>
                  <Link href="/signals" className="text-xs" style={{ color: "var(--neon-cyan)" }}>
                    View all →
                  </Link>
                </div>

                <div className="space-y-3">
                  <AnimatePresence>
                    {recentSignals.length === 0 ? (
                      <div className="text-center py-12" style={{ color: "rgba(255,255,255,0.2)" }}>
                        <Brain size={40} className="mx-auto mb-3 opacity-30" />
                        <p className="text-sm">Awaiting signals...</p>
                        <p className="text-xs mt-1">Agents are scanning the market</p>
                      </div>
                    ) : (
                      recentSignals.map((signal, i) => (
                        <motion.div
                          key={signal.id}
                          className="glass rounded-xl p-4"
                          initial={{ opacity: 0, x: -20 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.05 }}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <span className="font-bold text-sm">{signal.asset?.symbol || "Unknown"}</span>
                                <span className={`badge ${stateColor[signal.state] || ""}`}>
                                  {signal.state}
                                </span>
                                <span className="badge" style={{ background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.4)" }}>
                                  {signal.asset?.chain?.toLowerCase?.() || "unknown"}
                                </span>
                              </div>
                              <div className="flex items-center gap-3 text-xs" style={{ color: "rgba(255,255,255,0.4)" }}>
                                <span>{signal.dna?.primary_source?.plugin_name || signal.dna?.primary_source?.metric || "spawner"}</span>
                                {signal.tags?.slice(0, 2).map((t: string) => (
                                  <span key={t} style={{ color: "rgba(139,92,246,0.7)" }}>#{t}</span>
                                ))}
                              </div>
                            </div>

                            {/* Conviction gauge */}
                            <div className="text-right shrink-0">
                              <div
                                className="data-value text-2xl font-bold"
                                style={{ color: convictionColor(signal.conviction || 0) }}
                              >
                                {((signal.conviction || 0) * 100).toFixed(0)}%
                              </div>
                              <div className="data-label">conviction</div>
                              <div className="conviction-bar w-20 mt-1">
                                <div
                                  className="conviction-fill"
                                  style={{
                                    width: `${(signal.conviction || 0) * 100}%`,
                                    background: convictionColor(signal.conviction || 0),
                                    boxShadow: `0 0 8px ${convictionColor(signal.conviction || 0)}`,
                                  }}
                                />
                              </div>
                            </div>
                          </div>

                          {/* Parliament votes mini view */}
                          {signal.parliament_record?.votes?.length > 0 && (
                            <div className="mt-3 pt-3 flex items-center gap-3" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
                              <span className="data-label">Parliament:</span>
                              <div className="flex gap-1">
                                {signal.parliament_record.votes.slice(0, 6).map((v: any, vi: number) => (
                                  <div
                                    key={vi}
                                    className="w-5 h-5 rounded-full flex items-center justify-center text-xs vote-appear"
                                    style={{
                                      background: v.vote === "Approve"
                                        ? "rgba(0,255,136,0.2)"
                                        : v.vote === "Reject"
                                        ? "rgba(255,45,85,0.2)"
                                        : "rgba(255,255,255,0.1)",
                                      border: `1px solid ${v.vote === "Approve" ? "rgba(0,255,136,0.4)" : v.vote === "Reject" ? "rgba(255,45,85,0.4)" : "rgba(255,255,255,0.2)"}`,
                                      animationDelay: `${vi * 0.1}s`,
                                    }}
                                  >
                                    {v.vote === "Approve" ? "✓" : v.vote === "Reject" ? "✗" : "·"}
                                  </div>
                                ))}
                              </div>
                              <span className="text-xs" style={{ color: "rgba(255,255,255,0.3)" }}>
                                {signal.parliament_record.votes.length} votes
                              </span>
                            </div>
                          )}
                        </motion.div>
                      ))
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </div>

            {/* Right column — 5 cols */}
            <div className="col-span-5 space-y-4">
              {/* Agent Parliament Status */}
              <div className="glass-liquid rounded-2xl p-5">
                <h2 className="text-sm font-semibold mb-4">Agent Status</h2>
                <div className="space-y-2">
                  {agents.length === 0 ? (
                    <div className="text-xs text-center py-6" style={{ color: "rgba(255,255,255,0.2)" }}>
                      Initializing agents...
                    </div>
                  ) : (
                    agents.map((agent, i) => (
                      <motion.div
                        key={agent.id}
                        className="flex items-center gap-3 py-2"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: i * 0.05 }}
                      >
                        <div
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{
                            background: agent.reputation >= 0.7 ? "var(--neon-green)" : "var(--neon-orange)",
                            boxShadow: `0 0 6px ${agent.reputation >= 0.7 ? "rgba(0,255,136,0.6)" : "rgba(255,107,53,0.6)"}`,
                          }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium truncate">{agent.specialization}</span>
                            <span className="text-xs shrink-0" style={{ color: "rgba(255,255,255,0.3)" }}>{agent.type}</span>
                          </div>
                        </div>
                        <div className="data-value text-xs shrink-0" style={{ color: convictionColor(agent.reputation || 0) }}>
                          {((agent.reputation || 0) * 100).toFixed(0)}%
                        </div>
                      </motion.div>
                    ))
                  )}
                </div>
              </div>

              {/* Live Activity Feed */}
              <div className="glass-liquid rounded-2xl p-5 flex-1">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-semibold">Live Activity</h2>
                  <div
                    className="flex items-center gap-1.5 text-xs"
                    style={{ color: wsConnected ? "var(--neon-green)" : "var(--neon-orange)" }}
                  >
                    <div
                      className="w-1.5 h-1.5 rounded-full agent-active"
                      style={{ background: "currentColor" }}
                    />
                    {wsConnected ? "Live" : "Connecting"}
                  </div>
                </div>

                <div className="space-y-1.5 panel-scroll max-h-64">
                  {liveActivity.length === 0 ? (
                    <div className="text-xs text-center py-6" style={{ color: "rgba(255,255,255,0.2)" }}>
                      Awaiting events...
                    </div>
                  ) : (
                    <AnimatePresence>
                      {liveActivity.map((event, i) => (
                        <motion.div
                          key={`${event}-${i}`}
                          className="text-xs py-1.5 px-2 rounded-lg"
                          style={{
                            background: "rgba(255,255,255,0.03)",
                            color: i === 0 ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.4)",
                            fontFamily: "var(--font-mono)",
                          }}
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                        >
                          {event}
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  )}
                </div>
              </div>

              {/* MCP Connection Info */}
              <div className="glass-liquid rounded-2xl p-5">
                <h2 className="text-sm font-semibold mb-3">MCP Connection</h2>
                <div className="text-xs font-mono space-y-2" style={{ color: "rgba(255,255,255,0.5)" }}>
                  <div className="flex justify-between">
                    <span>Endpoint</span>
                    <span style={{ color: "var(--neon-cyan)" }}>:4000/mcp</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Tools available</span>
                    <span style={{ color: "var(--neon-green)" }}>40+</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Protocol</span>
                    <span>MCP 1.0</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
