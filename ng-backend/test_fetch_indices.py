import yfinance as yf
import json

mapping = {'^SPX':'SPX', '^IXIC':'IXIC', '^DJI':'DJI', '^VIX':'VIX', 'GC=F':'GCmain', 'CL=F':'CLmain', 'DX-Y.NYB':'DXmain'}
y_symbols = list(mapping.keys())
print("Fetching:", y_symbols)

tickers = yf.Tickers(' '.join(y_symbols))
indices_data = []

for sym, t in tickers.tickers.items():
    print(f"--- Fetching {sym} ---")
    try:
        hist = t.history(period="5d")
        print("History empty?", hist.empty)
        if not hist.empty:
            print(f"Length: {len(hist)}")
            if len(hist) >= 2:
                last = float(hist['Close'].iloc[-1])
                prev_close = float(hist['Close'].iloc[-2])
                change = last - prev_close
                change_rate = (change / prev_close) * 100
                print(f"Success! {sym}: Last={last}, Change={change_rate}%")
            else:
                print(f"Not enough days! Only got {len(hist)} rows for {sym}")
    except Exception as e:
        print(f"Error fetching {sym}: {e}")

