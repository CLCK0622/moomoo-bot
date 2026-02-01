# backend/seed_watchlist.py
from db import get_db_connection

INITIAL_STOCKS = [
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "type": "stock"},
    {"symbol": "AMD", "name": "Advanced Micro Devices, Inc.", "type": "stock"},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "type": "stock"},
    {"symbol": "MU", "name": "Micron Technology, Inc.", "type": "stock"},
    {"symbol": "SMCI", "name": "Super Micro Computer, Inc.", "type": "stock"},
    {"symbol": "ARM", "name": "Arm Holdings plc", "type": "stock"},
    {"symbol": "ASML", "name": "ASML Holding N.V.", "type": "stock"},
    {"symbol": "MRVL", "name": "Marvell Technology, Inc.", "type": "stock"},
    {"symbol": "AEIS", "name": "Advanced Energy Industries, Inc.", "type": "stock"},
    {"symbol": "ONTO", "name": "Onto Innovation Inc.", "type": "stock"},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "type": "stock"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "type": "stock"},
    {"symbol": "ADBE", "name": "Adobe Inc.", "type": "stock"},
    {"symbol": "PLTR", "name": "Palantir Technologies Inc.", "type": "stock"},
    {"symbol": "AI", "name": "C3.ai, Inc.", "type": "stock"},
    {"symbol": "SNOW", "name": "Snowflake Inc.", "type": "stock"},
    {"symbol": "NET", "name": "Cloudflare, Inc.", "type": "stock"},
    {"symbol": "DDOG", "name": "Datadog, Inc.", "type": "stock"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "type": "stock"},
    {"symbol": "META", "name": "Meta Platforms, Inc.", "type": "stock"},
    {"symbol": "AMZN", "name": "Amazon.com, Inc.", "type": "stock"},
    {"symbol": "NFLX", "name": "Netflix, Inc.", "type": "stock"},
    {"symbol": "UBER", "name": "Uber Technologies, Inc.", "type": "stock"},
    {"symbol": "XOM", "name": "Exxon Mobil Corporation", "type": "stock"},
    {"symbol": "CVX", "name": "Chevron Corporation", "type": "stock"},
    {"symbol": "OXY", "name": "Occidental Petroleum Corporation", "type": "stock"},
    {"symbol": "COP", "name": "ConocoPhillips", "type": "stock"},
    {"symbol": "DVN", "name": "Devon Energy Corporation", "type": "stock"},
    {"symbol": "MRO", "name": "Marathon Oil Corporation", "type": "stock"},
    {"symbol": "FCX", "name": "Freeport-McMoRan Inc.", "type": "stock"},
    {"symbol": "SCCO", "name": "Southern Copper Corporation", "type": "stock"},
    {"symbol": "TECK", "name": "Teck Resources Limited", "type": "stock"},
    {"symbol": "ZIM", "name": "ZIM Integrated Shipping Services Ltd.", "type": "stock"},
    {"symbol": "CAT", "name": "Caterpillar Inc.", "type": "stock"},
    {"symbol": "GE", "name": "GE Aerospace", "type": "stock"},
    {"symbol": "BA", "name": "The Boeing Company", "type": "stock"},
    {"symbol": "LMT", "name": "Lockheed Martin Corporation", "type": "stock"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "type": "stock"},
    {"symbol": "GS", "name": "The Goldman Sachs Group, Inc.", "type": "stock"},
    {"symbol": "MS", "name": "Morgan Stanley", "type": "stock"},
    {"symbol": "BAC", "name": "Bank of America Corporation", "type": "stock"},
    {"symbol": "C", "name": "Citigroup Inc.", "type": "stock"},
    {"symbol": "AXP", "name": "American Express Company", "type": "stock"},
    {"symbol": "PYPL", "name": "PayPal Holdings, Inc.", "type": "stock"},
    {"symbol": "SQ", "name": "Block, Inc.", "type": "stock"},
    {"symbol": "V", "name": "Visa Inc.", "type": "stock"},
    {"symbol": "LLY", "name": "Eli Lilly and Company", "type": "stock"},
    {"symbol": "NVO", "name": "Novo Nordisk A/S", "type": "stock"},
    {"symbol": "MRNA", "name": "Moderna, Inc.", "type": "stock"},
    {"symbol": "BIIB", "name": "Biogen Inc.", "type": "stock"},
    {"symbol": "ILMN", "name": "Illumina, Inc.", "type": "stock"},
    {"symbol": "DXCM", "name": "DexCom, Inc.", "type": "stock"},
    {"symbol": "VRTX", "name": "Vertex Pharmaceuticals Incorporated", "type": "stock"},
    {"symbol": "UNH", "name": "UnitedHealth Group Incorporated", "type": "stock"},
    {"symbol": "ISRG", "name": "Intuitive Surgical, Inc.", "type": "stock"},
    {"symbol": "NKE", "name": "NIKE, Inc.", "type": "stock"},
    {"symbol": "RIVN", "name": "Rivian Automotive, Inc.", "type": "stock"},
    {"symbol": "COST", "name": "Costco Wholesale Corporation", "type": "stock"},
    {"symbol": "WMT", "name": "Walmart Inc.", "type": "stock"},
    {"symbol": "MCD", "name": "McDonald's Corporation", "type": "stock"}
]

def seed():
    conn = get_db_connection()
    cur = conn.cursor()

    print(f"🌱 Seeding Watchlist with {len(INITIAL_STOCKS)} stocks...")

    for stock in INITIAL_STOCKS:
        cur.execute("""
            INSERT INTO "Watchlist" (symbol, name, type, "isActive")
            VALUES (%s, %s, %s, true)
            ON CONFLICT (symbol) DO NOTHING;
        """, (stock["symbol"], stock["name"], stock["type"]))

    conn.commit()
    cur.close()
    conn.close()

    print("✅ Seed Complete!")

if __name__ == "__main__":
    seed()
