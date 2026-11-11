"""
Журнал сигналов: фиксирует сигналы из топа скана и каждый день проверяет,
что сработало первым — стоп или цель. Сигнал живёт до MAX_DAYS торговых дней,
потом закрывается по последней цене («истёк»).

Вход — цена закрытия дня сигнала. Проверка идёт по свечам ПОСЛЕ дня сигнала.
Если в одну свечу задеты и стоп, и цель — считаем стоп (консервативно).
Файл: docs/data/journal.json
"""
import json
import datetime as dt
from pathlib import Path

MAX_DAYS = 20
PATH = Path(__file__).parent / "docs" / "data" / "journal.json"
TQBR = "engines/stock/markets/shares/boards/TQBR/securities/{}/candles.json"


def load():
    if PATH.exists():
        return json.loads(PATH.read_text(encoding="utf-8"))
    return {"signals": []}


def pnl(side, entry, price):
    return round(((price / entry - 1) if side == "buy" else (1 - price / entry)) * 100, 2)


def check(sig, bars):
    after = [b for b in bars if b["date"] > sig["opened"]]
    for i, b in enumerate(after, 1):
        if sig["side"] == "buy":
            hit_stop, hit_tgt = b["l"] <= sig["stop"], b["h"] >= sig["target"]
        else:
            hit_stop, hit_tgt = b["h"] >= sig["stop"], b["l"] <= sig["target"]
        if hit_stop or hit_tgt:
            px = sig["stop"] if hit_stop else sig["target"]
            sig.update(status="стоп" if hit_stop else "цель", closed=b["date"], close_price=px,
                       result_pct=pnl(sig["side"], sig["entry"], px), days=i)
            return
        if i >= MAX_DAYS:
            sig.update(status="истёк", closed=b["date"], close_price=b["c"],
                       result_pct=pnl(sig["side"], sig["entry"], b["c"]), days=i)
            return
    if after or bars:
        last = bars[-1]
        sig.update(last_price=last["c"], last_date=last["date"],
                   current_pct=pnl(sig["side"], sig["entry"], last["c"]), days=len(after))


def stats(signals):
    closed = [s for s in signals if s["status"] != "открыт"]
    out = {"total": len(signals), "open": len(signals) - len(closed), "closed": len(closed)}
    if closed:
        wins = [s for s in closed if s["result_pct"] > 0]
        out.update(win_rate=round(len(wins) / len(closed) * 100, 1),
                   avg_result=round(sum(s["result_pct"] for s in closed) / len(closed), 2),
                   sum_result=round(sum(s["result_pct"] for s in closed), 2),
                   targets=sum(s["status"] == "цель" for s in closed),
                   stops=sum(s["status"] == "стоп" for s in closed),
                   expired=sum(s["status"] == "истёк" for s in closed))
    for side in ("buy", "sell"):
        cs = [s for s in closed if s["side"] == side]
        if cs:
            out[f"win_rate_{side}"] = round(sum(s["result_pct"] > 0 for s in cs) / len(cs) * 100, 1)
    return out


def update(report, bars_by_ticker, loader):
    j = load()
    sigs = j["signals"]
    # 1) проверяем открытые
    for s in sigs:
        if s["status"] != "открыт":
            continue
        bars = bars_by_ticker.get(s["ticker"])
        if bars is None:
            try:
                bars = loader(TQBR.format(s["ticker"]))
            except Exception:  # noqa
                continue
        check(s, bars)
    # 2) добавляем новые из топа (если по бумаге в ту же сторону уже нет открытого)
    open_tickers = {s["ticker"] for s in sigs if s["status"] == "открыт"}
    for r in report["results"]:
        # по бумаге уже есть открытый сигнал (в любую сторону) — новый не открываем
        if not r.get("top") or r["ticker"] in open_tickers:
            continue
        open_tickers.add(r["ticker"])
        sigs.append({
            "id": f"{r['date']}-{r['ticker']}-{r['side']}",
            "ticker": r["ticker"], "name": r["name"], "side": r["side"],
            "opened": r["date"], "entry": r["close"], "stop": r["stop"], "target": r["target"],
            "stop_pct": r.get("stop_pct"), "target_pct": r.get("target_pct"),
            "rating": r["rating"], "comment": r.get("comment", ""), "signals": r["signals"],
            "status": "открыт", "current_pct": 0.0, "last_price": r["close"], "last_date": r["date"], "days": 0,
        })
    j["signals"] = sigs
    j["stats"] = stats(sigs)
    j["updated_utc"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
