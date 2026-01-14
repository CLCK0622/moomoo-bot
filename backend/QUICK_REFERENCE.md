# 🚀 Trading System - Quick Reference

## ✅ All Issues Fixed

1. ✅ **Account**: FUTUSG (was: FUTUSECURITIES)  
2. ✅ **Database Sync**: Immediate after orders
3. ✅ **Trade Logs**: TradeRecord/TradeLog integrated
4. ✅ **Analysis Time**: 07:00 AM ET (was: 08:00)
5. ✅ **Order Type**: NORMAL with limit prices (was: MARKET)
6. ✅ **Dashboard**: Shows correct totals

## 🎯 Start Trading

```bash
# Main trading loop (auto-analysis + auto-sniper + monitoring)
python monitor.py

# Manual analysis only
python run_analysis.py

# Check account
python check_accounts.py

# View dashboard
python dashboard.py
```

## 📊 Key Times (US Eastern)

- **07:00 AM** - Auto-analysis (DailyCandidate)
- **09:25 AM** - Opening sniper starts
- **09:30 AM** - Market opens
- **09:35 AM** - Sniper ends, switches to watch mode
- **15:55 PM** - Force close all positions

## 🛡️ Safety Features

- **Circuit Breaker**: -$200 max loss per stock per day
- **Hard Stop Loss**: -1% from cost price
- **Trailing Stop**: Dynamic based on profit level
- **Position Sizing**: Total assets / 1.2 / num stocks

## 📈 Strategy

### Entry
- Opening surge > +0.5%: Chase
- Opening drop > -1%: Skip, watch for reversal
- Flat open: Wait for breakout (+0.2%)

### Exit
- **Phase 1** (gain < 3%): Stop at high - 1.5%
- **Phase 2** (gain ≥ 3%): Lock 80% of profit
- **Hard stop**: -1% from cost (always active)
- **EOD**: Close all at 15:55

## 🔍 Monitor Database

```sql
-- Active positions
SELECT * FROM "TradePosition" WHERE status = 'OPEN';

-- Active monitors
SELECT * FROM "StockMonitor" WHERE "isActive" = true;

-- Today's candidates  
SELECT * FROM "DailyCandidate" 
WHERE date = CURRENT_DATE 
ORDER BY "sentimentScore" DESC;
```

## ⚠️ Before Live Trading

1. Set `CURRENT_ENV = TrdEnv.REAL` in `trader.py`
2. Verify `TRADING_PASSWORD` in `config.py`
3. Test with small positions first
4. Monitor first few trades closely

## 📞 Emergency Stop

```bash
# Stop monitor
Ctrl+C

# Force close all positions
python clear_account.py
```

---
**Status**: ✅ Production Ready  
**Last Updated**: Jan 12, 2026  
**Mode**: SIMULATE (change to REAL when ready)

