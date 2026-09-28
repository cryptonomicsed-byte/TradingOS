"use client";

import React from 'react';
import { Kanban, TrendingUp, Shield, Activity, Search } from 'lucide-react';

const KanbanBoard = () => {
  const columns = [
    { id: 'ingested', title: 'Ingested', icon: <Search className="w-4 h-4" /> },
    { id: 'strategy', title: 'Strategy Synthesis', icon: <TrendingUp className="w-4 h-4" /> },
    { id: 'backtest', title: 'Backtesting', icon: <Activity className="w-4 h-4" /> },
    { id: 'risk', title: 'Risk Ranking', icon: <Shield className="w-4 h-4" /> },
    { id: 'live', title: 'Live Execution', icon: <Kanban className="w-4 h-4" /> },
  ];

  return (
    <div className="flex gap-4 p-6 overflow-x-auto bg-[#0a0a0a] min-h-screen text-white font-mono">
      {columns.map((col) => (
        <div key={col.id} className="flex-shrink-0 w-80 bg-[#121212] rounded-lg border border-white/10 flex flex-col">
          <div className="p-4 border-b border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-blue-400">{col.icon}</span>
              <h2 className="text-xs font-bold uppercase tracking-wider">{col.title}</h2>
            </div>
            <span className="text-[10px] text-white/30">0</span>
          </div>
          <div className="flex-1 p-2 space-y-2 overflow-y-auto bg-black/20">
            {/* Cards will be rendered here */}
            <div className="p-4 bg-[#1a1a1a] border border-white/5 rounded-md hover:border-blue-500/50 transition-colors cursor-pointer group">
               <div className="flex justify-between items-start mb-2">
                  <span className="text-[10px] text-blue-400 font-bold">#BT-772</span>
                  <span className="text-[10px] bg-blue-500/10 text-blue-400 px-1.5 py-0.5 rounded">SOL/USDT</span>
               </div>
               <p className="text-xs text-white/70 line-clamp-2 mb-3">Grok detected social spike. MTF HMA alignment confirmed.</p>
               <div className="flex items-center gap-2 opacity-30 group-hover:opacity-100 transition-opacity">
                  <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
                  <span className="text-[8px] uppercase tracking-tighter">Hermes Processing</span>
               </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default KanbanBoard;
