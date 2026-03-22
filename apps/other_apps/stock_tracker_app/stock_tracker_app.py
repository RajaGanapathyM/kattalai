import json
import sys
import re
from datetime import datetime, timedelta
import os
from pathlib import Path
# .parent is 'myapp', .parent.parent is 'apps'
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

try:
    import yfinance as yf
except ImportError:
    yf = None

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR       =  Path(__file__).resolve().parent
WATCHLIST_FILE = os.path.join(BASE_DIR , "watchlist.json")
ALERTS_FILE    =os.path.join( BASE_DIR , "price_alerts.json")

# ── Storage helpers ───────────────────────────────────────────────────────────

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return default

def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def require_yfinance() -> dict | None:
    if yf is None:
        return {"status": "error", "message": "yfinance not installed. Run: pip install yfinance"}
    return None

def fmt_num(val, decimals=2) -> str | None:
    """Format a numeric value safely."""
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return None

def fmt_large(val) -> str | None:
    """Format large numbers as K / M / B strings."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    for unit, threshold in [("B", 1e9), ("M", 1e6), ("K", 1e3)]:
        if abs(v) >= threshold:
            return f"{v / threshold:.2f}{unit}"
    return str(round(v, 2))

# ── Command handlers ──────────────────────────────────────────────────────────

def handle_quote(args: list[str]) -> dict:
    """
    quote <SYMBOL>
    Fetch current price, day range, volume and change %.
    """
    err = require_yfinance()
    if err:
        return err

    if not args:
        return {"status": "error", "message": "Usage: quote <SYMBOL>  e.g. quote RELIANCE.NS"}

    symbol = args[0].upper()
    try:
        ticker = yf.Ticker(symbol)
        info   = ticker.fast_info

        price      = fmt_num(info.last_price)
        prev_close = fmt_num(info.previous_close)
        change     = fmt_num(price - prev_close) if price and prev_close else None
        change_pct = fmt_num((change / prev_close) * 100) if change and prev_close else None

        return {
            "status":        "ok",
            "symbol":        symbol,
            "price":         price,
            "prev_close":    prev_close,
            "change":        change,
            "change_pct":    change_pct,
            "day_high":      fmt_num(info.day_high),
            "day_low":       fmt_num(info.day_low),
            "volume":        fmt_large(info.three_month_average_volume),
            "52w_high":      fmt_num(info.year_high),
            "52w_low":       fmt_num(info.year_low),
            "market_cap":    fmt_large(info.market_cap),
            "currency":      info.currency,
            "as_of":         datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        return {"status": "error", "symbol": symbol, "message": str(e)}


def handle_info(args: list[str]) -> dict:
    """
    info <SYMBOL>
    Fetch company fundamentals: sector, P/E, EPS, dividend yield, etc.
    """
    err = require_yfinance()
    if err:
        return err

    if not args:
        return {"status": "error", "message": "Usage: info <SYMBOL>"}

    symbol = args[0].upper()
    try:
        info = yf.Ticker(symbol).info
        return {
            "status":          "ok",
            "symbol":          symbol,
            "name":            info.get("longName"),
            "sector":          info.get("sector"),
            "industry":        info.get("industry"),
            "country":         info.get("country"),
            "exchange":        info.get("exchange"),
            "pe_ratio":        fmt_num(info.get("trailingPE")),
            "forward_pe":      fmt_num(info.get("forwardPE")),
            "eps":             fmt_num(info.get("trailingEps")),
            "dividend_yield":  fmt_num(info.get("dividendYield", 0) * 100),
            "beta":            fmt_num(info.get("beta")),
            "debt_to_equity":  fmt_num(info.get("debtToEquity")),
            "roe":             fmt_num(info.get("returnOnEquity", 0) * 100),
            "revenue":         fmt_large(info.get("totalRevenue")),
            "net_income":      fmt_large(info.get("netIncomeToCommon")),
            "description":     (info.get("longBusinessSummary") or "")[:300] + "…",
        }
    except Exception as e:
        return {"status": "error", "symbol": symbol, "message": str(e)}


def handle_history(args: list[str]) -> dict:
    """
    history <SYMBOL> [days]
    Returns OHLCV data. Default: last 30 days.
    """
    err = require_yfinance()
    if err:
        return err

    if not args:
        return {"status": "error", "message": "Usage: history <SYMBOL> [days]  e.g. history TCS.NS 7"}

    symbol = args[0].upper()
    days   = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30

    try:
        df = yf.Ticker(symbol).history(period=f"{days}d")
        if df.empty:
            return {"status": "error", "symbol": symbol, "message": "No data returned."}

        rows = [
            {
                "date":   str(idx.date()),
                "open":   fmt_num(row["Open"]),
                "high":   fmt_num(row["High"]),
                "low":    fmt_num(row["Low"]),
                "close":  fmt_num(row["Close"]),
                "volume": int(row["Volume"]),
            }
            for idx, row in df.iterrows()
        ]

        first_close = rows[0]["close"]
        last_close  = rows[-1]["close"]
        period_chg  = fmt_num(((last_close - first_close) / first_close) * 100) if first_close else None

        return {
            "status":          "ok",
            "symbol":          symbol,
            "days_requested":  days,
            "rows_returned":   len(rows),
            "period_change_pct": period_chg,
            "data":            rows,
        }
    except Exception as e:
        return {"status": "error", "symbol": symbol, "message": str(e)}


def handle_compare(args: list[str]) -> dict:
    """
    compare <SYM1> <SYM2> [days]
    Compare closing-price performance of two symbols over N days.
    """
    err = require_yfinance()
    if err:
        return err

    if len(args) < 2:
        return {"status": "error", "message": "Usage: compare <SYM1> <SYM2> [days]"}

    sym1  = args[0].upper()
    sym2  = args[1].upper()
    days  = int(args[2]) if len(args) > 2 and args[2].isdigit() else 30

    def _fetch(sym):
        df = yf.Ticker(sym).history(period=f"{days}d")
        if df.empty:
            return None
        first, last = float(df["Close"].iloc[0]), float(df["Close"].iloc[-1])
        return {
            "start_price": fmt_num(first),
            "end_price":   fmt_num(last),
            "change_pct":  fmt_num(((last - first) / first) * 100),
        }

    try:
        r1, r2 = _fetch(sym1), _fetch(sym2)
        winner = None
        if r1 and r2:
            winner = sym1 if r1["change_pct"] > r2["change_pct"] else sym2

        return {
            "status":  "ok",
            "days":    days,
            sym1:      r1 or "no data",
            sym2:      r2 or "no data",
            "winner":  winner,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def handle_watchlist(args: list[str]) -> dict:
    """
    watchlist           – list all symbols
    watchlist add <SYM> – add symbol
    watchlist rm  <SYM> – remove symbol
    watchlist quotes    – fetch live quotes for all symbols
    """
    wl = load_json(WATCHLIST_FILE, [])

    if not args or args[0] == "list":
        return {"status": "ok", "count": len(wl), "watchlist": wl}

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 2:
            return {"status": "error", "message": "Usage: watchlist add <SYMBOL>"}
        sym = args[1].upper()
        if sym in wl:
            return {"status": "already_exists", "symbol": sym}
        wl.append(sym)
        save_json(WATCHLIST_FILE, wl)
        return {"status": "added", "symbol": sym, "watchlist": wl}

    if sub in ("rm", "remove", "del", "delete"):
        if len(args) < 2:
            return {"status": "error", "message": "Usage: watchlist rm <SYMBOL>"}
        sym = args[1].upper()
        if sym not in wl:
            return {"status": "error", "message": f"{sym} not in watchlist."}
        wl.remove(sym)
        save_json(WATCHLIST_FILE, wl)
        return {"status": "removed", "symbol": sym, "watchlist": wl}

    if sub == "quotes":
        err = require_yfinance()
        if err:
            return err
        quotes = []
        for sym in wl:
            q = handle_quote([sym])
            quotes.append(q)
        return {"status": "ok", "count": len(quotes), "quotes": quotes}

    return {"status": "error", "message": f"Unknown sub-command '{sub}'. Use: add | rm | quotes | list"}


def handle_alert(args: list[str]) -> dict:
    """
    alert set   <SYM> above|below <PRICE>  – set a price alert
    alert list                              – list all alerts
    alert check                             – check all alerts against live prices
    alert rm    <SYM>                       – remove alert for a symbol
    """
    alerts = load_json(ALERTS_FILE, [])

    if not args:
        return {"status": "error", "message": "Usage: alert set|list|check|rm ..."}

    sub = args[0].lower()

    if sub == "list":
        return {"status": "ok", "count": len(alerts), "alerts": alerts}

    if sub == "set":
        # alert set RELIANCE.NS above 2500
        if len(args) < 4 or args[2].lower() not in ("above", "below"):
            return {"status": "error", "message": "Usage: alert set <SYM> above|below <PRICE>"}
        sym       = args[1].upper()
        direction = args[2].lower()
        try:
            target = float(args[3])
        except ValueError:
            return {"status": "error", "message": "Price must be a number."}

        # remove existing alert for same symbol
        alerts = [a for a in alerts if a["symbol"] != sym]
        alerts.append({
            "symbol":    sym,
            "direction": direction,
            "target":    target,
            "set_at":    datetime.now().isoformat(timespec="seconds"),
        })
        save_json(ALERTS_FILE, alerts)
        return {"status": "alert_set", "symbol": sym, "direction": direction, "target": target}

    if sub == "rm":
        if len(args) < 2:
            return {"status": "error", "message": "Usage: alert rm <SYM>"}
        sym    = args[1].upper()
        before = len(alerts)
        alerts = [a for a in alerts if a["symbol"] != sym]
        save_json(ALERTS_FILE, alerts)
        return {"status": "removed" if len(alerts) < before else "not_found", "symbol": sym}

    if sub == "check":
        err = require_yfinance()
        if err:
            return err
        results = []
        for alert in alerts:
            q = handle_quote([alert["symbol"]])
            price = q.get("price")
            triggered = False
            if price:
                if alert["direction"] == "above" and price >= alert["target"]:
                    triggered = True
                elif alert["direction"] == "below" and price <= alert["target"]:
                    triggered = True
            results.append({
                **alert,
                "current_price": price,
                "triggered":     triggered,
            })
        return {"status": "ok", "checked": len(results), "results": results}

    return {"status": "error", "message": f"Unknown sub-command '{sub}'."}


def handle_search(args: list[str]) -> dict:
    """
    search <QUERY>
    Search for a ticker symbol by company name keyword.
    """
    err = require_yfinance()
    if err:
        return err

    if not args:
        return {"status": "error", "message": "Usage: search <QUERY>  e.g. search Reliance"}

    query = " ".join(args)
    try:
        results = yf.Search(query, max_results=8)
        quotes  = results.quotes  # list of dicts

        hits = [
            {
                "symbol":   q.get("symbol"),
                "name":     q.get("shortname") or q.get("longname"),
                "exchange": q.get("exchange"),
                "type":     q.get("quoteType"),
            }
            for q in quotes
        ]
        return {"status": "ok", "query": query, "count": len(hits), "results": hits}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def handle_movers(args: list[str]) -> dict:
    """
    movers [nifty50|sensex|crypto]
    Fetch top gainers and losers for a predefined index basket.
    """
    err = require_yfinance()
    if err:
        return err

    BASKETS = {
        "nifty50": [
            "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
            "HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS",
        ],
        "sensex": [
            "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
            "HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","AXISBANK.NS","BAJFINANCE.NS",
        ],
        "crypto": [
            "BTC-USD","ETH-USD","BNB-USD","SOL-USD","XRP-USD",
            "DOGE-USD","ADA-USD","AVAX-USD","MATIC-USD","DOT-USD",
        ],
    }

    basket_key = args[0].lower() if args else "nifty50"
    symbols    = BASKETS.get(basket_key)
    if not symbols:
        return {"status": "error", "message": f"Unknown basket '{basket_key}'. Choose: {list(BASKETS)}"}

    results = []
    for sym in symbols:
        q = handle_quote([sym])
        if q.get("status") == "ok":
            results.append({"symbol": sym, "price": q["price"], "change_pct": q["change_pct"]})

    results.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
    return {
        "status":   "ok",
        "basket":   basket_key,
        "gainers":  results[:3],
        "losers":   list(reversed(results[-3:])),
        "snapshot": results,
    }


# ── Command router ────────────────────────────────────────────────────────────

COMMANDS = {
    "quote":     handle_quote,
    "info":      handle_info,
    "history":   handle_history,
    "compare":   handle_compare,
    "watchlist": handle_watchlist,
    "alert":     handle_alert,
    "search":    handle_search,
    "movers":    handle_movers,
}

USAGE = (
    "quote <SYM> | info <SYM> | history <SYM> [days] | compare <SYM1> <SYM2> [days] | "
    "watchlist [add|rm|quotes] | alert [set|list|check|rm] | search <NAME> | movers [nifty50|sensex|crypto]"
)

async def process_command(se_interface, args):
    if not args:
        se_interface.send_message(json.dumps({
            "status":  "error",
            "message": "No command provided.",
            "usage":   USAGE,
        }))
        return

    cmd = args[0].lower()

    if cmd in COMMANDS:
        result = COMMANDS[cmd](args[1:])
    else:
        result = {
            "status":  "error",
            "message": f"Unknown command '{cmd}'.",
            "usage":   USAGE,
        }

    se_interface.send_message(json.dumps(result, ensure_ascii=False))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="SOUL STOCK TRACKER")
    soul_app.run_repl(main_fn=process_command)