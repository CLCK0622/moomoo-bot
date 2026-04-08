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
    
    if not symbols:
        print(json.dumps([]))
        return

    # Convert symbols to Futu format (e.g., AAPL -> US.AAPL)
    # Assuming US market for now as per previous context
    futu_symbols = [f"US.{s}" for s in symbols]

    try:
        quote_ctx = OpenQuoteContext(host=HOST, port=PORT)
        
        # Subscribe individually so failure of indices doesn't affect watchlist
        quote_ctx.subscribe(futu_symbols, [SubType.QUOTE], subscribe_push=False)
        
        # Get Market State (using first symbol as reference, usually US.AAPL or similar)
        # We need a US stock to check US market status. 
        # If the watchlist has US stocks, use the first one.
        # If not, default to US.AAPL for market status check.
        market_ref_symbol = futu_symbols[0] if futu_symbols else 'US.AAPL'
        ret_state, state_data = quote_ctx.get_market_state([market_ref_symbol])
        market_state = "UNKNOWN"
        market_phase = "CLOSED"  # default
        if ret_state == RET_OK:
            market_state = state_data['market_state'][0]
            
            # Map raw MarketState to simplified phase for frontend
            # See futu.common.constant.MarketState for all values
            TRADING_STATES = {'MORNING', 'AFTERNOON'}
            PRE_STATES = {'PRE_MARKET_BEGIN', 'PRE_MARKET_END', 'WAITING_OPEN', 'AUCTION'}
            POST_STATES = {'AFTER_HOURS_BEGIN', 'AFTER_HOURS_END'}
            OVERNIGHT_STATES = {'OVERNIGHT', 'NIGHT_OPEN', 'NIGHT', 'NIGHT_END'}
            
            state_str = str(market_state)
            if state_str in TRADING_STATES:
                market_phase = "REGULAR"
            elif state_str in PRE_STATES:
                market_phase = "PRE"
            elif state_str in POST_STATES:
                market_phase = "POST"
            elif state_str in OVERNIGHT_STATES:
                market_phase = "OVERNIGHT"
            else:
                market_phase = "CLOSED"
        
        ret, data = quote_ctx.get_market_snapshot(futu_symbols)
        
        quote_ctx.close()

        if ret == RET_OK:
            # Debug: Print all columns to spy on available data
            # logging.debug(f"Columns: {data.columns.tolist()}") 
            
            # Process watchlist data
            watchlist_data = []
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
                    
                watchlist_data.append({
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
            
            # Fetch indices data using yfinance
            indices_data = []
            try:
                import yfinance as yf
                mapping = {'^SPX':'SPX', '^IXIC':'IXIC', '^DJI':'DJI', '^VIX':'VIX', 'GC=F':'GCmain', 'CL=F':'CLmain', 'DX-Y.NYB':'DXmain'}
                y_symbols = list(mapping.keys())
                tickers = yf.Tickers(' '.join(y_symbols))
                
                # Fetch history sequentially to avoid large thread pool overhead for 7 symbols
                for sym, t in tickers.tickers.items():
                    hist = t.history(period="5d")
                    if not hist.empty and 'Close' in hist:
                        # Drop missing data which causes NaN downstream
                        hist = hist.dropna(subset=['Close'])
                        if len(hist) >= 2:
                            last = float(hist['Close'].iloc[-1])
                            prev_close = float(hist['Close'].iloc[-2])
                            
                            # Double check it is not nan
                            if pd.notna(last) and pd.notna(prev_close):
                                change = last - prev_close
                                change_rate = (change / prev_close) * 100
                                indices_data.append({
                                    "symbol": mapping.get(sym, sym),
                                    "price": last,
                                    "change": change_rate,
                                    "changeAmount": change
                                })
            except Exception as e:
                pass # suppress stderr to avoid pm2 logging
            
            
            import math
            def sanitize_json(obj):
                if isinstance(obj, float) and math.isnan(obj):
                    return None
                elif isinstance(obj, dict):
                    return {k: sanitize_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [sanitize_json(v) for v in obj]
                return obj
            
            # wrapper object to include global market state
            payload = {
                "status": "ok", 
                "market_state": str(market_state),
                "market_phase": market_phase,
                "data": watchlist_data,
                "indices": indices_data
            }
            print(json.dumps(sanitize_json(payload)))
        else:
            # Output the error to stdout so the API can read it
            print(json.dumps({"status": "error", "message": str(data)}))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))

if __name__ == "__main__":
    fetch_quotes()
