"use client";

import { useState, useEffect, useCallback } from "react";
import { StockCard } from "./StockCard";
import { Plus, AlertCircle, Loader2, RefreshCw, XCircle, Terminal, Maximize2, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface WatchlistData {
    symbols: string[];
}

interface PriceData {
    symbol: string;
    price: number;
    change: number;
    changeAmount?: number;
    preMarket?: { price: number; change: number };
    postMarket?: { price: number; change: number };
}

interface ApiResponse {
    status: "ok" | "error";
    data?: PriceData[];
    indices?: PriceData[];
    market_phase?: string;
    message?: string;
}

const INDEX_NAMES: Record<string, string> = {
    'SPX': '标普500',
    'IXIC': '纳斯达克',
    'DJI': '道琼斯',
    'VIX': '恐慌指数',
    'GCmain': '黄金',
    'CLmain': '原油',
    'DXmain': '美元',
    'DXY': '美元'
};

export function Watchlist() {
    const [symbols, setSymbols] = useState<string[]>([]);
    const [prices, setPrices] = useState<Record<string, PriceData>>({});
    const [indices, setIndices] = useState<PriceData[]>([]);
    const [tradingLogs, setTradingLogs] = useState<any>(null);
    const [newSymbol, setNewSymbol] = useState("");
    const [isLoading, setIsLoading] = useState(true);
    const [isRestricted, setIsRestricted] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [apiError, setApiError] = useState<string | null>(null);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [marketPhase, setMarketPhase] = useState<string>("CLOSED");
    const [isRefreshing, setIsRefreshing] = useState(false);

    // Sentiment State
    const [sentimentData, setSentimentData] = useState<Record<string, any>>({});
    const [isLoadingSentiment, setIsLoadingSentiment] = useState(false);
    const [isAddOpen, setIsAddOpen] = useState(false);

    // Service Status State
    const [serviceStatus, setServiceStatus] = useState<"running" | "stopped" | "unknown">("unknown");
    const [isTogglingService, setIsTogglingService] = useState(false);

    // View Mode State
    const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

    // Log Viewer State
    const [isLogOpen, setIsLogOpen] = useState(false);
    const [logs, setLogs] = useState("");

    // Modal State
    const [selectedSentimentSymbol, setSelectedSentimentSymbol] = useState<string | null>(null);

    const getSignalColor = (signal: string) => {
        const s = signal.toUpperCase().replace("_", " ");
        if (s.includes("STRONG BUY")) return "bg-emerald-800 hover:bg-emerald-900 text-white shadow-sm border-transparent";
        if (s.includes("STRONG SELL")) return "bg-red-900 hover:bg-red-950 text-white shadow-sm border-transparent";
        switch (s) {
            case "BUY": return "bg-green-500 hover:bg-green-600 text-white border-transparent";
            case "SELL": return "bg-red-500 hover:bg-red-600 text-white border-transparent";
            default: return "bg-yellow-500 hover:bg-yellow-600 text-white border-transparent";
        }
    };

    // Poll logs when modal is open
    useEffect(() => {
        if (!isLogOpen) return;

        const fetchLogs = async () => {
            try {
                const res = await fetch("/api/service/logs");
                if (res.ok) {
                    const text = await res.text();
                    setLogs(text);
                }
            } catch (e) {
                console.error("Failed to fetch logs:", e);
            }
        };

        fetchLogs();
        const interval = setInterval(fetchLogs, 1000); // Fast polling for logs
        return () => clearInterval(interval);
    }, [isLogOpen]);

    // Poll service status
    useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await fetch("/api/service/status");
                if (res.ok) {
                    const data = await res.json();
                    setServiceStatus(data.status);
                }
            } catch (e) {
                console.error("Failed to check service status:", e);
                setServiceStatus("unknown");
            }
        };

        checkStatus();
        const interval = setInterval(checkStatus, 5000); // Poll every 5s
        return () => clearInterval(interval);
    }, []);

    const toggleService = async () => {
        setIsTogglingService(true);
        const action = serviceStatus === "running" ? "stop" : "start";
        try {
            const res = await fetch("/api/service/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action }),
            });
            if (res.ok) {
                // Wait a bit and re-check
                setTimeout(async () => {
                    const statusRes = await fetch("/api/service/status");
                    if (statusRes.ok) {
                        const data = await statusRes.json();
                        setServiceStatus(data.status);
                    }
                    setIsTogglingService(false);
                }, 2000);
            } else {
                const err = await res.json();
                alert(`Failed to ${action} service: ${err.message}`);
                setIsTogglingService(false);
            }
        } catch (e) {
            console.error(`Failed to ${action} service:`, e);
            setIsTogglingService(false);
        }
    };



    // Fetch watchlist on mount
    useEffect(() => {
        fetchWatchlist();
    }, []);

    // Fetch sentiment on mount
    useEffect(() => {
        const fetchSentiment = async () => {
            setIsLoadingSentiment(true);
            try {
                const res = await fetch("/api/sentiment");
                if (res.ok) {
                    const json = await res.json();
                    if (json.status === "ok") {
                        setSentimentData(json.data);
                    }
                }
            } catch (error) {
                console.error("Failed to fetch sentiment:", error);
            } finally {
                setIsLoadingSentiment(false);
            }
        };
        fetchSentiment();
    }, []);

    const fetchWatchlist = async () => {
        try {
            const res = await fetch("/api/watchlist");
            if (!res.ok) throw new Error("Failed to fetch watchlist");
            const data: WatchlistData = await res.json();
            setSymbols(data.symbols);
        } catch (err) {
            setError("Failed to load watchlist");
        } finally {
            setIsLoading(false);
        }
    };

    const fetchTradingLogs = useCallback(async () => {
        try {
            const res = await fetch("/api/trading-logs");
            if (res.ok) {
                const data = await res.json();
                setTradingLogs(data);
            }
        } catch (e) {
            console.error("Failed to fetch logs:", e);
        }
    }, []);

    const fetchPrices = useCallback(async () => {
        setIsRefreshing(true);
        setApiError(null);
        try {
            const res = await fetch("/api/prices");
            if (!res.ok) throw new Error("Failed to fetch prices");

            const response: ApiResponse = await res.json();

            if (response.status === "error") {
                setApiError(response.message || "Unknown API error");
            } else if (response.data) {
                const newPrices: Record<string, PriceData> = {};
                response.data.forEach((p) => {
                    newPrices[p.symbol] = p;
                });
                setPrices(newPrices);
                if (response.indices) {
                    setIndices(response.indices);
                }
                setLastUpdated(new Date());
                if (response.market_phase) {
                    setMarketPhase(response.market_phase);
                }
            }
        } catch (err: any) {
            setApiError(err.message || "Failed to connect to data source");
        } finally {
            setIsRefreshing(false);
        }
    }, []);

    // Polling logic: 30 seconds
    useEffect(() => {
        if (symbols.length > 0) {
            fetchPrices(); // Initial fetch
            fetchTradingLogs();
            const interval = setInterval(() => {
                fetchPrices();
                fetchTradingLogs();
            }, 30000);
            return () => clearInterval(interval);
        }
    }, [symbols, fetchPrices, fetchTradingLogs]);

    const updateWatchlist = async (newSymbols: string[]) => {
        try {
            const res = await fetch("/api/watchlist", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ symbols: newSymbols }),
            });
            if (!res.ok) throw new Error("Failed to update watchlist");
            setSymbols(newSymbols);
            setNewSymbol("");
        } catch (err) {
            setError("Failed to update watchlist");
        }
    };

    const handleAddSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        // Open modal instead of adding directly
        if (!newSymbol.trim()) return;
        setIsAddOpen(true);
    };

    const confirmAdd = () => {
        const symbol = newSymbol.toUpperCase().trim();
        if (symbols.includes(symbol)) {
            setIsAddOpen(false);
            return;
        }
        updateWatchlist([...symbols, symbol]);
        setIsAddOpen(false);
    };

    const removeSymbol = (symbolToRemove: string) => {
        const updated = symbols.filter((s) => s !== symbolToRemove);
        updateWatchlist(updated);
    };

    if (isLoading) {
        return (
            <div className="flex justify-center items-center h-screen bg-slate-50">
                <Loader2 className="animate-spin text-slate-400" size={48} />
            </div>
        );
    }

    return (
        <div className="w-full max-w-[1600px] mx-auto p-4 md:p-8">
            {/* Market Indices Top Bar */}
            {indices && indices.length > 0 && (
                <div className="flex flex-nowrap overflow-x-auto gap-4 pb-4 mb-8 -mx-4 px-4 md:mx-0 md:px-0 hide-scrollbar justify-center items-stretch w-full">
                    {indices.map((idx) => {
                        const name = INDEX_NAMES[idx.symbol] || idx.symbol;
                        const isPositive = idx.change >= 0;
                        return (
                            <div key={idx.symbol} className="flex-1 min-w-[120px] max-w-[220px] bg-white rounded-xl p-3 shadow-sm border border-slate-100 shrink-0 text-center flex flex-col justify-center">
                                <div className="text-xs text-slate-500 font-medium mb-1">{name}</div>
                                <div className="text-lg font-bold text-slate-900">{idx.price.toFixed(2)}</div>
                                <div className={`text-xs font-medium flex items-center ${isPositive ? 'text-green-500' : 'text-red-500'}`}>
                                    {isPositive ? '+' : ''}{idx.change.toFixed(2)}%
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Trading Logs Section */}
            {tradingLogs && (
                <div className="mb-10">
                    <h2 className="text-xl font-bold mb-4 text-slate-800">
                        {tradingLogs.date === new Date().toLocaleDateString('en-CA') 
                            ? "今日交易日志" 
                            : `${tradingLogs.date} 交易日志 (上一个交易日)`}
                    </h2>
                    <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                        <div className="p-4 border-b border-slate-100 flex justify-between bg-slate-50/50">
                            <span className="font-semibold text-slate-600">
                                当日总收益率 (已打平): 
                                <span className={cn("ml-2", tradingLogs["今日总收益率"]?.startsWith('-') ? 'text-red-500' : 'text-green-500')}>
                                    {tradingLogs["今日总收益率"] || '0.00%'}
                                </span>
                            </span>
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm whitespace-nowrap">
                                <thead className="bg-slate-50 text-slate-600 border-b border-slate-100">
                                    <tr>
                                        <th className="px-4 py-3 font-medium">股票代码</th>
                                        <th className="px-4 py-3 font-medium">买入价格</th>
                                        <th className="px-4 py-3 font-medium">卖出原因</th>
                                        <th className="px-4 py-3 font-medium">卖出首价</th>
                                        <th className="px-4 py-3 font-medium">卖出次价</th>
                                        <th className="px-4 py-3 font-medium">独笔卖出价</th>
                                        <th className="px-4 py-3 font-medium">单票收益率</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                    {tradingLogs.logs && tradingLogs.logs.length > 0 ? (
                                        tradingLogs.logs.map((log: any, i: number) => (
                                            <tr key={i} className="hover:bg-slate-50/50 transition-colors">
                                                <td className="px-4 py-3 font-semibold text-slate-900">{log["股票代码"]}</td>
                                                <td className="px-4 py-3 text-slate-700">${log["买入价格"]}</td>
                                                <td className="px-4 py-3">
                                                    <span className={cn(
                                                        "px-2 py-1 bg-slate-100 rounded text-slate-700 text-xs font-medium",
                                                        log["卖出原因"] === 'tp1' ? 'bg-blue-50 text-blue-700' : ''
                                                    )}>
                                                        {log["卖出原因"] || '-'}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3 text-slate-700">{log["卖出价格 1"] ? `$${log["卖出价格 1"]}` : '-'}</td>
                                                <td className="px-4 py-3 text-slate-700">{log["卖出价格 2"] ? `$${log["卖出价格 2"]}` : '-'}</td>
                                                <td className="px-4 py-3 text-slate-700">{log["卖出价格"] ? `$${log["卖出价格"]}` : '-'}</td>
                                                <td className={cn("px-4 py-3 font-medium", log["收益率"]?.startsWith('-') ? 'text-red-500' : 'text-green-500')}>
                                                    {log["收益率"]}
                                                </td>
                                            </tr>
                                        ))
                                    ) : (
                                        <tr>
                                            <td colSpan={7} className="px-4 py-8 text-center text-slate-400">当日暂无交易记录</td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}

            <div className="mb-10 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                    <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight flex items-center gap-4">
                        行情看板
                        {/* Service Status Indicator & Log Trigger */}
                        <Dialog open={isLogOpen} onOpenChange={setIsLogOpen}>
                            <DialogTrigger asChild>
                                <div className={cn(
                                    "px-3 py-1 rounded-full text-sm font-medium border flex items-center gap-2 transition-all cursor-pointer hover:opacity-80",
                                    serviceStatus === "running"
                                        ? "bg-green-50 text-green-700 border-green-200"
                                        : "bg-slate-50 text-slate-500 border-slate-200"
                                )}>
                                    <span className={cn(
                                        "w-2 h-2 rounded-full",
                                        serviceStatus === "running" ? "bg-green-500 animate-pulse" : "bg-slate-400"
                                    )} />
                                    {serviceStatus === "running" ? "策略运行中" : "策略已停止"}
                                    <Terminal size={12} className="ml-1 opacity-50" />
                                </div>
                            </DialogTrigger>
                            <DialogContent className="max-w-4xl h-[80vh] flex flex-col">
                                <DialogHeader>
                                    <DialogTitle className="flex items-center gap-2">
                                        <Terminal size={20} />
                                        策略运行日志 (Real-time)
                                    </DialogTitle>
                                    <DialogDescription>
                                        显示后端服务的实时输出日志。
                                    </DialogDescription>
                                </DialogHeader>
                                <div className="flex-1 bg-slate-950 rounded-lg border border-slate-800 p-4 font-mono text-xs text-green-400 overflow-hidden relative shadow-inner">
                                    <ScrollArea className="h-full w-full">
                                        <pre className="whitespace-pre-wrap font-mono leading-relaxed pb-4">
                                            {logs || "Waiting for logs..."}
                                        </pre>
                                    </ScrollArea>
                                    <div className="absolute top-2 right-2 flex gap-2">
                                        <span className="animate-pulse bg-green-500 w-2 h-2 rounded-full"></span>
                                    </div>
                                </div>
                            </DialogContent>
                        </Dialog>
                    </h1>
                    <p className="text-slate-500 mt-2 font-medium flex items-center gap-2">
                        实时报价 (MutuOpenD)
                        {lastUpdated && (
                            <span className="text-xs bg-slate-100 px-2 py-0.5 rounded-full text-slate-400">
                                更新于: {lastUpdated.toLocaleTimeString()}
                            </span>
                        )}
                    </p>
                </div>

                <div className="flex gap-3">
                    {/* View Mode Toggle */}
                    <div className="flex bg-slate-100 rounded-lg p-1 border border-slate-200">
                        <button 
                            onClick={() => setViewMode("grid")}
                            className={cn("px-3 py-1.5 text-sm font-medium rounded-md transition-all", viewMode === "grid" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700")}
                        >
                            卡片
                        </button>
                        <button 
                            onClick={() => setViewMode("list")}
                            className={cn("px-3 py-1.5 text-sm font-medium rounded-md transition-all", viewMode === "list" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700")}
                        >
                            列表
                        </button>
                    </div>
                
                    {/* Service Control Button */}
                    <Button
                        variant={serviceStatus === "running" ? "destructive" : "default"}
                        onClick={toggleService}
                        disabled={isTogglingService}
                        className={cn(
                            "shadow-sm transition-all",
                            serviceStatus === "running" ? "bg-red-50 text-red-600 hover:bg-red-100 border-red-200" : ""
                        )}
                    >
                        {isTogglingService ? (
                            <Loader2 size={16} className="animate-spin mr-2" />
                        ) : (
                            serviceStatus === "running" ? "停止策略" : "启动策略"
                        )}
                    </Button>

                </div>
            </div>

            {/* Centered Add Input Section */}
            <div className="flex justify-center mb-8">
                <div className={cn(
                    "bg-white rounded-2xl p-2 border border-slate-100 shadow-sm transition-all duration-300 w-full max-w-2xl",
                    isRestricted ? "opacity-60 grayscale-[0.5]" : "opacity-100"
                )}>
                    <form onSubmit={handleAddSubmit} className="flex gap-2 relative">
                        <div className="relative flex-1">
                            <input
                                type="text"
                                value={newSymbol}
                                onChange={(e) => setNewSymbol(e.target.value)}
                                placeholder="输入代码添加自选股 (如 NVDA)"
                                className="w-full bg-slate-50 border-none text-slate-900 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-slate-900/10 placeholder-slate-400 transition-all font-medium text-lg"
                                disabled={isRestricted}
                            />
                        </div>

                        <Dialog open={isAddOpen} onOpenChange={setIsAddOpen}>
                            <DialogTrigger asChild>
                                <button
                                    type="submit"
                                    disabled={isRestricted || !newSymbol.trim()}
                                    className="bg-slate-900 hover:bg-slate-800 text-white px-6 py-3 rounded-xl font-semibold transition-all flex items-center disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg hover:-translate-y-0.5 active:translate-y-0"
                                >
                                    <Plus size={20} className="mr-2" />
                                    添加
                                </button>
                            </DialogTrigger>
                            <DialogContent>
                                <DialogHeader>
                                    <DialogTitle>确认添加 {newSymbol.toUpperCase()}?</DialogTitle>
                                    <DialogDescription>
                                        将 {newSymbol.toUpperCase()} 添加到您的行情看板。
                                    </DialogDescription>
                                </DialogHeader>
                                <div className="flex justify-end gap-2 mt-4">
                                    <Button variant="outline" onClick={() => setIsAddOpen(false)}>取消</Button>
                                    <Button onClick={confirmAdd}>确认添加</Button>
                                </div>
                            </DialogContent>
                        </Dialog>
                    </form>
                    {isRestricted && (
                        <p className="text-amber-600 text-sm mt-2 flex items-center font-medium px-2 pb-1">
                            <AlertCircle size={16} className="mr-2" />
                            交易时段 (06:30 - 13:00) 禁止修改自选股。
                        </p>
                    )}
                </div>
            </div>

            {apiError && (
                <div className="mb-8 bg-red-50 border border-red-100 text-red-600 px-4 py-3 rounded-lg flex items-start shadow-sm">
                    <XCircle size={20} className="mr-2 mt-0.5 shrink-0" />
                    <div>
                        <h3 className="font-semibold">数据源错误</h3>
                        <p className="text-sm mt-0.5 opacity-90">{apiError}</p>
                        <p className="text-xs mt-2 text-red-400">请检查 127.0.0.1:11111 的 Moomoo OpenD 是否连接正常</p>
                    </div>
                </div>
            )}

            {viewMode === "grid" ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6 mb-12">
                    {symbols.map((symbol) => (
                        <StockCard
                            key={symbol}
                            symbol={symbol}
                            price={prices[symbol]?.price || 0}
                            change={prices[symbol]?.change || 0}
                            preMarket={prices[symbol]?.preMarket}
                            postMarket={prices[symbol]?.postMarket}
                            marketPhase={marketPhase}
                            onRemove={removeSymbol}
                            disabled={isRestricted}
                            sentiment={sentimentData[symbol]}
                            isLoadingSentiment={isLoadingSentiment}
                        />
                    ))}
                </div>
            ) : (
                <div className="mb-12 bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm whitespace-nowrap">
                            <thead className="bg-slate-50 text-slate-600 border-b border-slate-100">
                                <tr>
                                    <th className="px-5 py-3 font-medium">代码</th>
                                    <th className="px-5 py-3 font-medium">当前价格</th>
                                    <th className="px-5 py-3 font-medium">涨跌幅</th>
                                    <th className="px-5 py-3 font-medium">盘前/盘后</th>
                                    <th className="px-5 py-3 font-medium">市场状态</th>
                                    <th className="px-5 py-3 font-medium text-right">操作</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                                {symbols.map((symbol) => {
                                    const p = prices[symbol];
                                    const price = p?.price || 0;
                                    const change = p?.change || 0;
                                    const isPositive = change > 0;
                                    const isNegative = change < 0;
                                    
                                    let extStr = "-";
                                    let extClass = "text-slate-500";
                                    if (marketPhase === "PRE" && p?.preMarket?.price) {
                                        extStr = `$${p.preMarket.price.toFixed(2)} (${p.preMarket.change >= 0 ? '+' : ''}${p.preMarket.change.toFixed(2)}%)`;
                                        extClass = p.preMarket.change >= 0 ? 'text-green-600' : 'text-red-600';
                                    } else if (marketPhase === "POST" && p?.postMarket?.price) {
                                        extStr = `$${p.postMarket.price.toFixed(2)} (${p.postMarket.change >= 0 ? '+' : ''}${p.postMarket.change.toFixed(2)}%)`;
                                        extClass = p.postMarket.change >= 0 ? 'text-green-600' : 'text-red-600';
                                    }

                                    return (
                                        <tr 
                                            key={symbol} 
                                            className="hover:bg-slate-50/70 transition-colors cursor-pointer group"
                                            onClick={() => setSelectedSentimentSymbol(symbol)}
                                        >
                                            <td className="px-5 py-4 font-bold text-slate-900 group-hover:text-blue-600 transition-colors">{symbol}</td>
                                            <td className="px-5 py-4 font-semibold text-slate-800">${price.toFixed(2)}</td>
                                            <td className={cn("px-5 py-4 font-medium", isPositive ? 'text-green-500' : isNegative ? 'text-red-500' : 'text-slate-500')}>
                                                {isPositive ? '+' : ''}{change.toFixed(2)}%
                                            </td>
                                            <td className={cn("px-5 py-4 font-medium", extClass)}>
                                                {extStr}
                                            </td>
                                            <td className="px-5 py-4 text-slate-500 text-xs">
                                                <span className={cn("px-2 py-1 rounded", marketPhase === "REGULAR" ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-600")}>
                                                    {marketPhase}
                                                </span>
                                            </td>
                                            <td className="px-5 py-4 text-right">
                                                <Button 
                                                    variant="ghost" 
                                                    size="sm"
                                                    onClick={(e) => { e.stopPropagation(); removeSymbol(symbol); }}
                                                    disabled={isRestricted}
                                                    className="text-slate-400 hover:text-red-500 hover:bg-red-50"
                                                >
                                                    <Trash2 size={16} />
                                                </Button>
                                            </td>
                                        </tr>
                                    );
                                })}
                                {symbols.length === 0 && (
                                    <tr><td colSpan={6} className="text-center py-8 text-slate-400">暂无自选股</td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {error && (
                <div className="mt-6 bg-red-50 text-red-600 px-4 py-3 rounded-lg flex items-center">
                    <AlertCircle size={20} className="mr-2" />
                    {error}
                </div>
            )}

            {/* Centralized Sentiment Modal for List View */}
            {selectedSentimentSymbol && (
                <Dialog open={selectedSentimentSymbol !== null} onOpenChange={(open) => !open && setSelectedSentimentSymbol(null)}>
                    <DialogContent className="max-w-2xl">
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                                {selectedSentimentSymbol} AI 分析报告
                                {sentimentData[selectedSentimentSymbol] ? (
                                    <Badge className={getSignalColor(sentimentData[selectedSentimentSymbol].signal)}>
                                        {sentimentData[selectedSentimentSymbol].signal}
                                    </Badge>
                                ) : (
                                    <Badge variant="outline" className="text-slate-400">Waiting...</Badge>
                                )}
                            </DialogTitle>
                            {sentimentData[selectedSentimentSymbol] && (
                                <DialogDescription>
                                    更新时间: {new Date(sentimentData[selectedSentimentSymbol].updated_at).toLocaleString()}
                                </DialogDescription>
                            )}
                        </DialogHeader>
                        
                        <ScrollArea className="h-[400px] w-full rounded-md border p-4 bg-slate-50 mt-2">
                            {isLoadingSentiment ? (
                                <div className="flex flex-col gap-4">
                                    <Skeleton className="h-6 w-1/3" />
                                    <Skeleton className="h-24 w-full" />
                                </div>
                            ) : sentimentData[selectedSentimentSymbol] ? (
                                <div className="space-y-4">
                                    {sentimentData[selectedSentimentSymbol].catalyst_cn && (
                                        <div className="bg-white p-3 rounded-lg border border-slate-100 shadow-sm">
                                            <h4 className="font-semibold mb-1 text-slate-900">核心驱动</h4>
                                            <p className="text-slate-600 text-sm leading-relaxed">{sentimentData[selectedSentimentSymbol].catalyst_cn}</p>
                                        </div>
                                    )}

                                    <div className="whitespace-pre-wrap text-slate-700 text-sm leading-relaxed">
                                        {sentimentData[selectedSentimentSymbol].summary}
                                    </div>
                                </div>
                            ) : (
                                <div className="flex justify-center items-center h-full text-slate-400">
                                    暂无分析数据
                                </div>
                            )}
                        </ScrollArea>
                    </DialogContent>
                </Dialog>
            )}
        </div>
    );
}
