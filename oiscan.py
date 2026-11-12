#!/usr/bin/env python3
"""
Открытый интерес физлиц по фьючерсам на акции (AlgoPack FUTOI) — сигналы «против толпы».

Сигнал (по итогам дня): чистая позиция физлиц изменилась за день на ≥10% от их совокупной позиции
(лонг + шорт на начало дня). Нарастили лонг → шорт акции; нарастили шорт → лонг.
Вход — открытие акции на следующий торговый день. Стоп 1.5 ATR(14), трейлинг 1.4% от лучшего закрытия
с 5-го дня, максимум 10 торговых дней. (Бэктест 11.2024–11.2026: ~27 сделок/мес, профит-фактор 1.43.)

  python oiscan.py intraday — таблица ОИ на текущий момент (кандидаты дня)
  python oiscan.py nightly  — сигналы закрытого дня, входы, ведение сделок

Файлы: docs/data/oi.json, docs/data/journal_oi.json
"""
import json
import sys
import datetime as dt
from pathlib import Path

import manual
from moexapi import TOKEN, iss, table

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data" / "oi.json"
JOURNAL = ROOT / "docs" / "data" / "journal_oi.json"

O = {"threshold": 0.10, "atr_k": 1.5, "atr_n": 14, "trail_from": 5, "trail": 0.014, "max_days": 10, "cooldown": 7}
ASSET2SHARE = {"SBRF": "SBER", "SBPR": "SBERP", "GAZR": "GAZP", "NOTK": "NVTK", "SNGR": "SNGS", "SNGP": "SNGSP",
               "TATP": "TATNP", "TCSI": "T", "FIVE": "X5", "TRNF": "TRNFP", "YNDF": "YDEX"}


def msk_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=3)


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return default


def save_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def mapping():
    """Код фьючерса в FUTOI (две буквы) → (акция, акций в контракте)."""
    rows = table(iss("engines/futures/markets/forts/securities.json",
                     {"iss.only": "securities", "securities.columns": "SECID,ASSETCODE,LOTVOLUME"}), "securities")
    sh = table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
                   {"iss.only": "securities,marketdata", "securities.columns": "SECID,SHORTNAME,SECTYPE",
                    "marketdata.columns": "SECID,LAST,OPEN,HIGH,LOW,LASTTOPREVPRICE"}), "securities")
    md = {r["SECID"]: r for r in table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
          {"iss.only": "marketdata", "marketdata.columns": "SECID,LAST,OPEN,HIGH,LOW,LASTTOPREVPRICE"}), "marketdata")}
    shares = {r["SECID"]: r["SHORTNAME"] for r in sh if str(r.get("SECTYPE")) in ("1", "2", "D")}
    excl = set()
    f = ROOT / "exclude.txt"
    if f.exists():
        excl = {ln.split("#")[0].strip().upper() for ln in f.read_text(encoding="utf-8").splitlines() if ln.split("#")[0].strip()}
    m = {}
    for r in rows:
        if len(r["SECID"]) != 4:
            continue
        share = ASSET2SHARE.get(r["ASSETCODE"], r["ASSETCODE"])
        if share in shares and share not in excl:
            m[r["SECID"][:2]] = dict(share=share, name=shares[share], lot=r["LOTVOLUME"])
    return m, md


def trading_dates(n=10):
    till = msk_now().date()
    rows = table(iss("engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json",
                     {"interval": 24, "from": (till - dt.timedelta(days=n * 2 + 10)).isoformat(), "till": till.isoformat()}), "candles")
    return sorted({str(r["begin"])[:10] for r in rows if dt.date.fromisoformat(str(r["begin"])[:10]).weekday() < 5})


def snapshot(date=None):
    """{код: {'FIZ': {...}, 'YUR': {...}}} — последний снимок ОИ за дату (или текущий)."""
    p = {"latest": 1}
    if date:
        p["date"] = date
    out = {}
    for r in table(iss("analyticalproducts/futoi/securities.json", p), "futoi"):
        out.setdefault(r["ticker"], {})[r["clgroup"]] = r
    return out


def daily(share, days=40):
    frm = (msk_now().date() - dt.timedelta(days=days * 2)).isoformat()
    rows = table(iss(f"engines/stock/markets/shares/boards/TQBR/securities/{share}/candles.json",
                     {"interval": 24, "from": frm}), "candles")
    return [dict(d=str(r["begin"])[:10], o=r["open"], h=r["high"], l=r["low"], c=r["close"]) for r in rows]


def atr(c, n):
    trs = [max(c[k]["h"] - c[k]["l"], abs(c[k]["h"] - c[k - 1]["c"]), abs(c[k]["l"] - c[k - 1]["c"])) for k in range(1, len(c))]
    trs = trs[-n:]
    return sum(trs) / len(trs) if trs else None


