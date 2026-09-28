"use client";

import React, { useEffect, useRef } from 'react';
import { createChart, CandlestickSeries } from 'lightweight-charts';

const TradingChart = ({ data, ticker }: { data: any[], ticker: string }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 400,
      layout: {
        background: { color: '#0a0a0a' },
        textColor: '#d1d1d1',
      },
      grid: {
        vertLines: { color: '#1a1a1a' },
        horzLines: { color: '#1a1a1a' },
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    candlestickSeries.setData(data);

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data]);

  return (
    <div className="relative w-full bg-[#0a0a0a] border border-white/10 rounded-lg overflow-hidden">
      <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
        <h3 className="text-xs font-bold text-white/50 uppercase tracking-widest">{ticker}</h3>
        <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
      </div>
      <div ref={chartContainerRef} />
    </div>
  );
};

export default TradingChart;
