"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

interface SentimentData {
    signal: "BUY" | "SELL" | "HOLD" | "STRONG BUY" | "STRONG SELL";
    score: number;
    summary: string;
    catalyst_cn?: string;
    updated_at: string;
}

interface StockCardProps {
    symbol: string;
    price: number;
    change: number;
    onRemove: (symbol: string) => void;
    disabled?: boolean;
    preMarket?: { price: number; change: number };
    postMarket?: { price: number; change: number };
    marketPhase?: string;
    sentiment?: SentimentData;
    isLoadingSentiment?: boolean;
}

export function StockCard({ symbol, price, change, onRemove, disabled, preMarket, postMarket, marketPhase = "CLOSED", sentiment, isLoadingSentiment }: StockCardProps) {
    const [isRemoveOpen, setIsRemoveOpen] = useState(false);

    // Determine what to display based on API-provided market phase
    let mainPrice = price;
    let mainChange = change;
    let label = "收盘";

    if (marketPhase === "REGULAR") {
        label = "交易中";
    } else if (marketPhase === "PRE" && preMarket && preMarket.price > 0) {
        mainPrice = preMarket.price;
        mainChange = preMarket.change;
        label = "盘前";
    } else if (marketPhase === "POST" && postMarket && postMarket.price > 0) {
        mainPrice = postMarket.price;
        mainChange = postMarket.change;
        label = "盘后";
    } else if (marketPhase === "OVERNIGHT" && postMarket && postMarket.price > 0) {
        mainPrice = postMarket.price;
        mainChange = postMarket.change;
        label = "夜盘";
    } else if (marketPhase === "CLOSED") {
        // If closed and postMarket data available, show it
        if (postMarket && postMarket.price > 0) {
            mainPrice = postMarket.price;
            mainChange = postMarket.change;
            label = "盘后";
        } else {
            label = "收盘";
        }
    }

    const isPositive = mainChange >= 0;
    const isRegularPositive = change >= 0;

    // Sentiment Logic
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

    return (
        <div className="bg-white rounded-xl p-6 flex justify-between items-center shadow-sm hover:shadow-md transition-all duration-300 border border-slate-100 group stock-card-fallback relative">
            <Dialog open={isRemoveOpen} onOpenChange={setIsRemoveOpen}>
                <DialogTrigger asChild>
                    <button
                        disabled={disabled}
                        className={cn(
                            "absolute top-2 right-2 p-1.5 rounded-full text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all opacity-0 group-hover:opacity-100",
                            disabled && "hidden"
                        )}
                        title="从自选股移除"
                    >
                        <X size={16} />
                    </button>
                </DialogTrigger>
                <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>确认移除 {symbol}?</DialogTitle>
                        <DialogDescription>
                            此操作将从您的自选股列表中移除该股票。
                        </DialogDescription>
                    </DialogHeader>
                    <div className="flex justify-end gap-2 mt-4">
                        <Button variant="outline" onClick={() => setIsRemoveOpen(false)}>取消</Button>
                        <Button variant="destructive" onClick={() => { onRemove(symbol); setIsRemoveOpen(false); }}>确认移除</Button>
                    </div>
                </DialogContent>
            </Dialog>

            <div className="w-full">
                <div className="flex justify-between items-start">
                    <h3 className="text-xl font-bold text-slate-900">{symbol}</h3>
                    <div className="flex items-center gap-2">
                        {/* Sentiment Badge */}
                        {isLoadingSentiment ? (
                            <Skeleton className="h-5 w-16" />
                        ) : sentiment ? (
                            <Dialog>
                                <DialogTrigger asChild>
                                    <Badge className={cn("cursor-pointer", getSignalColor(sentiment.signal))}>
                                        {sentiment.signal} {sentiment.score}
                                    </Badge>
                                </DialogTrigger>
                                <DialogContent className="max-w-2xl">
                                    <DialogHeader>
                                        <DialogTitle className="flex items-center gap-2">
                                            {symbol} AI 分析报告
                                            <Badge className={getSignalColor(sentiment.signal)}>{sentiment.signal}</Badge>
                                        </DialogTitle>
                                        <DialogDescription>
                                            更新时间: {new Date(sentiment.updated_at).toLocaleString()}
                                        </DialogDescription>
                                    </DialogHeader>
                                    <ScrollArea className="h-[400px] w-full rounded-md border p-4 bg-slate-50 mt-2">
                                        <div className="space-y-4">
                                            {sentiment.catalyst_cn && (
                                                <div className="bg-white p-3 rounded-lg border border-slate-100 shadow-sm">
                                                    <h4 className="font-semibold mb-1 text-slate-900">核心驱动</h4>
                                                    <p className="text-slate-600 text-sm leading-relaxed">{sentiment.catalyst_cn}</p>
                                                </div>
                                            )}

                                            <div className="whitespace-pre-wrap text-slate-700 text-sm leading-relaxed">
                                                {sentiment.summary}
                                            </div>
                                        </div>
                                    </ScrollArea>
                                </DialogContent>
                            </Dialog>
                        ) : (
                            <Badge variant="outline" className="text-slate-400 border-slate-200">Waiting...</Badge>
                        )}

                        <span className="text-xs font-medium text-slate-400 bg-slate-50 px-2 py-1 rounded-md">
                            {label}
                        </span>
                    </div>
                </div>

                {/* Main Price Display */}
                <div className="flex items-end gap-2 mt-2">
                    <span className="text-3xl font-bold text-slate-900 tracking-tight">
                        ${mainPrice.toFixed(2)}
                    </span>
                    <span className={cn(
                        "text-sm font-semibold mb-1 px-1.5 py-0.5 rounded",
                        isPositive ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    )}>
                        {isPositive ? "+" : ""}{mainChange.toFixed(2)}%
                    </span>
                </div>

                {/* Secondary/Label Display - Now on new line and cleaner */}
                {label !== "交易中" && label !== "收盘" && (
                    <div className="mt-2 pt-2 border-t border-slate-50 flex flex-col">
                        <span className="text-xs text-slate-400 mb-0.5">收盘价</span>
                        <span className="text-sm text-slate-600 font-mono flex items-center gap-2">
                            ${price.toFixed(2)}
                            <span className={cn(
                                "text-xs",
                                isRegularPositive ? "text-green-600" : "text-red-600"
                            )}>
                                ({isRegularPositive ? "+" : ""}{change.toFixed(2)}%)
                            </span>
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}
