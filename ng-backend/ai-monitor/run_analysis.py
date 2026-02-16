# backend/run_analysis.py

import time
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# Add parent directory to sys.path to allow importing config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from tools import get_market_context_comprehensive
from agents import CollectorAgent, SeniorAgent, ReviewerAgent

# File paths
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'watchlist.json')
REPORT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sentiment_report.json')

def load_watchlist():
    """Load watchlist from JSON file."""
    if not os.path.exists(WATCHLIST_FILE):
        print(f"⚠️ Watchlist file not found: {WATCHLIST_FILE}")
        return []
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading watchlist: {e}")
        return []

def save_report(symbol, data):
    """Save analysis result to sentiment_report.json (update existing)."""
    report = {}
    if os.path.exists(REPORT_FILE):
        try:
            with open(REPORT_FILE, 'r', encoding='utf-8') as f:
                report = json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading existing report: {e}")
    
    # Update symbol data
    report[symbol] = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "sentiment_score": data['score'],
        "signal": data['signal'],
        "summary": data['summary'],
        "catalyst_en": data.get('catalyst_en'),
        "catalyst_cn": data.get('catalyst_cn'),
        "news_links": data.get('news_links', [])
    }
    
    try:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
        print(f"   💾 Report updated for {symbol}")
    except Exception as e:
        print(f"⚠️ Error saving report: {e}")

def main():
    print(f"🚀 [Aggressive Analysis Job] Starting... {datetime.now()}")

    # Reset report file
    try:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        print("   🧹 Previous report cleared.")
    except Exception as e:
        print(f"⚠️ Error clearing report: {e}")

    watchlist = load_watchlist()
    if not watchlist:
        print("⚠️ Watchlist empty.")
        return

    agent_gnews = CollectorAgent("GNews")
    agent_ddg = CollectorAgent("DDG")
    agent_nitter = CollectorAgent("Nitter")
    agent_senior = SeniorAgent()
    agent_reviewer = ReviewerAgent()


    for symbol_str in watchlist.get('symbols', []):
        symbol = symbol_str
        name = symbol_str  # Default name to symbol since watchlist.json only has strings
        asset = {'symbol': symbol, 'name': name}

        print(f"\n⚡ Analyzing {symbol} ({name})...")

        # 1. 搜集
        raw_intels = []
        raw_intels.extend(agent_gnews.run(symbol, [symbol]))
        raw_intels.extend(agent_ddg.run(symbol, [f"{symbol} news"]))
        raw_intels.extend(agent_nitter.run(symbol, [f"{symbol} stock"]))

        # 2. 市场数据
        market_context = get_market_context_comprehensive(symbol)

        # 3. 主打分 (获取详细中文分析)
        analysis = agent_senior.run_scoring_analysis(asset, raw_intels, market_context)

        if not analysis:
            print("   ⚠️ Senior Agent silent.")
            continue

        raw_score = analysis.get('score', 0)

        # 🚀 分离中英文驱动
        catalyst_en = analysis.get('primary_catalyst_en', 'No catalyst')
        catalyst_cn = analysis.get('primary_catalyst_cn', '无明显驱动')

        impact_analysis = analysis.get('impact_analysis', '暂无')
        key_levels = analysis.get('key_levels', '暂无')
        trade_plan = analysis.get('trade_plan', '暂无')

        print(f"   🎲 Raw Score: {raw_score}")
        print(f"      Driver (EN): {catalyst_en}")

        # 4. 复核 (使用英文去做搜索！)
        penalty = 0
        review_reason = ""

        if abs(raw_score) >= 4:
            # ✅ 关键点：这里传入 catalyst_en 给 Reviewer
            review_result = agent_reviewer.check_catalyst(symbol, catalyst_en, raw_score)

            penalty = review_result.get('penalty', 0)
            review_reason = review_result.get('reason', '')

            if penalty != 0:
                print(f"   🛑 Penalty: {penalty} | Reason: {review_reason}")

        final_score = raw_score + penalty

        # 5. 生成最终信号
        signal = "HOLD"
        if final_score >= 7:
            signal = "STRONG_BUY"
        elif final_score >= 4:
            signal = "BUY"
        elif final_score <= -7:
            signal = "STRONG_SELL"
        elif final_score <= -4:
            signal = "SELL"

        # 6. 生成中文报告 (使用 catalyst_cn)
        summary_text = (
            f"【最终决策: {signal}】 (总分: {final_score})\n"
            f"----------------------------------\n"
            f"🔥 核心驱动: {catalyst_cn}\n\n"  # ✅ 报告里显示中文
            f"📈 影响分析:\n{impact_analysis}\n\n"
            f"🎯 关键点位:\n{key_levels}\n\n"
            f"💡 操作建议:\n{trade_plan}\n"
        )

        if penalty != 0:
            summary_text += (
                f"\n⚠️ 风控修正 (Risk Adjustment):\n"
                f"初始分数 {raw_score} -> 修正后 {final_score}\n"
                f"扣分原因: {review_reason}\n"
            )

        # 存入 JSON
        links = list(set([i['link'] for i in raw_intels if i.get('link')]))[:5]
        
        save_data = {
            "score": final_score,
            "signal": signal,
            "summary": summary_text,
            "catalyst_en": catalyst_en,
            "catalyst_cn": catalyst_cn,
            "news_links": links
        }
        
        save_report(symbol, save_data)

    print("\n✅ Analysis Complete.")

if __name__ == "__main__":
    main()