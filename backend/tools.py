# backend/tools.py

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from ddgs import DDGS
from config import NITTER_INSTANCE
from futu import *

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# --- 1. GNews (返回 List[Dict]) ---
def search_gnews_broad(queries):
    results = []
    seen_titles = set()

    for q in queries:
        # 强制只搜过去 1 天 (when:1d)
        url = f"https://news.google.com/rss/search?q={q}+when:1d&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                for item in root.findall('.//item')[:15]:
                    title = item.find('title').text
                    link = item.find('link').text
                    pub_date = item.find('pubDate').text

                    if title not in seen_titles:
                        results.append({
                            "source": "GNews",
                            "content": title,
                            "link": link,
                            "timestamp": pub_date
                        })
                        seen_titles.add(title)
        except Exception as e:
            print(f"    (GNews Error: {e})")

    return results


# --- 2. DDG (返回 List[Dict]) ---
def search_ddg_broad(queries):
    results = []
    ddgs = DDGS()
    for q in queries:
        try:
            # max_results 5, 过去1天
            ddg_gen = ddgs.text(f"{q}", max_results=15, timelimit='d')
            if ddg_gen:
                for r in ddg_gen:
                    results.append({
                        "source": "DDG",
                        "content": r['title'],
                        "link": r['href'],
                        "timestamp": "Recent"
                    })
        except Exception as e:
            print(f"    (DDG Error: {e})")
            pass
    return results


# --- 3. Nitter (返回 List[Dict]) ---
def search_nitter_broad(queries):
    results = []
    for q in queries:
        url = f"{NITTER_INSTANCE}/search?f=tweets&q={q}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                tweets = soup.find_all('div', class_='timeline-item', limit=25)
                for t in tweets:
                    content_div = t.find('div', class_='tweet-content')
                    link_a = t.find('a', class_='tweet-link')
                    date_span = t.find('span', class_='tweet-date')

                    if content_div:
                        link = f"{NITTER_INSTANCE}{link_a['href']}" if link_a else ""
                        date = date_span.find('a')['title'] if date_span else "Recent"
                        results.append({
                            "source": "Nitter",
                            "content": content_div.get_text(strip=True)[:150],  # 截断
                            "link": link,
                            "timestamp": date
                        })
        except Exception as e:
            # Nitter 经常超时，静默失败即可
            pass
    return results


# --- 4. Market Data (综合行情) ---
# 这一部分保持你之前最新的全量数据逻辑
MOOMOO_HOST = '127.0.0.1'
MOOMOO_PORT = 11111


def get_market_context_comprehensive(symbol):
    moomoo_symbol = f"US.{symbol}"
    try:
        quote_ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)

        # A. 周线
        ret_w, data_w = quote_ctx.get_cur_kline(moomoo_symbol, 10, KLType.K_DAY, AuType.QFQ)
        weekly_summary = "No Data"
        if ret_w == RET_OK and not data_w.empty:
            week_start = data_w.iloc[0]['close']
            week_end = data_w.iloc[-1]['close']
            week_pct = ((week_end - week_start) / week_start) * 100
            trend_str = []
            for _, row in data_w.iterrows():
                date = row['time_key'][:10]
                pct = ((row['close'] - row['open']) / row['open']) * 100
                icon = "🟢" if pct > 0 else "🔴"
                trend_str.append(f"{date}: {icon} {pct:.2f}%")
            weekly_summary = f"Change: {week_pct:.2f}%\nTrend: {' | '.join(trend_str)}"

        # B. 昨日/最近交易日 5分钟线
        ret_d, data_d = quote_ctx.get_cur_kline(moomoo_symbol, 100, KLType.K_5M, AuType.QFQ)
        intraday_summary = "No Data"
        last_date = "N/A"

        if ret_d == RET_OK and not data_d.empty:
            last_ts = data_d.iloc[-1]['time_key']
            last_date = last_ts.split(' ')[0]
            df_today = data_d[data_d['time_key'].str.contains(last_date)]

            tape_log = []
            avg_vol = df_today['volume'].mean()
            for _, row in df_today.iterrows():
                time_str = row['time_key'][11:16]
                vol = row['volume']
                if vol > avg_vol * 1.5 or time_str.endswith("00") or time_str.endswith("30"):
                    candle = "🟢" if row['close'] > row['open'] else "🔴"
                    tape_log.append(f"[{time_str}] {candle} ${row['close']:.2f} (V:{int(vol)})")
            intraday_summary = "\n".join(tape_log)

        quote_ctx.close()
        return f"=== MARKET CONTEXT ===\n[Weekly]: {weekly_summary}\n[Intraday {last_date}]:\n{intraday_summary}"

    except Exception as e:
        return f"Market Data Error: {e}"