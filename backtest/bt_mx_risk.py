#!/usr/bin/env python3
"""MX «всегда против физлиц» + стоп/тейк.

Сигнал: изменение чистой позиции физлиц за 3 дня ≥ порога → позиция против них, исполнение по открытию следующего дня.
Стоп/тейк проверяются внутри дня по high/low индекса (если в один день задеты оба — считаем стоп).
Гэп за стоп/тейк — выход по открытию. После выхода по стопу/тейку стоим вне рынка:
  reentry="opposite" — ждём сигнала в противоположную сторону (обычный переворот);
  reentry="any"      — заходим снова, как только сигнал есть (в т. ч. в ту же сторону).
"""
import sys
import datetime as dt
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bt_oi  # noqa: E402
from bt_mx import index_candles  # noqa: E402

bt_oi.START = dt.date(2022, 12, 1)
COMM = 0.0003
THR, WIN = 10000, 3


def run(px, sig, stop=None, take=None, reentry="opposite"):
    days = sorted(px)
    pos, entry, eq, curve, trades, start = 0, None, 1.0, [], [], None
    pending, last_dir = None, 0
    for k, d in enumerate(days):
        o, h, l, c = px[d]["o"], px[d]["h"], px[d]["l"], px[d]["c"]
        prevc = px[days[k - 1]]["c"] if k else o
        ref = prevc
        # исполнение сигнала по открытию
        if pending and pending != pos:
            ok = reentry == "any" or pos != 0 or pending != last_dir
            if ok:
                eq *= 1 + pos * (o / prevc - 1)
                if pos:
                    trades.append(dict(side=pos, start=start, exit=d, result=pos * (o / entry - 1) * 100, why="переворот"))
                eq *= 1 - COMM * (2 if pos else 1)
                pos, entry, start, ref, last_dir = pending, o, d, o, pending
        # стоп / тейк внутри дня
        if pos:
            sl = entry * (1 - pos * stop) if stop else None
            tp = entry * (1 + pos * take) if take else None
            px_exit, why = None, None
            if sl is not None and ((pos > 0 and o <= sl) or (pos < 0 and o >= sl)):
                px_exit, why = o, "стоп (гэп)"
            elif tp is not None and ((pos > 0 and o >= tp) or (pos < 0 and o <= tp)):
                px_exit, why = o, "тейк (гэп)"
            elif sl is not None and ((pos > 0 and l <= sl) or (pos < 0 and h >= sl)):
                px_exit, why = sl, "стоп"
            elif tp is not None and ((pos > 0 and h >= tp) or (pos < 0 and l <= tp)):
                px_exit, why = tp, "тейк"
            if px_exit:
                eq *= 1 + pos * (px_exit / ref - 1)
                eq *= 1 - COMM
                trades.append(dict(side=pos, start=start, exit=d, result=pos * (px_exit / entry - 1) * 100, why=why))
                pos, entry = 0, None
                curve.append((d, eq, 0))
                pending = sig.get(d)
                continue
        eq *= 1 + pos * (c / ref - 1)
        curve.append((d, eq, pos))
        pending = sig.get(d)
    if pos:
        trades.append(dict(side=pos, start=start, exit="открыта", result=pos * (px[days[-1]]["c"] / entry - 1) * 100, why="открыта"))
    return curve, trades


def stats(curve, trades):
    eq = np.array([e for _, e, _ in curve])
    dd = (eq / np.maximum.accumulate(eq) - 1).min() * 100
    yrs = len(curve) / 250
    closed = [t for t in trades if t["exit"] != "открыта"]
    r = np.array([t["result"] for t in closed]) if closed else np.array([0.0])
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    years, prev, by = {}, 1.0, {}
    for d, e, _ in curve:
        years[d[:4]] = e
    for y in sorted(years):
        by[y] = round((years[y] / prev - 1) * 100, 1)
        prev = years[y]
    return dict(total=(eq[-1] - 1) * 100, cagr=(eq[-1] ** (1 / yrs) - 1) * 100, dd=dd, n=len(closed) / yrs,
                win=np.mean(r > 0) * 100, pf=gp / gl if gl else float("inf"),
                stops=sum("стоп" in t["why"] for t in closed), takes=sum("тейк" in t["why"] for t in closed),
                inm=np.mean([p != 0 for _, _, p in curve]) * 100, by=by)


def main():
    oi = bt_oi.futoi("MX")
    px = index_candles()
    ds = sorted(d for d in oi if d in px)
    net = {d: oi[d]["FIZ"]["pos"] for d in ds}
    sig = {}
    for i in range(WIN, len(ds)):
        ch = net[ds[i]] - net[ds[i - WIN]]
        if ch >= THR:
            sig[ds[i]] = -1
        elif ch <= -THR:
            sig[ds[i]] = 1
    px = {d: v for d, v in px.items() if d > ds[WIN]}
    print(f"MX против физлиц, порог {THR}, {min(px)} … {max(px)}; индекс: {(px[max(px)]['c'] / px[min(px)]['o'] - 1) * 100:+.1f}%")
    print("\n| Вариант | Итого | В год | Макс. просадка | Сделок в год | Прибыльных | PF | Стопов | Тейков | В рынке |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    rows = [("Без стопа и тейка (как сейчас)", None, None, "opposite")]
    for st in (0.02, 0.03, 0.04, 0.05):
        rows.append((f"Стоп {st:.0%}", st, None, "opposite"))
    for tk in (0.04, 0.06, 0.08, 0.10):
        rows.append((f"Тейк {tk:.0%}", None, tk, "opposite"))
    for st, tk in ((0.02, 0.04), (0.02, 0.06), (0.03, 0.06), (0.03, 0.08), (0.04, 0.08), (0.05, 0.10)):
        rows.append((f"Стоп {st:.0%} + тейк {tk:.0%}", st, tk, "opposite"))
    for st, tk in ((0.03, None), (0.03, 0.06), (0.04, 0.08)):
        rows.append((f"Стоп {st:.0%}" + (f" + тейк {tk:.0%}" if tk else "") + ", перезаход по сигналу", st, tk, "any"))
    res = {}
    for name, st, tk, re_ in rows:
        curve, trades = run(px, sig, st, tk, re_)
        s = stats(curve, trades)
        res[name] = s
        print(f"| {name} | {s['total']:+.1f}% | {s['cagr']:+.1f}% | {s['dd']:.1f}% | {s['n']:.1f} | {s['win']:.0f}% | {s['pf']:.2f} | {s['stops']} | {s['takes']} | {s['inm']:.0f}% |")
    print()
    for name, s in res.items():
        print(name, "| по годам %:", s["by"])


if __name__ == "__main__":
    main()
