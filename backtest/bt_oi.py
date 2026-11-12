#!/usr/bin/env python3
"""Бэктест: торговля против физлиц по открытому интересу фьючерсов на акции (AlgoPack FUTOI).

Физлица нарастили лонг сильнее обычного → шорт акции; нарастили шорт → лонг.
Снимок ОИ — конец дня (latest), вход — открытие акции на следующий день.
"""
import sys
import datetime as dt
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from moexapi import iss, table  # noqa: E402

YEARS = float(sys.argv[1]) if len(sys.argv) > 1 else 2
START = dt.date.today() - dt.timedelta(days=int(YEARS * 365) + 120)
ASSET2SHARE = {"SBRF": "SBER", "SBPR": "SBERP", "GAZR": "GAZP", "NOTK": "NVTK", "SNGR": "SNGS", "SNGP": "SNGSP",
               "TATP": "TATNP", "TCSI": "T", "FIVE": "X5", "TRNF": "TRNFP", "YNDF": "YDEX", "MAGN": "MAGN"}
LOOK, ZK = 60, 2.0
STOP_ATR, TRAIL_FROM, TRAIL, MAX_DAYS = 1.5, 5, 0.014, 10


def chunks(a, b, days=300):
    while a <= b:
        e = min(b, a + dt.timedelta(days=days))
        yield a, e
        a = e + dt.timedelta(days=1)


def mapping():
    rows = table(iss("engines/futures/markets/forts/securities.json",
                     {"iss.only": "securities", "securities.columns": "SECID,ASSETCODE,LOTVOLUME"}), "securities")
    shares = {r["SECID"] for r in table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
                                            {"iss.only": "securities", "securities.columns": "SECID,SECTYPE"}), "securities")
              if str(r.get("SECTYPE")) in ("1", "2", "D")}
    m = {}
    for r in rows:
        code, asset = r["SECID"][:2], r["ASSETCODE"]
        share = ASSET2SHARE.get(asset, asset)
        if share in shares and len(r["SECID"]) == 4:
            m[code] = (share, r["LOTVOLUME"])
    return m


def futoi(code):
    out = {}
    for a, b in chunks(START, dt.date.today()):
        rows = table(iss(f"analyticalproducts/futoi/securities/{code.lower()}.json",
                         {"from": a.isoformat(), "till": b.isoformat(), "latest": 1}), "futoi")
        for r in rows:
            d = r["tradedate"]
            if dt.date.fromisoformat(d).weekday() >= 5:
                continue
            out.setdefault(d, {})[r["clgroup"]] = r
    return {d: v for d, v in out.items() if "FIZ" in v}


def candles(share):
    out, start = [], 0
    while True:
        rows = table(iss(f"engines/stock/markets/shares/boards/TQBR/securities/{share}/candles.json",
                         {"interval": 24, "from": START.isoformat(), "start": start}), "candles")
        out += rows
        start += len(rows)
        if len(rows) < 500:
            break
    return {str(r["begin"])[:10]: dict(o=r["open"], h=r["high"], l=r["low"], c=r["close"]) for r in out}


def z(series, i, k=LOOK):
    hist = series[max(0, i - k):i]
    if len(hist) < 30:
        return None
    sd = np.std(hist)
    return (series[i] - np.mean(hist)) / sd if sd > 0 else None


SIGNALS = {
    "доля ≥3%": dict(kind="rel", thr=0.03),
    "доля ≥5%": dict(kind="rel", thr=0.05),
    "доля ≥10%": dict(kind="rel", thr=0.10),
    "доля ≥5% + против цены": dict(kind="rel", thr=0.05, against_price=True),
    "доля ≥5% + фильтр рынка": dict(kind="rel", thr=0.05, market=True),
    "доля ≥5% + против цены + рынок": dict(kind="rel", thr=0.05, against_price=True, market=True),
}
EXITS = {
    "A: без тейка, 10 дн.": dict(take=None, max_days=10),
    "F: без тейка, 15 дн.": dict(take=None, max_days=15),
    "E: тейк 8%, 15 дн.": dict(take=0.08, max_days=15),
}
VARIANTS = {f"{sn} | {en}": (sp, ep) for sn, sp in SIGNALS.items() for en, ep in EXITS.items()}


def signals(ds, oi, kind, thr=0.05):
    net = np.array([oi[d]["FIZ"]["pos"] for d in ds], dtype=float)
    gross = np.array([oi[d]["FIZ"]["pos_long"] - oi[d]["FIZ"]["pos_short"] for d in ds], dtype=float)
    nl = np.array([oi[d]["FIZ"]["pos_long_num"] for d in ds], dtype=float)
    ns = np.array([oi[d]["FIZ"]["pos_short_num"] for d in ds], dtype=float)
    d1 = np.diff(net, prepend=net[0])
    d3 = net - np.concatenate([[net[0]] * 3, net[:-3]])
    dl, dsh = np.diff(nl, prepend=nl[0]), np.diff(ns, prepend=ns[0])
    out = {}
    for i in range(1, len(ds)):
        side = None
        if kind == "z1":
            zz = z(d1, i)
            side = None if zz is None else ("sell" if zz >= ZK else "buy" if zz <= -ZK else None)
        elif kind == "z3":
            zz = z(d3, i)
            side = None if zz is None else ("sell" if zz >= ZK else "buy" if zz <= -ZK else None)
        elif kind == "rel":
            r = d1[i] / gross[i - 1] if gross[i - 1] else 0
            side = "sell" if r >= thr else "buy" if r <= -thr else None
        elif kind == "crowd":
            zl, zs = z(dl, i), z(dsh, i)
            if zl is not None and zl >= ZK and (zs is None or zs < ZK):
                side = "sell"
            elif zs is not None and zs >= ZK and (zl is None or zl < ZK):
                side = "buy"
        if side:
            out[ds[i]] = (side, float(d1[i]))
    return out


