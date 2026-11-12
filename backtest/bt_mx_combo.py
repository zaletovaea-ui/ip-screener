#!/usr/bin/env python3
"""MX против физлиц: дневная дельта vs 3-дневная и их комбинации. Переворот по открытию следующего дня, без стопов."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bt_oi  # noqa: E402
import bt_mx_risk as R  # noqa: E402
from bt_mx import index_candles  # noqa: E402


def signals(ds, net, rules):
    """rules: список (окно, порог). Сигнал, если любое правило сработало; при конфликте — по самому короткому окну."""
    sig = {}
    for i in range(len(ds)):
        for win, thr in sorted(rules):
            if i < win:
                continue
            ch = net[ds[i]] - net[ds[i - win]]
            if ch >= thr:
                sig[ds[i]] = -1
                break
            if ch <= -thr:
                sig[ds[i]] = 1
                break
    return sig


def main():
    oi = bt_oi.futoi("MX")
    px0 = index_candles()
    ds = sorted(d for d in oi if d in px0)
    net = {d: oi[d]["FIZ"]["pos"] for d in ds}
    import numpy as np
    d1 = np.abs(np.diff([net[d] for d in ds]))
    print(f"MX {ds[0]} … {ds[-1]}. Дневное изменение позиции физлиц: медиана {int(np.median(d1))}, 75% {int(np.percentile(d1, 75))}, 90% {int(np.percentile(d1, 90))}, 95% {int(np.percentile(d1, 95))}")
    px = {d: v for d, v in px0.items() if d > ds[3]}
    variants = [("3 дня ≥10 тыс. (сейчас)", [(3, 10000)])]
    for t in (5000, 7000, 8000, 10000, 12000):
        variants.append((f"1 день ≥{t / 1000:g} тыс.", [(1, t)]))
    for t in (7000, 8000, 10000, 12000):
        variants.append((f"1 день ≥{t / 1000:g} тыс. ИЛИ 3 дня ≥10 тыс.", [(1, t), (3, 10000)]))
    variants.append(("2 дня ≥8 тыс. ИЛИ 3 дня ≥10 тыс.", [(2, 8000), (3, 10000)]))
    print("\n| Правило | Итого | В год | Макс. просадка | Сделок в год | Прибыльных | PF |")
    print("|---|---|---|---|---|---|---|")
    for name, rules in variants:
        curve, trades = R.run(px, signals(ds, net, rules))
        s = R.stats(curve, trades)
        print(f"| {name} | {s['total']:+.1f}% | {s['cagr']:+.1f}% | {s['dd']:.1f}% | {s['n']:.1f} | {s['win']:.0f}% | {s['pf']:.2f} |")
        print("   по годам:", s["by"])


if __name__ == "__main__":
    main()
