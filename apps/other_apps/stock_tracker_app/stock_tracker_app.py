import json
import sys
import os
from datetime import datetime
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

try:
    import yfinance as yf
except ImportError:
    yf = None

USAGE = (
    "quote <SYM> | info <SYM> | history <SYM> [days] | compare <SYM1> <SYM2> [days] | "
    "watchlist [add|rm|quotes] | alert [set|list|check|rm] | search <NAME> | "
    "movers [nifty50|sensex|crypto]"
)

BASKETS = {
    "nifty50": [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    ],
    "sensex": [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "AXISBANK.NS", "BAJFINANCE.NS",
    ],
    "crypto": [
        "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
        "DOGE-USD", "ADA-USD", "AVAX-USD", "MATIC-USD", "DOT-USD",
    ],
}


class StockTrackerApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="SOUL STOCK TRACKER")

        script_directory   = Path(__file__).parent
        self._watchlist_file = script_directory / "watchlist.json"
        self._alerts_file    = script_directory / "price_alerts.json"

        self._commands = {
            "quote":     self._handle_quote,
            "info":      self._handle_info,
            "history":   self._handle_history,
            "compare":   self._handle_compare,
            "watchlist": self._handle_watchlist,
            "alert":     self._handle_alert,
            "search":    self._handle_search,
            "movers":    self._handle_movers,
        }

    # ------------------------------------------------------------------ storage
    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return default

    def _save_json(self, path: Path, data):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------ utils
    def _require_yfinance(self):
        if yf is None:
            return {"status": "error", "message": "yfinance not installed. Run: pip install yfinance"}
        return None

    @staticmethod
    def _fmt(val, decimals=2):
        try:
            return round(float(val), decimals)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fmt_large(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return None
        for unit, threshold in [("B", 1e9), ("M", 1e6), ("K", 1e3)]:
            if abs(v) >= threshold:
                return f"{v / threshold:.2f}{unit}"
        return str(round(v, 2))

    # ------------------------------------------------------------------ handlers
    def _handle_quote(self, args: list) -> dict:
        err = self._require_yfinance()
        if err:
            return err
        if not args:
            return {"status": "error", "message": "Usage: quote <SYMBOL>"}
        symbol = args[0].upper()
        try:
            info       = yf.Ticker(symbol).fast_info
            price      = self._fmt(info.last_price)
            prev_close = self._fmt(info.previous_close)
            change     = self._fmt(price - prev_close) if price and prev_close else None
            change_pct = self._fmt((change / prev_close) * 100) if change and prev_close else None
            return {
                "status": "ok", "symbol": symbol,
                "price": price, "prev_close": prev_close,
                "change": change, "change_pct": change_pct,
                "day_high": self._fmt(info.day_high), "day_low": self._fmt(info.day_low),
                "volume": self._fmt_large(info.three_month_average_volume),
                "52w_high": self._fmt(info.year_high), "52w_low": self._fmt(info.year_low),
                "market_cap": self._fmt_large(info.market_cap),
                "currency": info.currency,
                "as_of": datetime.now().isoformat(timespec="seconds"),
            }
        except Exception as e:
            return {"status": "error", "symbol": symbol, "message": str(e)}

    def _handle_info(self, args: list) -> dict:
        err = self._require_yfinance()
        if err:
            return err
        if not args:
            return {"status": "error", "message": "Usage: info <SYMBOL>"}
        symbol = args[0].upper()
        try:
            info = yf.Ticker(symbol).info
            return {
                "status": "ok", "symbol": symbol,
                "name": info.get("longName"), "sector": info.get("sector"),
                "industry": info.get("industry"), "country": info.get("country"),
                "exchange": info.get("exchange"),
                "pe_ratio": self._fmt(info.get("trailingPE")),
                "forward_pe": self._fmt(info.get("forwardPE")),
                "eps": self._fmt(info.get("trailingEps")),
                "dividend_yield": self._fmt(info.get("dividendYield", 0) * 100),
                "beta": self._fmt(info.get("beta")),
                "debt_to_equity": self._fmt(info.get("debtToEquity")),
                "roe": self._fmt(info.get("returnOnEquity", 0) * 100),
                "revenue": self._fmt_large(info.get("totalRevenue")),
                "net_income": self._fmt_large(info.get("netIncomeToCommon")),
                "description": (info.get("longBusinessSummary") or "")[:300] + "…",
            }
        except Exception as e:
            return {"status": "error", "symbol": symbol, "message": str(e)}

    def _handle_history(self, args: list) -> dict:
        err = self._require_yfinance()
        if err:
            return err
        if not args:
            return {"status": "error", "message": "Usage: history <SYMBOL> [days]"}
        symbol = args[0].upper()
        days   = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30
        try:
            df = yf.Ticker(symbol).history(period=f"{days}d")
            if df.empty:
                return {"status": "error", "symbol": symbol, "message": "No data returned."}
            rows = [
                {"date": str(idx.date()), "open": self._fmt(row["Open"]),
                 "high": self._fmt(row["High"]), "low": self._fmt(row["Low"]),
                 "close": self._fmt(row["Close"]), "volume": int(row["Volume"])}
                for idx, row in df.iterrows()
            ]
            first, last = rows[0]["close"], rows[-1]["close"]
            period_chg  = self._fmt(((last - first) / first) * 100) if first else None
            return {"status": "ok", "symbol": symbol, "days_requested": days,
                    "rows_returned": len(rows), "period_change_pct": period_chg, "data": rows}
        except Exception as e:
            return {"status": "error", "symbol": symbol, "message": str(e)}

    def _handle_compare(self, args: list) -> dict:
        err = self._require_yfinance()
        if err:
            return err
        if len(args) < 2:
            return {"status": "error", "message": "Usage: compare <SYM1> <SYM2> [days]"}
        sym1 = args[0].upper()
        sym2 = args[1].upper()
        days = int(args[2]) if len(args) > 2 and args[2].isdigit() else 30

        def _fetch(sym):
            df = yf.Ticker(sym).history(period=f"{days}d")
            if df.empty:
                return None
            first, last = float(df["Close"].iloc[0]), float(df["Close"].iloc[-1])
            return {"start_price": self._fmt(first), "end_price": self._fmt(last),
                    "change_pct": self._fmt(((last - first) / first) * 100)}

        try:
            r1, r2 = _fetch(sym1), _fetch(sym2)
            winner = None
            if r1 and r2:
                winner = sym1 if r1["change_pct"] > r2["change_pct"] else sym2
            return {"status": "ok", "days": days, sym1: r1 or "no data",
                    sym2: r2 or "no data", "winner": winner}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _handle_watchlist(self, args: list) -> dict:
        wl = self._load_json(self._watchlist_file, [])
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
            self._save_json(self._watchlist_file, wl)
            return {"status": "added", "symbol": sym, "watchlist": wl}
        if sub in ("rm", "remove", "del", "delete"):
            if len(args) < 2:
                return {"status": "error", "message": "Usage: watchlist rm <SYMBOL>"}
            sym = args[1].upper()
            if sym not in wl:
                return {"status": "error", "message": f"{sym} not in watchlist."}
            wl.remove(sym)
            self._save_json(self._watchlist_file, wl)
            return {"status": "removed", "symbol": sym, "watchlist": wl}
        if sub == "quotes":
            err = self._require_yfinance()
            if err:
                return err
            return {"status": "ok", "count": len(wl),
                    "quotes": [self._handle_quote([sym]) for sym in wl]}
        return {"status": "error", "message": f"Unknown sub-command '{sub}'. Use: add | rm | quotes | list"}

    def _handle_alert(self, args: list) -> dict:
        alerts = self._load_json(self._alerts_file, [])
        if not args:
            return {"status": "error", "message": "Usage: alert set|list|check|rm ..."}
        sub = args[0].lower()
        if sub == "list":
            return {"status": "ok", "count": len(alerts), "alerts": alerts}
        if sub == "set":
            if len(args) < 4 or args[2].lower() not in ("above", "below"):
                return {"status": "error", "message": "Usage: alert set <SYM> above|below <PRICE>"}
            sym = args[1].upper()
            direction = args[2].lower()
            try:
                target = float(args[3])
            except ValueError:
                return {"status": "error", "message": "Price must be a number."}
            alerts = [a for a in alerts if a["symbol"] != sym]
            alerts.append({"symbol": sym, "direction": direction, "target": target,
                            "set_at": datetime.now().isoformat(timespec="seconds")})
            self._save_json(self._alerts_file, alerts)
            return {"status": "alert_set", "symbol": sym, "direction": direction, "target": target}
        if sub == "rm":
            if len(args) < 2:
                return {"status": "error", "message": "Usage: alert rm <SYM>"}
            sym    = args[1].upper()
            before = len(alerts)
            alerts = [a for a in alerts if a["symbol"] != sym]
            self._save_json(self._alerts_file, alerts)
            return {"status": "removed" if len(alerts) < before else "not_found", "symbol": sym}
        if sub == "check":
            err = self._require_yfinance()
            if err:
                return err
            results = []
            for alert in alerts:
                q = self._handle_quote([alert["symbol"]])
                price     = q.get("price")
                triggered = False
                if price:
                    if alert["direction"] == "above" and price >= alert["target"]:
                        triggered = True
                    elif alert["direction"] == "below" and price <= alert["target"]:
                        triggered = True
                results.append({**alert, "current_price": price, "triggered": triggered})
            return {"status": "ok", "checked": len(results), "results": results}
        return {"status": "error", "message": f"Unknown sub-command '{sub}'."}

    def _handle_search(self, args: list) -> dict:
        err = self._require_yfinance()
        if err:
            return err
        if not args:
            return {"status": "error", "message": "Usage: search <QUERY>"}
        query = " ".join(args)
        try:
            results = yf.Search(query, max_results=8)
            hits = [
                {"symbol": q.get("symbol"), "name": q.get("shortname") or q.get("longname"),
                 "exchange": q.get("exchange"), "type": q.get("quoteType")}
                for q in results.quotes
            ]
            return {"status": "ok", "query": query, "count": len(hits), "results": hits}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _handle_movers(self, args: list) -> dict:
        err = self._require_yfinance()
        if err:
            return err
        basket_key = args[0].lower() if args else "nifty50"
        symbols    = BASKETS.get(basket_key)
        if not symbols:
            return {"status": "error", "message": f"Unknown basket '{basket_key}'. Choose: {list(BASKETS)}"}
        results = []
        for sym in symbols:
            q = self._handle_quote([sym])
            if q.get("status") == "ok":
                results.append({"symbol": sym, "price": q["price"], "change_pct": q["change_pct"]})
        results.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        return {"status": "ok", "basket": basket_key,
                "gainers": results[:3], "losers": list(reversed(results[-3:])),
                "snapshot": results}

    # ------------------------------------------------------------------ main entry
    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({"status": "error",
                                                   "message": "No command provided.",
                                                   "usage": USAGE}))
            return

        cmd = args[0].lower()
        if cmd in self._commands:
            result = self._commands[cmd](args[1:])
        else:
            result = {"status": "error", "message": f"Unknown command '{cmd}'.", "usage": USAGE}

        se_interface.send_message(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    app = StockTrackerApp()
    app.run_repl()