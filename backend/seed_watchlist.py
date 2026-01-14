# backend/seed_watchlist.py
from db import get_db_connection

INITIAL_STOCKS = [
    # --- Uranium / Nuclear ---
    {"symbol": "DNN", "name": "Denison Mines Corp.", "type": "stock"},
    {"symbol": "UUUU", "name": "Energy Fuels Inc.", "type": "stock"},
    {"symbol": "CCJ", "name": "Cameco Corporation", "type": "stock"},
    {"symbol": "UEC", "name": "Uranium Energy Corp.", "type": "stock"},
    {"symbol": "NXE", "name": "NexGen Energy Ltd.", "type": "stock"},
    {"symbol": "LEU", "name": "Centrus Energy Corp.", "type": "stock"},
    {"symbol": "SMR", "name": "NuScale Power Corporation", "type": "stock"},
    {"symbol": "OKLO", "name": "Oklo Inc.", "type": "stock"},
    {"symbol": "BWXT", "name": "BWX Technologies, Inc.", "type": "stock"},
    {"symbol": "NNE", "name": "Nano Nuclear Energy Inc.", "type": "stock"},

    # --- Utilities / Power ---
    {"symbol": "CEG", "name": "Constellation Energy Corporation", "type": "stock"},
    {"symbol": "DUK", "name": "Duke Energy Corporation", "type": "stock"},
    {"symbol": "EXC", "name": "Exelon Corporation", "type": "stock"},
    {"symbol": "NEE", "name": "NextEra Energy, Inc.", "type": "stock"},
    {"symbol": "SO", "name": "The Southern Company", "type": "stock"},
    {"symbol": "VST", "name": "Vistra Corp.", "type": "stock"},
    {"symbol": "TLN", "name": "Talen Energy Corporation", "type": "stock"},

    # --- Electrical / Industrial ---
    {"symbol": "ETN", "name": "Eaton Corporation plc", "type": "stock"},
    {"symbol": "GEV", "name": "GE Vernova Inc.", "type": "stock"},
    {"symbol": "SIEGY", "name": "Siemens AG (ADR)", "type": "stock"},
    {"symbol": "VRT", "name": "Vertiv Holdings Co.", "type": "stock"},

    # --- Semiconductors / AI Infrastructure ---
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "type": "stock"},
    {"symbol": "AMD", "name": "Advanced Micro Devices, Inc.", "type": "stock"},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "type": "stock"},
    {"symbol": "TSM", "name": "Taiwan Semiconductor Manufacturing Company", "type": "stock"},
    {"symbol": "ASML", "name": "ASML Holding N.V.", "type": "stock"},
    {"symbol": "COHR", "name": "Coherent Corp.", "type": "stock"},
    {"symbol": "LITE", "name": "Lumentum Holdings Inc.", "type": "stock"},
    {"symbol": "ANET", "name": "Arista Networks, Inc.", "type": "stock"},
    {"symbol": "CSCO", "name": "Cisco Systems, Inc.", "type": "stock"},
    {"symbol": "MU", "name": "Micron Technology, Inc.", "type": "stock"},
    {"symbol": "NTAP", "name": "NetApp, Inc.", "type": "stock"},
    {"symbol": "PSTG", "name": "Pure Storage, Inc.", "type": "stock"},

    # --- Aerospace / Defense ---
    {"symbol": "HEI", "name": "HEICO Corporation", "type": "stock"},
    {"symbol": "ATRO", "name": "Astronics Corporation", "type": "stock"},
    {"symbol": "RTX", "name": "RTX Corporation", "type": "stock"},
    {"symbol": "BA", "name": "The Boeing Company", "type": "stock"},
    {"symbol": "LMT", "name": "Lockheed Martin Corporation", "type": "stock"},
    {"symbol": "NOC", "name": "Northrop Grumman Corporation", "type": "stock"},

    # --- Space / Satellite ---
    {"symbol": "PL", "name": "Planet Labs PBC", "type": "stock"},
    {"symbol": "BKSY", "name": "BlackSky Technology Inc.", "type": "stock"},
    {"symbol": "SPIR", "name": "Spire Global, Inc.", "type": "stock"},
    {"symbol": "ASTS", "name": "AST SpaceMobile, Inc.", "type": "stock"},
    {"symbol": "SATS", "name": "EchoStar Corporation", "type": "stock"},
    {"symbol": "IRDM", "name": "Iridium Communications Inc.", "type": "stock"},
    {"symbol": "VSAT", "name": "Viasat, Inc.", "type": "stock"},
    {"symbol": "TSAT", "name": "Telesat Corporation", "type": "stock"},
    {"symbol": "RKLB", "name": "Rocket Lab USA, Inc.", "type": "stock"},
    {"symbol": "SPCE", "name": "Virgin Galactic Holdings, Inc.", "type": "stock"},
    {"symbol": "LUNR", "name": "Intuitive Machines, Inc.", "type": "stock"},
    {"symbol": "RDW", "name": "Redwire Corporation", "type": "stock"},

    # --- Materials / Mining ---
    {"symbol": "MP", "name": "MP Materials Corp.", "type": "stock"},
    {"symbol": "IDR", "name": "Idaho Strategic Resources, Inc.", "type": "stock"},
    {"symbol": "FCX", "name": "Freeport-McMoRan Inc.", "type": "stock"},
    {"symbol": "SCCO", "name": "Southern Copper Corporation", "type": "stock"},
    {"symbol": "ALB", "name": "Albemarle Corporation", "type": "stock"},
    {"symbol": "LAC", "name": "Lithium Americas Corp.", "type": "stock"},
    {"symbol": "SQM", "name": "Sociedad Química y Minera de Chile S.A.", "type": "stock"},

    # --- AI / Software / Infra ---
    {"symbol": "ARM", "name": "Arm Holdings plc", "type": "stock"},
    {"symbol": "MTSR", "name": "Metsera, Inc.", "type": "stock"},
    {"symbol": "RVMD", "name": "Revolution Medicines, Inc.", "type": "stock"},
    {"symbol": "FRSH", "name": "Freshworks Inc.", "type": "stock"},
    {"symbol": "TEM", "name": "Tempus AI, Inc.", "type": "stock"},
    {"symbol": "GTLB", "name": "GitLab Inc.", "type": "stock"},
    {"symbol": "PATH", "name": "UiPath Inc.", "type": "stock"},
    {"symbol": "PRME", "name": "Prime Medicine, Inc.", "type": "stock"},

    # --- Healthcare / Biotech ---
    {"symbol": "ABBV", "name": "AbbVie Inc.", "type": "stock"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "type": "stock"},
    {"symbol": "AZN", "name": "AstraZeneca PLC", "type": "stock"},
    {"symbol": "LLY", "name": "Eli Lilly and Company", "type": "stock"},
    {"symbol": "NVO", "name": "Novo Nordisk A/S", "type": "stock"},
    {"symbol": "VKTX", "name": "Viking Therapeutics, Inc.", "type": "stock"},
    {"symbol": "ALT", "name": "Altimmune, Inc.", "type": "stock"},
    {"symbol": "NTLA", "name": "Intellia Therapeutics, Inc.", "type": "stock"},
    {"symbol": "BEAM", "name": "Beam Therapeutics Inc.", "type": "stock"},
    {"symbol": "CRSP", "name": "CRISPR Therapeutics AG", "type": "stock"},
    {"symbol": "ABCL", "name": "AbCellera Biologics Inc.", "type": "stock"},
    {"symbol": "BSX", "name": "Boston Scientific Corporation", "type": "stock"},
    {"symbol": "ISRG", "name": "Intuitive Surgical, Inc.", "type": "stock"},
    {"symbol": "ILMN", "name": "Illumina, Inc.", "type": "stock"},
    {"symbol": "SYK", "name": "Stryker Corporation", "type": "stock"},
    {"symbol": "UNH", "name": "UnitedHealth Group Incorporated", "type": "stock"},
    {"symbol": "OSCR", "name": "Oscar Health, Inc.", "type": "stock"},
    {"symbol": "CVS", "name": "CVS Health Corporation", "type": "stock"},
    {"symbol": "TMO", "name": "Thermo Fisher Scientific Inc.", "type": "stock"},
    {"symbol": "DHR", "name": "Danaher Corporation", "type": "stock"},
    {"symbol": "IQV", "name": "IQVIA Holdings Inc.", "type": "stock"},
    {"symbol": "MEDP", "name": "Medpace Holdings, Inc.", "type": "stock"},
    {"symbol": "PTGX", "name": "Protagonist Therapeutics, Inc.", "type": "stock"},

    # --- Crypto / Energy Infra ---
    {"symbol": "NBIS", "name": "Nebius Group N.V.", "type": "stock"},
    {"symbol": "CRWV", "name": "CoreWeave, Inc.", "type": "stock"},
    {"symbol": "IREN", "name": "Iris Energy Limited", "type": "stock"},
    {"symbol": "HUT", "name": "Hut 8 Corp.", "type": "stock"},

    # --- Misc ---
    {"symbol": "ALAB", "name": "Astera Labs, Inc.", "type": "stock"},
    {"symbol": "SKYT", "name": "SkyWater Technology, Inc.", "type": "stock"},
    {"symbol": "PLTR", "name": "Palantir Technologies Inc.", "type": "stock"},
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
