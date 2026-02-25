# agents.py
import json
from openai import OpenAI
from config import *


from tools import *
import os
import datetime

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class BaseAgent:
    def __init__(self, model):
        self.model = model

    def call_llm(self, system, user):
        try:
            resp = client.chat.completions.create(
                model=self.model,
                # reasoning={
                #     "effort": "medium"
                # },
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
            content = resp.choices[0].message.content
            # 尝试清洗 Markdown
            return json.loads(content.replace("```json", "").replace("```", "").strip())
        except Exception as e:
            print(f"LLM Error: {e}")
            return None

# --- 1. 采集型 Agent (Temp 0.3) ---
class CollectorAgent(BaseAgent):
    def __init__(self, source_type):
        self.source = source_type
        # 这一版不需要 model 了，因为只是搬运数据
        self.model = None

    def run(self, symbol, queries):
        print(f"    Running {self.source} Collector for {symbol}...")

        # 局部引用防止循环依赖
        from tools import search_gnews_broad, search_ddg_broad, search_nitter_broad

        results = []
        try:
            if self.source == "GNews":
                results = search_gnews_broad(queries)
            elif self.source == "DDG":
                results = search_ddg_broad(queries)
            elif self.source == "Nitter":
                results = search_nitter_broad(queries)
        except Exception as e:
            print(f"    ⚠️ {self.source} Error: {e}")
            results = []

        # 关键修正：确保永远返回列表，如果是 None 则变为空列表
        return results if results is not None else []

# --- 4. 高级分析师 Agent ---
class SeniorAgent(BaseAgent):
    def __init__(self):
        super().__init__(MODEL_EXECUTIVE)

    def run_scoring_analysis(self, asset_info, raw_events, market_context):
        symbol = asset_info['symbol']
        name = asset_info['name']

        print(f"🎩 Senior Analyst Scoring {symbol} (-8 to +8)...")

        events_text = ""
        for i, e in enumerate(raw_events[:10]):
            events_text += f"{i + 1}. [{e['source']}] {e['timestamp']}: {e['content']}\n"
        if not events_text: events_text = "No recent news."

        system_prompt = f"""
        You are an Aggressive Proprietary Trader.
        Analyze {name} ({symbol}) for the **UPCOMING SESSION**.

        **INPUTS:**
        [MARKET TAPE]:
        {market_context}

        [NEWS STREAM]:
        {events_text}

        **SCORING SYSTEM (-8 to +8):**
        * **+8 (Max Conviction Buy):** Huge Catalyst (Earnings Beat, New Product) + Bullish Tape (Green Volume).
        * **+4 to +7 (Buy Zone):** Good Catalyst OR Strong Technical Breakout. Worth a shot.
        * **-3 to +3 (Noise):** Conflicting signals, low volume, or boring news.
        * **-4 to -7 (Sell Zone):** Bad News OR Breakdown.
        * **-8 (Max Conviction Sell):** Fraud, lawsuit, crash mode.

        **PHILOSOPHY:**
        * We are here to make money. If there is a 60% chance of going up, Score it +4 or +5.
        * Do NOT be overly conservative. "Wait and see" makes no money.
        * If the chart looks good (Green candles) even without news, that is valid momentum (+4).

        **OUTPUT FORMAT (JSON):**
        {{
            "score": (int -8 to +8),
            
            "primary_catalyst_en": "Short summary in ENGLISH. (Use for Search Verification, e.g. 'Q3 Earnings beat estimates by 20%')",
            "primary_catalyst_cn": "Short summary in SIMPLIFIED CHINESE. (For Report Display)",
            
            "impact_analysis": "Detailed explanation in CHINESE on how this affects price.",
            "key_levels": "Support/Resistance levels in CHINESE.",
            "trade_plan": "Brief actionable advice in CHINESE. (e.g. '建议开盘即刻买入。'"
        }}
        """

        return self.call_llm(system_prompt, "Score this setup.")


# ---------------------------------------------------------
# 2. Reviewer Agent (扣分员: 规则更新)
# ---------------------------------------------------------
class ReviewerAgent(BaseAgent):
    def __init__(self):
        super().__init__(MODEL_EXECUTIVE)

    def check_catalyst(self, symbol, catalyst_claim, current_score):
        if abs(current_score) < 4:
            return 0

        print(f"  🕵️ Reviewer: Fact-checking '{catalyst_claim}'...")

        from tools import search_ddg_broad
        query = f"{symbol} {catalyst_claim} truth check"
        evidence = search_ddg_broad([query])
        evidence_text = "\n".join([f"- {e['content']}" for e in evidence[:3]])

        # 🚀 这里的 Prompt 已经根据你的要求更新了
        system_prompt = f"""
        You are a Risk Manager.
        The Trader wants to execute based on: "{catalyst_claim}".
        Current Score: {current_score}

        **EVIDENCE:**
        {evidence_text}

        **TASK:**
        Verify if the claim is FACTUALLY WRONG or OLD.

        **PENALTY RULES (Apply Strict Logic):**
        1. **FALSE / FAKE / DEBUNKED:** Penalty = +/-5. (The catalyst is simply not true).
        2. **OLD NEWS (Stale / Priced In):** Penalty = +/-3. (Market reacted days ago, no new juice).
        3. **OLD NEWS (But has Lasting Impact):** Penalty = +/-1. (It's a few days old but fundamentally changes the valuation long-term).
        4. **UNCERTAIN / UNCONFIRMED:** Penalty = 0. (If you can't prove it's false, don't block the trade. Let the trend decide).
        5. **TRUE & FRESH:** Penalty = 0.

        **NOTICE:**
        Please notice that you MUST consider past market reaction (real data) to the catalyst for determining case 2 from case 3.
        If current_score is negative, then please note that your penalty should be positive (e.g. 6 to 3 and -6 to -3), and vice versa. (Generally, the punishment is adjusted towards the direction of 0 to AVOID FURTHER MOVEMENT for these stocks.)

        **OUTPUT JSON:**
        {{
            "penalty": (int),
            "reason": "Explain the penalty in Simplified Chinese (e.g. '新闻是2023年的旧闻'). Make sure you include precise reason."
        }}
        """

        result = self.call_llm(system_prompt, "Verify.")
        if result:
            return result

        return {"penalty": 0, "reason": "Verification failed or passed by default"}
