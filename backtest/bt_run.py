#!/usr/bin/env python3
"""Бэктест, шаг 2: сигналы аномального объёма по 15-минутным проверкам и сделки по правилам выхода.

python backtest/bt_run.py bt_part_*.npz
Печатает сводную таблицу по вариантам; сделки — в bt_trades.csv.
"""
import csv
import sys
from collections import defaultdict

import numpy as np

SLOT0, SLOT = 7 * 60, 15
NS = (24 * 60 - SLOT0) // SLOT
FIRST_CHECK = (10 * 60 + 15 - SLOT0) // SLOT   # 10:15 — первая проверка для «рекомендуемых»
NORM_DAYS, MIN_DAYS = 20, 10

EXIT = dict(stop_pad=0.005, min_stop=0.015, max_stop=0.08, trail_from=5, trail=0.014, max_days=10,
            against_ratio=2.0, against_share=0.6)

VARIANTS = {
    "1. Как сейчас: ×3, покупатели за день ≥58%": dict(
        ratio=3, day_share=0.58, win=None, first=0, vwap=False, chg=(1.5, 99), pos=0.6, value=30e6),
    "2. Рекомендуемый: ×3, дисбаланс за час ≥+0.2, выше VWAP": dict(
        ratio=3, day_share=0.53, win=dict(n=4, ratio=3, imb=0.2), first=FIRST_CHECK, vwap=True, chg=(1.5, 8), pos=0.6, value=50e6),
    "3. Строгий: ×5, дисбаланс за час ≥+0.2, выше VWAP": dict(
        ratio=5, day_share=0.53, win=dict(n=4, ratio=3, imb=0.2), first=FIRST_CHECK, vwap=True, chg=(1.5, 8), pos=0.6, value=50e6),
}


def load(files):
    data = defaultdict(dict)
    for f in files:
        z = np.load(f)
        for k in z.files:
            d, t = k.split("|")
            data[t][d] = z[k]
    return data


def day_ohlc(a):
    c = a[4][~np.isnan(a[4])]
    if not len(c):
        return None
    return dict(o=float(c[0]), c=float(c[-1]), h=float(np.nanmax(a[5])), l=float(np.nanmin(a[6])),
                val=float(a[0].sum()), vb=float(a[1].sum()), vs=float(a[2].sum()))


def run():
    data = load(sys.argv[1:])
    alldates = sorted({d for t in data for d in data[t]})
    test_dates = alldates[NORM_DAYS:]
    print(f"Дней: {len(alldates)} ({alldates[0]} … {alldates[-1]}), в тесте {len(test_dates)} "
          f"({test_dates[0]} … {test_dates[-1]}), бумаг {len(data)}")
    trades = []
    for vname, P in VARIANTS.items():
        for t, days in data.items():
            ds = sorted(days)
            cum = {d: np.cumsum(days[d][0]) for d in ds}
            ohlc = {d: day_ohlc(days[d]) for d in ds}
            busy_until = ""
            for i, d in enumerate(ds):
                if d not in test_dates or i < MIN_DAYS or d <= busy_until:
                    continue
                prev = [x for x in ds[max(0, i - NORM_DAYS):i]]
                if len(prev) < MIN_DAYS or not ohlc[ds[i - 1]] or not ohlc[d]:
                    continue
                pc = ohlc[ds[i - 1]]["c"]
                norm_cum = np.median(np.stack([cum[x] for x in prev]), axis=0)
                win_norm = None
                if P["win"]:
                    n = P["win"]["n"]
                    wins = np.stack([np.convolve(days[x][0], np.ones(n), "full")[:NS] for x in prev])
                    win_norm = np.median(wins, axis=0)
                a = days[d]
                c_cum = cum[d]
                vb_c, vs_c, sh_c = np.cumsum(a[1]), np.cumsum(a[2]), np.cumsum(a[3])
                hi_c = np.fmax.accumulate(np.nan_to_num(a[5], nan=-np.inf))
                lo_c = np.fmin.accumulate(np.nan_to_num(a[6], nan=np.inf))
                last = None
                for s in range(NS):
                    if not np.isnan(a[4, s]):
                        last = float(a[4, s])
                    if s < P["first"] or last is None or norm_cum[s] <= 0 or c_cum[s] < P["value"]:
                        continue
                    ratio = c_cum[s] / norm_cum[s]
                    if ratio < P["ratio"]:
                        continue
                    tot = vb_c[s] + vs_c[s]
                    share = vb_c[s] / tot if tot else 0.5
                    chg = (last / pc - 1) * 100
                    rng = hi_c[s] - lo_c[s]
                    pos = (last - lo_c[s]) / rng if rng > 0 else 0.5
                    vwap = c_cum[s] / sh_c[s] if sh_c[s] else last
                    side = None
                    for sd, sign in (("buy", 1), ("sell", -1)):
                        ok = (share >= P["day_share"]) if sign > 0 else (share <= 1 - P["day_share"])
                        ok = ok and P["chg"][0] <= sign * chg <= P["chg"][1]
                        ok = ok and ((pos >= P["pos"]) if sign > 0 else (pos <= 1 - P["pos"]))
                        if P["vwap"]:
                            ok = ok and ((last > vwap) if sign > 0 else (last < vwap))
                        if P["win"] and ok:
                            n = P["win"]["n"]
                            lo = max(0, s - n + 1)
                            wv = a[0, lo:s + 1].sum()
                            wb, ws = a[1, lo:s + 1].sum(), a[2, lo:s + 1].sum()
                            imb = (wb - ws) / (wb + ws) if wb + ws else 0
                            ok = win_norm[s] > 0 and wv / win_norm[s] >= P["win"]["ratio"] and sign * imb >= P["win"]["imb"]
                        if ok:
                            side = sd
                            break
                    if not side:
                        continue
                    tr = simulate(t, ds, i, s, last, float(hi_c[s]), float(lo_c[s]), side, days, ohlc, data)
                    tr.update(variant=vname, ratio=round(float(ratio), 1), share=round(share * 100), chg=round(chg, 2))
                    trades.append(tr)
                    busy_until = tr["exit_date"]
                    break
    report(trades, len(test_dates))