def trade(px, days, i, side, take=None, max_days=MAX_DAYS):
    """Вход по открытию дня days[i+1]; стоп 1.5 ATR; трейлинг 1.4% с 5-го дня; тейк (доля) и срок — параметры."""
    if i + 1 >= len(days):
        return None
    buy = side == "buy"
    trs = [max(px[days[k]]["h"] - px[days[k]]["l"], abs(px[days[k]]["h"] - px[days[k - 1]]["c"]),
               abs(px[days[k]]["l"] - px[days[k - 1]]["c"])) for k in range(max(1, i - 13), i + 1)]
    atr = float(np.mean(trs))
    e = px[days[i + 1]]["o"]
    stop = e - STOP_ATR * atr if buy else e + STOP_ATR * atr
    res = lambda p: ((p / e - 1) if buy else (1 - p / e)) * 100  # noqa: E731
    best, trailing = e, False
    tk = (e * (1 + take) if buy else e * (1 - take)) if take else None
    for n, k in enumerate(range(i + 1, len(days)), 1):
        c = px[days[k]]
        if (buy and c["l"] <= stop) or (not buy and c["h"] >= stop):
            p = min(stop, c["o"]) if buy else max(stop, c["o"])
            return dict(exit_date=days[k], days=n, exit="трейлинг" if trailing else "стоп", result=res(p))
        if tk and ((buy and c["h"] >= tk) or (not buy and c["l"] <= tk)):
            p = max(tk, c["o"]) if buy else min(tk, c["o"])
            return dict(exit_date=days[k], days=n, exit="тейк", result=res(p))
        if n >= max_days:
            return dict(exit_date=days[k], days=n, exit="истёк", result=res(c["c"]))
        best = max(best, c["c"]) if buy else min(best, c["c"])
        if n >= TRAIL_FROM:
            ns_ = best * (1 - TRAIL) if buy else best * (1 + TRAIL)
            if (buy and ns_ > stop) or (not buy and ns_ < stop):
                stop, trailing = ns_, True
    return None


REG = {}


def main():
    global REG
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bt_run2 import market_regime
    try:
        REG = market_regime()
    except Exception as e:  # noqa
        print("индекс:", e)
    m = mapping()
    print("Фьючерсы на акции:", len(m), sorted(f"{k}→{v[0]}" for k, v in m.items()))
    test_from = (dt.date.today() - dt.timedelta(days=int(YEARS * 365))).isoformat()
    trades = []
    for code, (share, lot) in sorted(m.items()):
        try:
            oi, px = futoi(code), candles(share)
        except Exception as e:  # noqa
            print("пропуск", code, e)
            continue
        ds = sorted(d for d in oi if d in px)
        if len(ds) < 60:
            continue
        pdays = sorted(px)
        pidx = {d: i for i, d in enumerate(pdays)}
        sig_cache = {}
        for vname, (sp, ep) in VARIANTS.items():
            key = (sp["kind"], sp["thr"])
            if key not in sig_cache:
                sig_cache[key] = signals(ds, oi, sp["kind"], sp["thr"])
            busy = ""
            for d, (side, delta) in sorted(sig_cache[key].items()):
                if d < test_from or d <= busy:
                    continue
                i = pidx[d]
                if sp.get("against_price") and i > 0:
                    chg = px[d]["c"] / px[pdays[i - 1]]["c"] - 1
                    if not ((side == "sell" and chg < 0) or (side == "buy" and chg > 0)):
                        continue
                if sp.get("market") and d in REG:
                    if (side == "buy" and not REG[d]) or (side == "sell" and REG[d]):
                        continue
                t = trade(px, pdays, i, side, ep["take"], ep["max_days"])
                if not t:
                    continue
                trades.append(dict(variant=vname, ticker=share, code=code, side=side, date=d,
                                   delta=delta, delta_rub=delta * lot * px[d]["c"], **t))
                busy = t["exit_date"]
    ndays = YEARS * 250
    print(f"\nПериод: {test_from} … {dt.date.today()}\n")
    print("| Вариант | Сторона | Сделок | В месяц | Прибыльных | Средний | Медиана | Профит-фактор | Ср. дней | Тейк/стоп/трейл/срок |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for v in VARIANTS:
        for sd in ("buy", "sell", "all"):
            ts = [t for t in trades if t["variant"] == v and (sd == "all" or t["side"] == sd)]
            if not ts:
                continue
            r = np.array([t["result"] for t in ts])
            pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else float("inf")
            print(f"| {v} | {sd} | {len(ts)} | {len(ts) / ndays * 21:.1f} | {np.mean(r > 0) * 100:.0f}% | {r.mean():+.2f}% | "
                  f"{np.median(r):+.2f}% | {pf:.2f} | {np.mean([t['days'] for t in ts]):.1f} | "
                  f"{sum(t['exit'] == 'тейк' for t in ts)}/{sum(t['exit'] == 'стоп' for t in ts)}/{sum(t['exit'] == 'трейлинг' for t in ts)}/{sum(t['exit'] == 'истёк' for t in ts)} |")
    print()
    for v in VARIANTS:
        y = defaultdict(list)
        for t in trades:
            if t["variant"] == v:
                y[t["date"][:4] + ("-1" if t["date"][5:7] <= "06" else "-2")].append(t["result"])
        print(v, "| полугодия (сделок, средний %):", {k: (len(x), round(float(np.mean(x)), 2)) for k, x in sorted(y.items())})


if __name__ == "__main__":
    main()
