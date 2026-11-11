"""
Журнал сигналов: фиксирует сигналы из топа скана и каждый день проверяет,
что сработало первым — стоп или цель. Сигнал живёт до MAX_DAYS торговых дней,
потом закрывается по последней цене («истёк»).

Вход — цена на момент скана (ночной скан — закрытие дня). Проверка: в день входа — по часовым
свечам ПОСЛЕ времени входа (opened_at, МСК), дальше — по дневным свечам следующих дней.
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


def hit(sig, b):
    if sig["side"] == "buy":
        return b["l"] <= sig["stop"], b["h"] >= sig["target"]
    return b["h"] >= sig["stop"], b["l"] <= sig["target"]


def check(sig, bars, intraday=None):
    # 1) день входа: часовые свечи, начавшиеся после времени входа
    for b in intraday or []:
        if b["begin"] < sig.get("opened_at", sig["opened"] + " 23:59"):
            continue
        hs, ht = hit(sig, b)
        if hs or ht:
            px = sig["stop"] if hs else sig["target"]
            sig.update(status="стоп" if hs else "цель", closed=sig["opened"], closed_at=b["begin"][:16],
                       close_price=px, result_pct=pnl(sig["side"], sig["entry"], px), days=0)
            return
    # 1б) часовые свечи биржа отдаёт с задержкой: если дневная свеча дня входа уже задела уровень,
    #     а до времени входа (часовые свечи до opened_at) цена его не касалась — значит, задела после входа.
    if intraday is not None and sig.get("opened_at", "")[11:16] < "23:59":
        day = next((b for b in bars if b["date"] == sig["opened"]), None)
        if day:
            pre = [b for b in intraday if b["begin"] < sig["opened_at"]]
            pre_h = max([b["h"] for b in pre], default=-1e18)
            pre_l = min([b["l"] for b in pre], default=1e18)
            if sig["side"] == "buy":
                hs = day["l"] <= sig["stop"] and pre_l > sig["stop"]
                ht = day["h"] >= sig["target"] and pre_h < sig["target"]
            else:
                hs = day["h"] >= sig["stop"] and pre_h < sig["stop"]
                ht = day["l"] <= sig["target"] and pre_l > sig["target"]
            if hs or ht:
                px = sig["stop"] if hs else sig["target"]
                sig.update(status="стоп" if hs else "цель", closed=sig["opened"], closed_at=sig["opened"] + " (в течение дня)",
                           close_price=px, result_pct=pnl(sig["side"], sig["entry"], px), days=0)
                return
    # 2) следующие дни: дневные свечи
    after = [b for b in bars if b["date"] > sig["opened"]]
    for i, b in enumerate(after, 1):
        hit_stop, hit_tgt = hit(sig, b)
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


def stats_all(signals):
    out = stats(signals)
    out["by_strategy"] = {k: stats([s for s in signals if s.get("strategy", "ta") == k]) for k in ("ta", "momentum")}
    return out


def opened_at(bar_date):
    """Время входа (МСК). Ночной скан (уже следующие сутки) — вход по закрытию: проверка в тот же день не нужна."""
    now = msk_now()
    if now.strftime("%Y-%m-%d") > bar_date or now.strftime("%H:%M") >= "23:50":
        return bar_date + " 23:59"
    return now.strftime("%Y-%m-%d %H:%M")


def msk_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=3)


def update(report, bars_by_ticker, loader, intraday_loader=None):
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
        intr = None
        if intraday_loader and s.get("opened_at") and s["opened_at"][11:16] < "23:59":
            try:
                intr = intraday_loader(s["ticker"], s["opened"])
            except Exception:  # noqa
                intr = None
        check(s, bars, intr)
    # 2) добавляем новые из топа (если по бумаге в ту же сторону уже нет открытого)
    def _base(t):
        return t[:-1] if t.endswith("P") and len(t) > 4 else t
    open_keys = {(_base(s["ticker"]), s.get("strategy", "ta")) for s in sigs if s["status"] == "открыт"}
    for r in report["results"]:
        # по бумаге уже есть открытый сигнал этой стратегии (в любую сторону) — новый не открываем
        base = r["ticker"][:-1] if r["ticker"].endswith("P") and len(r["ticker"]) > 4 else r["ticker"]
        key = (base, r.get("strategy", "ta"))  # обычка и префы — одна позиция
        if not r.get("top") or key in open_keys:
            continue
        open_keys.add(key)
        sigs.append({
            "id": f"{r['date']}-{r['ticker']}-{r['side']}-{r.get('strategy', 'ta')}",
            "strategy": r.get("strategy", "ta"),
            "ticker": r["ticker"], "name": r["name"], "side": r["side"],
            "opened": r["date"], "opened_at": opened_at(r["date"]), "entry": r["close"], "stop": r["stop"], "target": r["target"],
            "stop_pct": r.get("stop_pct"), "target_pct": r.get("target_pct"),
            "rating": r["rating"], "comment": r.get("comment", ""), "signals": r["signals"],
            "status": "открыт", "current_pct": 0.0, "last_price": r["close"], "last_date": r["date"], "days": 0,
        })
    j["signals"] = sigs
    j["stats"] = stats_all(sigs)
    j["updated_utc"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
