#!/usr/bin/env python3
"""MX «всегда против физлиц»: переворот, когда чистая позиция физлиц за N дней изменилась на ≥ порог контрактов.

Позиция меняется по открытию следующего дня; результат — по индексу IMOEX (MX ходит вместе с ним).
"""
import sys
import datetime as dt
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bt_oi  # noqa: E402
from bt_mx import index_candles  # noqa: E402

YEARS = float(sys.argv[1]) if len(sys.argv) > 1 else 5
bt_oi.START = dt.date.today() - dt.timedelta(days=int(YEARS * 365) + 30)
COMM = 0.0003  # комиссия+проскальзывание на одну смену позиции (0,03% от суммы)


def run(oi, px, ds, thr, win, mode="flip"):
    net = {d: oi[d]["FIZ"]["pos"] for d in ds}
    days = [d for d in sorted(px) if d >= ds[win]]
    pos, eq, curve, trades, cur = 0, 1.0, [], [], None
    pending = None
    for k, d in enumerate(days):
        o, c = px[d]["o"], px[d]["c"]
        if pending is not None and pending != pos:   # исполнение по открытию
            prevc = px[days[k - 1]]["c"] if k else o
            eq *= 1 + pos * (o / prevc - 1)          # старая позиция: от вчерашнего закрытия до открытия
            if pos and cur:
                r = pos * (o / cur["entry"] - 1)
                trades.append(dict(cur, exit=d, result=r * 100))
            eq *= 1 - COMM * (2 if pos else 1)
            pos = pending
            cur = dict(side=pos, start=d, entry=o) if pos else None
            ref = o
        else:
            ref = px[days[k - 1]]["c"] if k else o
        eq *= 1 + pos * (c / ref - 1)
        curve.append((d, eq, pos))
        if d in net:
            i = ds.index(d)
            if i >= win:
                ch = net[d] - net[ds[i - win]]
                if ch >= thr:
                    pending = -1
                elif ch <= -thr:
                    pending = 1
                elif mode == "flat_on_calm":
                    pending = 0
    if pos and cur:
        trades.append(dict(cur, exit="открыта", result=pos * (px[days[-1]]["c"] / cur["entry"] - 1) * 100))
    return curve, trades


def stats(curve, trades, bh):
    eq = np.array([e for _, e, _ in curve])
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1).min() * 100
    yrs = len(curve) / 250
    years = defaultdict(list)
    for d, e, _ in curve:
        years[d[:4]].append(e)
    by_year, prev = {}, 1.0
    for y in sorted(years):
        by_year[y] = round((years[y][-1] / prev - 1) * 100, 1)
        prev = years[y][-1]
    closed = [t for t in trades if t["exit"] != "открыта"]
    r = np.array([t["result"] for t in closed]) if closed else np.array([0.0])
    return dict(total=round((eq[-1] - 1) * 100, 1), cagr=round((eq[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round(dd, 1),
                flips=len(trades), per_year=round(len(trades) / yrs, 1), win=round(float(np.mean(r > 0) * 100)),
                avg=round(float(r.mean()), 2), days=round(float(np.mean([(dt.date.fromisoformat(t["exit"]) - dt.date.fromisoformat(t["start"])).days for t in closed])) if closed else 0, 1),
                in_market=round(float(np.mean([p != 0 for _, _, p in curve]) * 100)), by_year=by_year, bh=bh)


def main():
    oi = bt_oi.futoi("MX")
    px = index_candles()
    ds = sorted(d for d in oi if d in px)
    first = [d for d in sorted(px) if d >= ds[3]][0]
    bh = round((px[sorted(px)[-1]]["c"] / px[first]["o"] - 1) * 100, 1)
    print(f"MX: {ds[0]} … {ds[-1]}; индекс за период (купил и держи): {bh:+}%")
    net = np.array([oi[d]["FIZ"]["pos"] for d in ds], dtype=float)
    d3 = np.abs(net[3:] - net[:-3])
    print("Изменение позиции физлиц за 3 дня, контрактов: медиана", int(np.median(d3)), "| 75%", int(np.percentile(d3, 75)), "| 90%", int(np.percentile(d3, 90)))
    print("\n| Правило | Итого | В год (CAGR) | Макс. просадка | Переворотов в год | Прибыльных позиций | Средняя позиция | Дней в позиции |")
    print("|---|---|---|---|---|---|---|---|")
    res = {}
    for win in (3,):
        for thr in (5000, 10000, 15000, 20000):
            for mode in ("flip",):
                curve, trades = run(oi, px, ds, thr, win, mode)
                s = stats(curve, trades, bh)
                name = f"{win} дня, ≥{thr // 1000} тыс. контр."
                res[name] = (s, trades)
                print(f"| {name} | {s['total']:+}% | {s['cagr']:+}% | {s['maxdd']}% | {s['per_year']} | {s['win']}% | {s['avg']:+}% | {s['days']} |")
    print()
    for name, (s, trades) in res.items():
        print(name, "| по годам %:", s["by_year"])
    s, trades = res["3 дня, ≥10 тыс. контр."]
    print("\nПоследние позиции (правило 10 тыс.):")
    for t in trades[-8:]:
        print(" ", "лонг" if t["side"] > 0 else "шорт", t["start"], "→", t["exit"], f"{t['result']:+.2f}%")


if __name__ == "__main__":
    main()
