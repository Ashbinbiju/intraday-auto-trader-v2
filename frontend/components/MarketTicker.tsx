import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface IndexData {
    symbol: string;
    displayName: string;
    ltp: number;
    close: number;
    changePct: number;
}

interface MarketTickerProps {
    indices: IndexData[];
}

const MarketTicker: React.FC<MarketTickerProps> = ({ indices }) => {
    if (!indices || indices.length === 0) return null;

    return (
        <div className="w-full mb-8">
            <h3 className="text-gray-400 text-sm font-semibold mb-3 uppercase tracking-wider">Market Overview</h3>
            <div className="flex gap-4 overflow-x-auto pb-4 scrollbar-hide">
                {indices.map((idx, i) => {
                    const isPositive = idx.changePct > 0;
                    const isNegative = idx.changePct < 0;
                    const colorClass = isPositive ? 'text-green-400' : isNegative ? 'text-red-400' : 'text-gray-400';
                    const bgClass = isPositive ? 'bg-green-500/10 border-green-500/20' : isNegative ? 'bg-red-500/10 border-red-500/20' : 'bg-gray-500/10 border-white/10';

                    return (
                        <div key={i} className={`min-w-[180px] p-4 rounded-xl border backdrop-blur-sm flex flex-col justify-between ${bgClass}`}>
                            <div className="flex justify-between items-start mb-2">
                                <span className="font-bold text-sm text-gray-200 truncate pr-2" title={idx.displayName || idx.symbol}>
                                    {idx.displayName || idx.symbol}
                                </span>
                                {isPositive ? <TrendingUp size={16} className={colorClass} /> : 
                                 isNegative ? <TrendingDown size={16} className={colorClass} /> : 
                                 <Minus size={16} className={colorClass} />}
                            </div>
                            <div>
                                <div className="text-lg font-bold text-white">
                                    {idx.ltp.toLocaleString('en-IN')}
                                </div>
                                <div className={`text-xs font-mono font-medium ${colorClass}`}>
                                    {isPositive ? '+' : ''}{idx.changePct}%
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default MarketTicker;