def simulate(t, ds, i, s, entry, hi, lo, side, days, ohlc, data):
    buy = side == "buy"
    if buy:
        stop = min(lo * (1 - EXIT["stop_pad"]), entry * (1 - EXIT["min_stop"]))
        stop = max(stop, entry * (1 - EXIT["max_stop"]))
    else:
        stop = max(hi * (1 + EXIT["stop_pad"]), entry * (1 + EXIT["min_stop"]))
        stop = min(stop, entry * (1 + EXIT["max_stop"]))
    d0 = ds[i]
    res = lambda px: ((px / entry - 1) if buy else (1 - px / entry)) * 100  # noqa: E731
    a = days[d0]
    for k in range(s + 1, NS):  # остаток дня входа
        if np.isnan(a[5, k]):
            continue
        if (buy and a[6, k] <= stop) or (not buy and a[5, k] >= stop):
            return dict(ticker=t, side=side, entry_date=d0, exit_date=d0, days=0, exit="стоп", result=res(stop))
    best = ohlc[d0]["c"]
    trailing = False
    n = 0
    for j in range(i + 1, len(ds)):
        d = ds[j]
        o = ohlc[d]
        if not o:
            continue
        n += 1
        if (buy and o["l"] <= stop) or (not buy and o["h"] >= stop):
            px = min(stop, o["o"]) if buy else max(stop, o["o"])  # гэп через стоп — по цене открытия
            return dict(ticker=t, side=side, entry_date=d0, exit_date=d, days=n, exit="трейлинг" if trailing else "стоп", result=res(px))
        prev = [x for x in ds[max(0, j - NORM_DAYS):j]]
        dn = np.median([ohlc[x]["val"] for x in prev if ohlc[x]]) if prev else 0
        tot = o["vb"] + o["vs"]
        if dn and tot and o["val"] >= EXIT["against_ratio"] * dn:
            ag = (o["vs"] if buy else o["vb"]) / tot
            if ag >= EXIT["against_share"] and ((o["c"] < o["o"]) if buy else (o["c"] > o["o"])):
                return dict(ticker=t, side=side, entry_date=d0, exit_date=d, days=n, exit="объём против", result=res(o["c"]))
        if n >= EXIT["max_days"]:
            return dict(ticker=t, side=side, entry_date=d0, exit_date=d, days=n, exit="истёк", result=res(o["c"]))
        best = max(best, o["c"]) if buy else min(best, o["c"])
        if n >= EXIT["trail_from"]:
            ns_ = best * (1 - EXIT["trail"]) if buy else best * (1 + EXIT["trail"])
            if (buy and ns_ > stop) or (not buy and ns_ < stop):
                stop, trailing = ns_, True
    last = ohlc[ds[-1]]["c"]
    return dict(ticker=t, side=side, entry_date=d0, exit_date="9999", days=n, exit="открыта", result=res(last))


def report(trades, ndays):
    with open("bt_trades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "ticker", "side", "entry_date", "exit_date", "days", "exit", "result", "ratio", "share", "chg"])
        w.writeheader()
        for t in trades:
            w.writerow({**t, "result": round(t["result"], 2)})
    print()
    print("| Вариант | Сторона | Сделок | В месяц | Прибыльных | Средний результат | Медиана | Сумма | Профит-фактор | Ср. дней | Выходы: стоп/трейл/объём/срок |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for v in VARIANTS:
        for sd in ("buy", "sell", "all"):
            ts = [t for t in trades if t["variant"] == v and t["exit"] != "открыта" and (sd == "all" or t["side"] == sd)]
            if not ts:
                print(f"| {v} | {sd} | 0 | | | | | | | | |")
                continue
            r = np.array([t["result"] for t in ts])
            gains, losses = r[r > 0].sum(), -r[r < 0].sum()
            pf = gains / losses if losses else float("inf")
            ex = defaultdict(int)
            for t in ts:
                ex[t["exit"]] += 1
            print(f"| {v} | {sd} | {len(ts)} | {len(ts) / ndays * 21:.1f} | {np.mean(r > 0) * 100:.0f}% | {r.mean():+.2f}% | {np.median(r):+.2f}% | "
                  f"{r.sum():+.1f}% | {pf:.2f} | {np.mean([t['days'] for t in ts]):.1f} | "
                  f"{ex['стоп']}/{ex['трейлинг']}/{ex['объём против']}/{ex['истёк']} |")


if __name__ == "__main__":
    run()
