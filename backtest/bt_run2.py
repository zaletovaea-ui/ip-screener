#!/usr/bin/env python3
"""Бэктест 2: сигнал по итогам дня, вход на следующий день (как в схеме «сигнал → подтверждение → вход»).

python backtest/bt_run2.py bt_part_*.npz
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_run import load, day_ohlc, NS, NORM_DAYS, MIN_DAYS  # noqa: E402

TRAIL_FROM, TRAIL, MAX_DAYS = 5, 0.014, 10
AGAINST_RATIO, AGAINST_SHARE = 2.0, 0.6

BASE = dict(ratio=3, share=0.53, chg=(1.5, 4.0), pos=0.6, vwap=True, value=50e6,
            entry="open", atr_k=1.5, max_stop=0.10, market=False)
VARIANTS = {
    "A. Сигнал по дню (×3, рост 1,5–4%), вход на след. день по открытию, стоп 1,5 ATR": dict(BASE),
    "B. = A + фильтр рынка (покупки при индексе выше EMA200, продажи — ниже)": dict(BASE, market=True),
    "C. = A, но вход на откате к VWAP дня сигнала в течение 3 дней": dict(BASE, entry="vwap"),
    "D. = B + вход на откате к VWAP": dict(BASE, market=True, entry="vwap"),
}


def market_regime():
    """{дата: True, если индекс Мосбиржи выше EMA200} — по публичным дневным свечам ISS."""
    import requests
    out, start = [], 0
    while True:
        j = requests.get("https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json",
                         params={"iss.meta": "off", "interval": 24, "from": "2025-01-01", "start": start}, timeout=30).json()
        rows = j["candles"]["data"]
        cols = j["candles"]["columns"]
        out += [dict(zip(cols, r)) for r in rows]
        start += len(rows)
        if len(rows) < 500:
            break
    closes = [r["close"] for r in out]
    k, e, reg = 2 / 201, None, {}
    for i, r in enumerate(out):
        if i < 199:
            continue
        e = sum(closes[:200]) / 200 if e is None else closes[i] * k + e * (1 - k)
        reg[str(r["begin"])[:10]] = closes[i] > e
    return reg


def atr(ohlc, ds, i, n=14):
    trs = []
    for j in range(max(1, i - n + 1), i + 1):
        o, p = ohlc[ds[j]], ohlc[ds[j - 1]]
        if o and p:
            trs.append(max(o["h"] - o["l"], abs(o["h"] - p["c"]), abs(o["l"] - p["c"])))
    return float(np.mean(trs)) if trs else None


def run_from(t, ds, j, s, entry, stop, side, days, ohlc, sig_date):
    """Сделка с входом в день ds[j] в слоте s."""
    buy = side == "buy"
    res = lambda px: ((px / entry - 1) if buy else (1 - px / entry)) * 100  # noqa: E731
    a = days[ds[j]]
    base = dict(ticker=t, side=side, signal_date=sig_date, entry_date=ds[j])
    for k in range(s + 1, NS):
        if np.isnan(a[5, k]):
            continue
        if (buy and a[6, k] <= stop) or (not buy and a[5, k] >= stop):
            return dict(base, exit_date=ds[j], days=0, exit="стоп", result=res(stop))
    best, trailing, n = ohlc[ds[j]]["c"], False, 0
    for q in range(j + 1, len(ds)):
        d, o = ds[q], ohlc[ds[q]]
        if not o:
            continue
        n += 1
        if (buy and o["l"] <= stop) or (not buy and o["h"] >= stop):
            px = min(stop, o["o"]) if buy else max(stop, o["o"])
            return dict(base, exit_date=d, days=n, exit="трейлинг" if trailing else "стоп", result=res(px))
        prev = ds[max(0, q - NORM_DAYS):q]
        dn = np.median([ohlc[x]["val"] for x in prev if ohlc[x]]) if prev else 0
        tot = o["vb"] + o["vs"]
        if dn and tot and o["val"] >= AGAINST_RATIO * dn:
            ag = (o["vs"] if buy else o["vb"]) / tot
            if ag >= AGAINST_SHARE and ((o["c"] < o["o"]) if buy else (o["c"] > o["o"])):
                return dict(base, exit_date=d, days=n, exit="объём против", result=res(o["c"]))
        if n >= MAX_DAYS:
            return dict(base, exit_date=d, days=n, exit="истёк", result=res(o["c"]))
        best = max(best, o["c"]) if buy else min(best, o["c"])
        if n >= TRAIL_FROM:
            ns_ = best * (1 - TRAIL) if buy else best * (1 + TRAIL)
            if (buy and ns_ > stop) or (not buy and ns_ < stop):
                stop, trailing = ns_, True
    return dict(base, exit_date="9999", days=n, exit="открыта", result=res(ohlc[ds[-1]]["c"]))


def run():
    data = load(sys.argv[1:])
    alldates = sorted({d for t in data for d in data[t]})
    test_dates = set(alldates[NORM_DAYS:])
    ntest = len(test_dates)
    try:
        reg = market_regime()
    except Exception as e:  # noqa
        print("Индекс не загрузился:", e)
        reg = {}
    trades = []
    for vname, P in VARIANTS.items():
        for t, days in data.items():
            ds = sorted(days)
            ohlc = {d: day_ohlc(days[d]) for d in ds}
            busy = ""
            for i, d in enumerate(ds[:-1]):
                if d not in test_dates or i < MIN_DAYS or d <= busy or not ohlc[d] or not ohlc[ds[i - 1]]:
                    continue
                o, pc = ohlc[d], ohlc[ds[i - 1]]["c"]
                prev = ds[max(0, i - NORM_DAYS):i]
                dn = np.median([ohlc[x]["val"] for x in prev if ohlc[x]])
                if not dn or o["val"] < P["value"] or o["val"] / dn < P["ratio"]:
                    continue
                a = days[d]
                tot = o["vb"] + o["vs"]
                share = o["vb"] / tot if tot else 0.5
                chg = (o["c"] / pc - 1) * 100
                pos = (o["c"] - o["l"]) / (o["h"] - o["l"]) if o["h"] > o["l"] else 0.5
                vwap = a[0].sum() / a[3].sum() if a[3].sum() else o["c"]
                side = None
                for sd, sg in (("buy", 1), ("sell", -1)):
                    ok = (share >= P["share"]) if sg > 0 else (share <= 1 - P["share"])
                    ok = ok and P["chg"][0] <= sg * chg <= P["chg"][1]
                    ok = ok and ((pos >= P["pos"]) if sg > 0 else (pos <= 1 - P["pos"]))
                    ok = ok and (not P["vwap"] or ((o["c"] > vwap) if sg > 0 else (o["c"] < vwap)))
                    if ok and P["market"] and d in reg:
                        ok = reg[d] if sg > 0 else not reg[d]
                    if ok:
                        side = sd
                        break
                if not side:
                    continue
                buy = side == "buy"
                at = atr(ohlc, ds, i)
                if not at:
                    continue
                # вход
                entry = None
                for j in range(i + 1, min(i + (4 if P["entry"] == "vwap" else 2), len(ds))):
                    b = days[ds[j]]
                    for s in range(NS):
                        if np.isnan(b[4, s]):
                            continue
                        if P["entry"] == "open":
                            entry, ej, es = float(b[4, s]), j, s
                        elif (buy and b[6, s] <= vwap) or (not buy and b[5, s] >= vwap):
                            entry, ej, es = float(vwap), j, s
                        if entry:
                            break
                    if entry:
                        break
                if not entry:
                    continue
                dist = min(P["atr_k"] * at, P["max_stop"] * entry)
                stop = entry - dist if buy else entry + dist
                tr = run_from(t, ds, ej, es, entry, stop, side, days, ohlc, d)
                tr.update(variant=vname, ratio=round(o["val"] / dn, 1), share=round(share * 100), chg=round(chg, 2),
                          stop_pct=round(dist / entry * 100, 2))
                trades.append(tr)
                busy = tr["exit_date"]
    with open("bt2_trades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0].keys()) if trades else ["variant"])
        w.writeheader()
        for t in trades:
            w.writerow({**t, "result": round(t["result"], 2)})
    print(f"В тесте {ntest} дней ({min(test_dates)} … {max(test_dates)}), бумаг {len(data)}\n")
    print("| Вариант | Сторона | Сделок | В месяц | Прибыльных | Средний | Медиана | Профит-фактор | Ср. стоп | Ср. дней | Выходы: стоп/трейл/объём/срок |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for v in VARIANTS:
        for sd in ("buy", "sell", "all"):
            ts = [t for t in trades if t["variant"] == v and t["exit"] != "открыта" and (sd == "all" or t["side"] == sd)]
            if not ts:
                print(f"| {v} | {sd} | 0 |||||||||")
                continue
            r = np.array([t["result"] for t in ts])
            pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else float("inf")
            ex = defaultdict(int)
            for t in ts:
                ex[t["exit"]] += 1
            print(f"| {v} | {sd} | {len(ts)} | {len(ts) / ntest * 21:.1f} | {np.mean(r > 0) * 100:.0f}% | {r.mean():+.2f}% | {np.median(r):+.2f}% | "
                  f"{pf:.2f} | {np.mean([t['stop_pct'] for t in ts]):.1f}% | {np.mean([t['days'] for t in ts]):.1f} | "
                  f"{ex['стоп']}/{ex['трейлинг']}/{ex['объём против']}/{ex['истёк']} |")
    # по месяцам для лучшего варианта по сумме
    for v in VARIANTS:
        m = defaultdict(list)
        for t in trades:
            if t["variant"] == v and t["exit"] != "открыта":
                m[t["entry_date"][:7]].append(t["result"])
        print(v[:2], "по месяцам (сделок, сумма %):", {k: (len(x), round(sum(x), 1)) for k, x in sorted(m.items())})


if __name__ == "__main__":
    run()
