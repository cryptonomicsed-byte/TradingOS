import KanbanBoard from '../components/KanbanBoard';
import TradingChart from '../components/TradingChart';

export default function Home() {
  const mockData = [
    { time: '2023-01-01', open: 100, high: 105, low: 95, close: 102 },
    { time: '2023-01-02', open: 102, high: 110, low: 100, close: 108 },
  ];

  return (
    <main className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="p-6 border-b border-white/10">
        <h1 className="text-2xl font-bold tracking-tighter uppercase">TradingOS Terminal</h1>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 p-6">
        <div className="lg:col-span-2 space-y-6">
          <TradingChart ticker="BTC/USDT" data={mockData} />
          <KanbanBoard />
        </div>
        <div className="bg-[#121212] rounded-lg border border-white/10 p-4">
          <h2 className="text-sm font-bold uppercase mb-4 text-white/50">System Logs</h2>
          <div className="space-y-2 font-mono text-[10px] text-green-500/80">
            <p>[22:42:01] Grok sentiment initialized.</p>
            <p>[22:42:05] Connected to Kafka market.ticks.</p>
            <p>[22:42:10] Strategy BT-772 active.</p>
          </div>
        </div>
      </div>
    </main>
  );
}
