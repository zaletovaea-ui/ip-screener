#!/usr/bin/env python3
"""Бэктест «против физлиц» на фьючерсе MX (индекс Мосбиржи): сигнал по ОИ физлиц, сделка по индексу.

Цена — индекс IMOEX (фьючерс MX ходит вместе с ним); 1 контракт MX = индекс × 10 ₽.
"""
import sys
import datetime as dt
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from moexapi import iss, table  # noqa: E402
import bt_oi  # noqa: E402

YEARS = float(sys.argv[1]) if len(sys.argv) > 1 else 5
bt_oi.START = dt.date.today() - dt.timedelta(days=int(YEARS * 365) + 120)
MULT = 10  # ₽ за пункт индекса в одном контракте MX


def index_candles():
    out, start = [], 0
    while True:
        rows = table(iss("engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json",
                         {"interval": 24, "from": bt_oi.START.isoformat(), "start": start}), "candles")
        out += rows
        start += len(rows)
        if len(rows) < 500:
            break
    return {str(r["begin"])[:10]: dict(o=r["open"], h=r["high"], l=r["low"], c=r["close"]) for r in out}


VARIANTS = {
    "за день ≥5% позиции физлиц": dict(kind="rel", thr=0.05),
    "за день ≥10% позиции физлиц": dict(kind="rel", thr=0.10),
    "за день ≥1 млрд ₽": dict(kind="rub", rub=1e9),
    "за день ≥3 млрд ₽": dict(kind="rub", rub=3e9),
    "за день: скачок z ≥2": dict(kind="z1"),
    "3 дня подряд": dict(kind="streak", n=3),
    "3 дня подряд + сумма ≥3 млрд ₽": dict(kind="streak", n=3, rub=3e9),
}
EXITS = {"без тейка, 10 дн.": dict(take=None, max_days=10), "тейк 3%, 10 дн.": dict(take=0.03, max_days=10)}


def main():
    oi = bt_oi.futoi("MX")
    px = index_candles()
    ds = sorted(d for d in oi if d in px)
    pdays = sorted(px)
    pidx = {d: i for i, d in enumerate(pdays)}
    test_from = (dt.date.today() - dt.timedelta(days=int(YEARS * 365))).isoformat()
    print(f"MX: дней ОИ {len(ds)} ({ds[0]} … {ds[-1]}), тест с {test_from}")
    rel_sig = bt_oi.signals(ds, oi, "rel", 1e-9)
    z_sig = bt_oi.signals(ds, oi, "z1")
    st_cache = {}
    trades = []
    for vname, sp in VARIANTS.items():
        for ename, ep in EXITS.items():
            if sp["kind"] == "streak":
                st_cache.setdefault(sp["n"], bt_oi.streaks(ds, oi, sp["n"]))
                sigs = st_cache[sp["n"]]
            elif sp["kind"] == "z1":
                sigs = {d: (s, dl, None) for d, (s, dl) in z_sig.items()}
            else:
                sigs = {d: (s, dl, None) for d, (s, dl) in rel_sig.items()}
            busy = ""
            for d, (side, delta, st_i) in sorted(sigs.items()):
                if d < test_from or d <= busy:
                    continue
                prv = ds[st_i] if st_i is not None else ds[ds.index(d) - 1]
                gross = oi[prv]["FIZ"]["pos_long"] - oi[prv]["FIZ"]["pos_short"]
                rel = abs(delta) / gross if gross else 0
                rub = abs(delta) * MULT * px[d]["c"]
                if sp["kind"] == "rel" and rel < sp["thr"]:
                    continue
                if sp.get("rub") and rub < sp["rub"]:
                    continue
                t = bt_oi.trade(px, pdays, pidx[d], side, ep["take"], ep["max_days"])
                if not t:
                    continue
                trades.append(dict(variant=f"{vname} | {ename}", side=side, date=d, rub=rub, rel=rel, **t))
                busy = t["exit_date"]
    ndays = YEARS * 250
    print("\n| Сигнал | Выход | Сторона | Сделок | В год | Прибыльных | Средний | Медиана | Профит-фактор | Ср. дней |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for v in sorted({t["variant"] for t in trades}, key=lambda x: list(VARIANTS).index(x.split(" | ")[0]) * 10 + list(EXITS).index(x.split(" | ")[1])):
        for sd in ("buy", "sell", "all"):
            ts = [t for t in trades if t["variant"] == v and (sd == "all" or t["side"] == sd)]
            if not ts:
                continue
            r = np.array([t["result"] for t in ts])
            pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else float("inf")
            print(f"| {v} | {sd} | {len(ts)} | {len(ts) / ndays * 250:.0f} | {np.mean(r > 0) * 100:.0f}% | {r.mean():+.2f}% | "
                  f"{np.median(r):+.2f}% | {pf:.2f} | {np.mean([t['days'] for t in ts]):.1f} |")
    for v in sorted({t["variant"] for t in trades}):
        y = defaultdict(list)
        for t in trades:
            if t["variant"] == v:
                y[t["date"][:4]].append(t["result"])
        print(v, "| по годам (сделок, сумма %):", {k: (len(x), round(float(np.sum(x)), 1)) for k, x in sorted(y.items())})
    # типичные дневные изменения позиции физлиц в MX
    net = np.array([oi[d]["FIZ"]["pos"] for d in ds[-250:]], dtype=float)
    d1 = np.abs(np.diff(net))
    print("MX: медианное |изменение| позиции физлиц за день, контрактов:", int(np.median(d1)),
          "| 90-й перцентиль:", int(np.percentile(d1, 90)), "| в рублях медиана ≈", round(np.median(d1) * MULT * px[ds[-1]]["c"] / 1e9, 2), "млрд")


if __name__ == "__main__":
    main()