def build_table(m, md, now_snap, prev_snap, week_snap, now_label):
    rows = []
    for code, info in m.items():
        cur, prv = now_snap.get(code, {}).get("FIZ"), prev_snap.get(code, {}).get("FIZ")
        if not cur or not prv:
            continue
        wk = week_snap.get(code, {}).get("FIZ")
        price = (md.get(info["share"]) or {}).get("LAST")
        mult = info["lot"] * price if price else None
        gross_prev = prv["pos_long"] - prv["pos_short"]
        d_net = cur["pos"] - prv["pos"]
        rel = d_net / gross_prev if gross_prev else 0
        rub = lambda x: round(x * mult / 1e6, 1) if mult is not None and x is not None else None  # noqa: E731
        rows.append({
            "code": code, "ticker": info["share"], "name": info["name"], "lot": info["lot"], "price": price,
            "change_pct": (md.get(info["share"]) or {}).get("LASTTOPREVPRICE"),
            "long": cur["pos_long"], "short": -cur["pos_short"], "net": cur["pos"],
            "d_long": cur["pos_long"] - prv["pos_long"], "d_short": -(cur["pos_short"] - prv["pos_short"]),
            "d_net": d_net, "rel_pct": round(rel * 100, 1),
            "d_net_week": cur["pos"] - wk["pos"] if wk else None,
            "net_mln": rub(cur["pos"]), "d_net_mln": rub(d_net), "d_net_week_mln": rub(cur["pos"] - wk["pos"]) if wk else None,
            "long_num": cur["pos_long_num"], "short_num": cur["pos_short_num"],
            "d_long_num": cur["pos_long_num"] - prv["pos_long_num"], "d_short_num": cur["pos_short_num"] - prv["pos_short_num"],
            "side": ("sell" if rel >= O["threshold"] else "buy" if rel <= -O["threshold"] else None),
            "time": str(cur["tradetime"])[:5], "date": cur["tradedate"],
        })
    rows.sort(key=lambda r: abs(r["rel_pct"]), reverse=True)
    return rows


def pnl(side, e, p):
    return round(((p / e - 1) if side == "buy" else (1 - p / e)) * 100, 2)


def stats(sigs):
    closed = [s for s in sigs if s["status"] not in ("открыт", "ждёт входа", "отменён")]
    out = {"total": len(sigs), "open": sum(s["status"] == "открыт" for s in sigs),
           "pending": sum(s["status"] == "ждёт входа" for s in sigs), "closed": len(closed)}
    if closed:
        out.update(win_rate=round(sum(s["result_pct"] > 0 for s in closed) / len(closed) * 100, 1),
                   avg_result=round(sum(s["result_pct"] for s in closed) / len(closed), 2))
        for st in ("стоп", "трейлинг", "истёк"):
            out[st] = sum(s["status"] == st for s in closed)
    return out


def manage(s, candles, entry_only=False, last=None):
    """Вход по открытию следующего дня и ведение сделки по дневным свечам.
    entry_only — днём: только записать вход по открытию и текущий результат (дневная свеча ещё не закрыта)."""
    if s["status"] == "ждёт входа":
        nxt = [c for c in candles if c["d"] > s["signal_date"]]
        if not nxt:
            return
        c0 = nxt[0]
        hist = [c for c in candles if c["d"] <= s["signal_date"]]
        a = atr(hist, O["atr_n"]) or c0["o"] * 0.03
        s.update(status="открыт", opened=c0["d"], entry=c0["o"], atr=round(a, 6),
                 stop=round(c0["o"] - O["atr_k"] * a if s["side"] == "buy" else c0["o"] + O["atr_k"] * a, 6), days=0)
        s["stop_pct"] = round(-abs(s["stop"] / s["entry"] - 1) * 100, 1)
        s["best"] = c0["o"]
    if entry_only:
        if s["status"] == "открыт" and last:
            s["last_price"], s["current_pct"] = last, pnl(s["side"], s["entry"], last)
        return
    if s["status"] != "открыт":
        return
    buy = s["side"] == "buy"
    for c in [c for c in candles if c["d"] >= s["opened"] and c["d"] > s.get("processed", "")]:
        if c["d"] > s["opened"]:
            s["days"] = s.get("days", 0) + 1
        if (buy and c["l"] <= s["stop"]) or (not buy and c["h"] >= s["stop"]):
            p = min(s["stop"], c["o"]) if buy else max(s["stop"], c["o"])
            s.update(status="трейлинг" if s.get("trailing") else "стоп", closed=c["d"], close_price=p,
                     result_pct=pnl(s["side"], s["entry"], p), processed=c["d"])
            return
        s["processed"] = c["d"]
        s["last_price"], s["last_date"], s["current_pct"] = c["c"], c["d"], pnl(s["side"], s["entry"], c["c"])
        if s["days"] >= O["max_days"]:
            s.update(status="истёк", closed=c["d"], close_price=c["c"], result_pct=pnl(s["side"], s["entry"], c["c"]))
            return
        s["best"] = max(s["best"], c["c"]) if buy else min(s["best"], c["c"])
        if s["days"] >= O["trail_from"]:
            ns = s["best"] * (1 - O["trail"]) if buy else s["best"] * (1 + O["trail"])
            if (buy and ns > s["stop"]) or (not buy and ns < s["stop"]):
                s["stop"], s["trailing"] = round(ns, 6), True


