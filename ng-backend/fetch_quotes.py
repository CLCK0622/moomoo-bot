import sys
import json
import os
import logging
import pandas as pd
from futu import *

# Suppress all logging to stdout/stderr from libraries
logging.basicConfig(level=logging.CRITICAL)

# Configuration
HOST = '127.0.0.1'
PORT = 11111
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist.json')

def get_watchlist():
    try:
        if not os.path.exists(WATCHLIST_FILE):
             print(f"Watchlist file not found at {WATCHLIST_FILE}", file=sys.stderr)
             return []
        with open(WATCHLIST_FILE, 'r') as f:
            data = json.load(f)
            return data.get('symbols', [])
    except Exception as e:
        print(f"Error reading watchlist: {e}", file=sys.stderr)
        return []

def fetch_quotes():
    symbols = get_watchlist()
    print(f"Fetching quotes for: {symbols}", file=sys.stderr)
    
    if not symbols:
        print(json.dumps([]))
        return

    # Convert symbols to Futu format (e.g., AAPL -> US.AAPL)
    # Assuming US market for now as per previous context
    futu_symbols = [f"US.{s}" for s in symbols]

    try:
        quote_ctx = OpenQuoteContext(host=HOST, port=PORT)
        
        # Subscribe to quotes to ensure we have permission/access
        ret_sub, err_message = quote_ctx.subscribe(futu_symbols, [SubType.QUOTE], subscribe_push=False)
        
        # Get Market State (using first symbol as reference, usually US.AAPL or similar)
        # We need a US stock to check US market status. 
        # If the watchlist has US stocks, use the first one.
        # If not, default to US.AAPL for market status check.
        market_ref_symbol = futu_symbols[0] if futu_symbols else 'US.AAPL'
        ret_state, state_data = quote_ctx.get_market_state([market_ref_symbol])
        market_state = "UNKNOWN"
        if ret_state == RET_OK:
            market_state = state_data['market_state'][0]
        
        ret, data = quote_ctx.get_market_snapshot(futu_symbols)
        
        quote_ctx.close()

        if ret == RET_OK:
            # Debug: Print all columns to spy on available data
            # logging.debug(f"Columns: {data.columns.tolist()}") 
            
            # Process data
            results = []
            for _, row in data.iterrows():
                code = row['code'].split('.')[-1]
                last = row['last_price']
                prev_close = row['prev_close_price']
                
                # Extended hours data
                pre_price = row.get('pre_price', 0)
                pre_change = row.get('pre_change_rate', 0)
                after_price = row.get('after_price', 0)
                after_change = row.get('after_change_rate', 0)
                
                # Standard change calculation
                change = 0
                change_rate = 0
                if prev_close > 0:
                    change = last - prev_close
                    change_rate = (change / prev_close) * 100
                    
                results.append({
                    "symbol": code,
                    "price": last,
                    "change": change_rate,
                    "changeAmount": change,
                    "preMarket": {
                        "price": pre_price if pd.notna(pre_price) else 0,
                        "change": pre_change if pd.notna(pre_change) else 0
                    },
                    "postMarket": {
                        "price": after_price if pd.notna(after_price) else 0,
                        "change": after_change if pd.notna(after_change) else 0
                    }
                })
            
            # wrapper object to include global market state
            print(json.dumps({
                "status": "ok", 
                "market_state": str(market_state),
                "data": results
            }))
        else:
            # Output the error to stdout so the API can read it
            print(json.dumps({"status": "error", "message": str(data)}))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))

if __name__ == "__main__":
    fetch_quotes()
