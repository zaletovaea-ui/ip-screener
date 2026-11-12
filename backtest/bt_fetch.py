#!/usr/bin/env python3
"""Бэктест, шаг 1: скачать tradestats за часть дат и свернуть в 15-минутные слоты.

python backtest/bt_fetch.py <часть> <всего_частей> <месяцев>
Результат: bt_part_<часть>.npz — ключ "ДАТА|ТИКЕР" → массив 7×NSLOTS:
  0 val, 1 val_b, 2 val_s, 3 shares (val/pr_vwap, для VWAP), 4 close, 5 high, 6 low  (по слотам; цены — nan без сделок)
"""
import sys
import datetime as dt
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from moexapi import iss, table, paged  # noqa: E402

SLOT0, SLOT = 7 * 60, 15
NS = (24 * 60 - SLOT0) // SLOT


def slot_of(t):
    h, m = int(t[:2]), int(t[3:5])
    return max(0, min(NS - 1, (h * 60 + m - SLOT0) // SLOT))


def dates(months):
    till = dt.date.today()
    frm = till - dt.timedelta(days=int(months * 31) + 45)  # + запас на норму (20 торговых дней)
    rows = table(iss("engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json",
                     {"interval": 24, "from": frm.isoformat(), "till": till.isoformat()}), "candles")
    ds = sorted({str(r["begin"])[:10] for r in rows})
    return [d for d in ds if dt.date.fromisoformat(d).weekday() < 5 and d < till.isoformat()]


def universe():
    rows = table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
                     {"iss.only": "securities", "securities.columns": "SECID,SECTYPE"}), "securities")
    return {r["SECID"] for r in rows if str(r.get("SECTYPE")) in ("1", "2", "D")}


def main():
    part, n, months = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
    ds = dates(months)[part::n]
    uni = universe()
    out = {}
    for d in ds:
        rows = paged("datashop/algopack/eq/tradestats.json", {"date": d})
        by = {}
        for r in rows:
            if r["secid"] in uni:
                by.setdefault(r["secid"], []).append(r)
        for t, bars in by.items():
            a = np.full((7, NS), np.nan, dtype=np.float32)
            a[0:4] = 0
            for b in sorted(bars, key=lambda r: r["tradetime"]):
                s = slot_of(b["tradetime"])
                val = float(b["val"] or 0)
                a[0, s] += val
                a[1, s] += float(b["val_b"] or 0)
                a[2, s] += float(b["val_s"] or 0)
                if b["pr_vwap"]:
                    a[3, s] += val / float(b["pr_vwap"])
                a[4, s] = b["pr_close"]
                a[5, s] = b["pr_high"] if np.isnan(a[5, s]) else max(a[5, s], b["pr_high"])
                a[6, s] = b["pr_low"] if np.isnan(a[6, s]) else min(a[6, s], b["pr_low"])
            out[f"{d}|{t}"] = a
        print(d, len(by), flush=True)
    np.savez_compressed(f"bt_part_{part}.npz", **out)


if __name__ == "__main__":
    main()