def run(mode):
    now = msk_now()
    m, md = mapping()
    dates = trading_dates()
    today = now.strftime("%Y-%m-%d")
    closed_days = [d for d in dates if d < today or (d == today and now.strftime("%H:%M") >= "23:55")]
    if mode == "intraday" and dates and dates[-1] == today:
        cur, prev = snapshot(), snapshot(closed_days[-1])
        week = snapshot(closed_days[-5]) if len(closed_days) >= 5 else {}
        label = "сейчас"
    else:
        d = closed_days[-1]
        cur, prev = snapshot(d), snapshot(closed_days[-2])
        week = snapshot(closed_days[-6]) if len(closed_days) >= 6 else {}
        label = "итог дня"
    rows = build_table(m, md, cur, prev, week, label)
    j = load_json(JOURNAL, {"signals": []})
    sigs = j["signals"]
    manual.apply(sigs, "oi")
    if mode == "intraday":
        for s in sigs:
            if s["status"] in ("ждёт входа", "открыт"):
                try:
                    manage(s, daily(s["ticker"]), entry_only=True, last=(md.get(s["ticker"]) or {}).get("LAST"))
                except Exception as e:  # noqa
                    print("вход", s["ticker"], e, file=sys.stderr)
    if mode == "nightly":
        sig_date = closed_days[-1]
        cache = {}
        for s in sigs:
            if s["status"] in ("ждёт входа", "открыт"):
                cache.setdefault(s["ticker"], daily(s["ticker"]))
                manage(s, cache[s["ticker"]])
        active = {s["ticker"] for s in sigs if s["status"] in ("ждёт входа", "открыт")}
        for r in rows:
            if not r["side"] or r["ticker"] in active:
                continue
            if any(s["ticker"] == r["ticker"] and s["side"] == r["side"] and s["status"] == "стоп" and s.get("closed") and
                   (dt.date.fromisoformat(sig_date) - dt.date.fromisoformat(s["closed"])).days < O["cooldown"] for s in sigs):
                continue
            if any(s["ticker"] == r["ticker"] and s["signal_date"] == sig_date for s in sigs):
                continue
            crowd = "лонг" if r["side"] == "sell" else "шорт"
            try:
                cc = daily(r["ticker"])
                hist = [c for c in cc if c["d"] <= sig_date]
                ref, a = hist[-1]["c"], atr(hist, O["atr_n"])
            except Exception:  # noqa
                ref, a = r["price"], None
            sigs.append({
                "ref_price": ref, "atr": a, "net": r["net"], "long": r["long"], "short": r["short"],
                "id": f"{sig_date}-{r['ticker']}-{r['side']}-oi", "strategy": "oi", "ticker": r["ticker"], "name": r["name"],
                "code": r["code"], "side": r["side"], "signal_date": sig_date, "status": "ждёт входа",
                "rel_pct": r["rel_pct"], "d_net": r["d_net"], "d_net_mln": r["d_net_mln"],
                "comment": f"Физлица нарастили {crowd}: {r['d_net']:+,} контр. ({r['rel_pct']:+.1f}% позиции)".replace(",", " "),
            })
            active.add(r["ticker"])
        j["updated_night"] = now.strftime("%Y-%m-%d %H:%M")
    j["signals"], j["stats"], j["params"] = sigs, stats(sigs), O
    save_json(JOURNAL, j)
    save_json(OUT, {"updated": now.strftime("%Y-%m-%d %H:%M"), "mode": label, "params": O,
                    "date": rows[0]["date"] if rows else None, "time": rows[0]["time"] if rows else None, "rows": rows})
    print(f"ОИ {label}: фьючерсов {len(rows)}, кандидатов {sum(1 for r in rows if r['side'])}; журнал {j['stats']}")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Нужен ключ AlgoPack: секрет MOEX_TOKEN")
    run(sys.argv[1] if len(sys.argv) > 1 else "intraday")
