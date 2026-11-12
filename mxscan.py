#!/usr/bin/env python3
"""
MX — всегда против физлиц (правило Евгении, 12.11.2026):
изменение чистой позиции физлиц во фьючерсе MX за 3 торговых дня ≥ +10 000 контрактов → шорт MX,
≤ −10 000 → лонг MX; иначе держим текущую позицию. Смена позиции — по открытию следующего дня.
Результат считаем по индексу Мосбиржи (MX ходит вместе с ним), с учётом 0,03% на каждую смену позиции.

Файл: docs/data/mx.json
"""
import json
import sys
import datetime as dt
from pathlib import Path

from moexapi import TOKEN, iss, table

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data" / "mx.json"
LIVE = ROOT / "docs" / "data" / "mx_live.json"
M = {"window": 3, "threshold": 10000, "since": "2023-01-01", "live_from": "2026-11-12", "comm": 0.0003}


def msk_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=3)


def futoi_mx(frm):
    out = {}
    a = frm
    today = msk_now().date()
    while a <= today:
        b = min(today, a + dt.timedelta(days=300))
        for r in table(iss("analyticalproducts/futoi/securities/mx.json",
                           {"from": a.isoformat(), "till": b.isoformat(), "latest": 1}), "futoi"):
            if dt.date.fromisoformat(r["tradedate"]).weekday() < 5:
                out.setdefault(r["tradedate"], {})[r["clgroup"]] = r
        a = b + dt.timedelta(days=1)
    return {d: v for d, v in out.items() if "FIZ" in v}


def index_daily(frm):
    out, start = [], 0
    while True:
        rows = table(iss("engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json",
                         {"interval": 24, "from": frm.isoformat(), "start": start}), "candles")
        out += rows
        start += len(rows)
        if len(rows) < 500:
            break
    return {str(r["begin"])[:10]: dict(o=r["open"], h=r["high"], l=r["low"], c=r["close"]) for r in out}


def front_mx():
    """Ближний фьючерс MX с торгами: (SECID, последняя цена, время)."""
    sec = table(iss("engines/futures/markets/forts/securities.json",
                    {"iss.only": "securities", "securities.columns": "SECID,ASSETCODE,LASTTRADEDATE"}), "securities")
    md = {r["SECID"]: r for r in table(iss("engines/futures/markets/forts/securities.json",
          {"iss.only": "marketdata", "marketdata.columns": "SECID,LAST,UPDATETIME"}), "marketdata")}
    today = msk_now().strftime("%Y-%m-%d")
    mx = sorted((r for r in sec if r["ASSETCODE"] == "MIX" and r["LASTTRADEDATE"] > today and (md.get(r["SECID"]) or {}).get("LAST")),
                key=lambda r: r["LASTTRADEDATE"])
    r = mx[0]
    return r["SECID"], md[r["SECID"]]["LAST"], str(md[r["SECID"]]["UPDATETIME"])[:5]


def mx_open(secid, date):
    rows = table(iss(f"engines/futures/markets/forts/securities/{secid}/candles.json",
                     {"interval": 24, "from": date, "till": date}), "candles")
    return rows[0]["open"] if rows else None


def update_live(net_closed, closed_days, snap):
    """Живой журнал MX: перевороты внутри дня по изменению позиции физлиц за 3 дня (вкл. сегодня)."""
    now = msk_now()
    j = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else None
    secid, last, utime = front_mx()
    if j is None:  # старт наблюдения: лонг с открытия 12.11.2026 (сигнал по итогам 11.11)
        e = mx_open(secid, M["live_from"]) or last
        j = dict(position="long", contract=secid, entry=e, entry_time=M["live_from"] + " открытие", events=[
            dict(time=M["live_from"] + " 09:00", action="Открываем лонг MX", side="long", price=e, contract=secid,
                 reason="старт наблюдения: физлица за 3 дня сократили позицию на 18 716 контр.")], trades=[])
    def close_open(new_side, price, reason):
        old = j["position"]
        if old:
            res = round(((price / j["entry"] - 1) if old == "long" else (1 - price / j["entry"])) * 100, 2)
            j["trades"].append(dict(side=old, contract=j["contract"], open_time=j["entry_time"], open_price=j["entry"],
                                    close_time=now.strftime("%Y-%m-%d %H:%M"), close_price=price, result=res))
            j["events"].append(dict(time=now.strftime("%Y-%m-%d %H:%M"), action=f"Закрываем {'лонг' if old == 'long' else 'шорт'} MX",
                                    side=old, price=price, contract=j["contract"], result=res, reason=reason))
        j.update(position=new_side, contract=secid, entry=price, entry_time=now.strftime("%Y-%m-%d %H:%M"))
        j["events"].append(dict(time=now.strftime("%Y-%m-%d %H:%M"), action=f"Открываем {'лонг' if new_side == 'long' else 'шорт'} MX",
                                side=new_side, price=price, contract=secid, reason=reason))
    # перенос на следующий контракт при экспирации
    if j["position"] and j["contract"] != secid:
        close_open(j["position"], last, f"перенос позиции {j['contract']} → {secid}")
    d3 = None
    if snap and len(closed_days) >= M["window"]:
        base = closed_days[-M["window"]] if snap["tradedate"] not in net_closed else closed_days[-M["window"] - 1]
        d3 = snap["pos"] - net_closed[base]
        want = "short" if d3 >= M["threshold"] else "long" if d3 <= -M["threshold"] else None
        if want and want != j["position"]:
            crowd = "нарастили лонг" if d3 > 0 else "нарастили шорт"
            close_open(want, last, f"физлица за 3 дня {crowd}: {d3:+,} контр. (порог {M['threshold']:,})".replace(",", " "))
    cur = round(((last / j["entry"] - 1) if j["position"] == "long" else (1 - last / j["entry"])) * 100, 2) if j["position"] else None
    eq = 1.0
    for t in j["trades"]:
        eq *= 1 + t["result"] / 100
    j.update(last_price=last, last_time=utime, contract_now=secid, current=cur, d3_now=d3,
             snap_time=(snap or {}).get("tradetime", "")[:5] if snap else None,
             closed_return=round((eq - 1) * 100, 2), total_return=round((eq * (1 + (cur or 0) / 100) - 1) * 100, 2),
             updated=now.strftime("%Y-%m-%d %H:%M"))
    LIVE.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    return j


def main():
    frm = dt.date.fromisoformat(M["since"]) - dt.timedelta(days=15)
    oi, px = futoi_mx(frm), index_daily(frm)
    ds = sorted(d for d in oi if d in px)
    net = {d: oi[d]["FIZ"]["pos"] for d in ds}
    w, thr = M["window"], M["threshold"]
    days = [d for d in sorted(px) if d >= M["since"]]
    pos, eq, pending, cur = 0, 1.0, None, None
    curve, flips, rows = [], [], []
    for k, d in enumerate(days):
        o, c = px[d]["o"], px[d]["c"]
        prevc = px[days[k - 1]]["c"] if k else o
        if pending is not None and pending != pos:
            eq *= 1 + pos * (o / prevc - 1)
            if cur:
                cur.update(exit=d, exit_price=o, result=round(pos * (o / cur["entry"] - 1) * 100, 2))
            eq *= 1 - M["comm"] * (2 if pos else 1)
            pos = pending
            cur = dict(side="long" if pos > 0 else "short", start=d, entry=o, live=d >= M["live_from"])
            flips.append(cur)
            ref = o
        else:
            ref = prevc
        eq *= 1 + pos * (c / ref - 1)
        curve.append([d, round((eq - 1) * 100, 2), pos])
        if d in net:
            i = ds.index(d)
            ch = net[d] - net[ds[i - w]] if i >= w else None
            if ch is not None and ch >= thr:
                pending = -1
            elif ch is not None and ch <= -thr:
                pending = 1
            rows.append(dict(date=d, intraday=(d == msk_now().strftime("%Y-%m-%d") and msk_now().strftime("%H:%M") < "23:55"), net=net[d], d1=net[d] - net[ds[i - 1]] if i else None, d3=ch,
                             long=oi[d]["FIZ"]["pos_long"], short=-oi[d]["FIZ"]["pos_short"],
                             long_num=oi[d]["FIZ"]["pos_long_num"], short_num=oi[d]["FIZ"]["pos_short_num"],
                             index=c, pos=pos, signal=("short" if ch is not None and ch >= thr else "long" if ch is not None and ch <= -thr else None)))
    # текущий (внутридневной) снимок: кандидат на переворот завтра
    live = None
    try:
        snap = {r["clgroup"]: r for r in table(iss("analyticalproducts/futoi/securities/mx.json", {"latest": 1}), "futoi")}
        if "FIZ" in snap and snap["FIZ"]["tradedate"] not in net:
            base = ds[-w] if len(ds) >= w else ds[0]
            ch = snap["FIZ"]["pos"] - net[base]
            live = dict(date=snap["FIZ"]["tradedate"], time=str(snap["FIZ"]["tradetime"])[:5], net=snap["FIZ"]["pos"],
                        d1=snap["FIZ"]["pos"] - net[ds[-1]], d3=ch,
                        signal=("short" if ch >= thr else "long" if ch <= -thr else None))
    except Exception as e:  # noqa
        print("снимок:", e, file=sys.stderr)
    last_c = px[days[-1]]["c"]
    if cur:
        cur["current"] = round(pos * (last_c / cur["entry"] - 1) * 100, 2)
    eqs = [e for _, e, _ in curve]
    peak, mdd = -1e9, 0
    for e in eqs:
        peak = max(peak, e)
        mdd = min(mdd, (100 + e) / (100 + peak) - 1)
    by_year, prev_end, cy, last = {}, 0.0, None, 0.0
    for d, e, _ in curve:
        if d[:4] != cy:
            if cy:
                by_year[cy] = round(((100 + last) / (100 + prev_end) - 1) * 100, 1)
                prev_end = last
            cy = d[:4]
        last = e
    if cy:
        by_year[cy] = round(((100 + last) / (100 + prev_end) - 1) * 100, 1)
    before = [e for d, e, _ in curve if d < M["live_from"]]
    live_ret = round(((100 + curve[-1][1]) / (100 + (before[-1] if before else 0)) - 1) * 100, 2) if curve and curve[-1][0] >= M["live_from"] else None
    out = dict(updated=msk_now().strftime("%Y-%m-%d %H:%M"), params=M, position=("long" if pos > 0 else "short" if pos < 0 else None),
               pending=(("long" if pending > 0 else "short") if pending and pending != pos else None),
               current=cur, live=live, total=curve[-1][1] if curve else 0, live_return=live_ret, maxdd=round(mdd * 100, 1),
               by_year=by_year, index_change=round((last_c / px[days[0]]["o"] - 1) * 100, 1), index=last_c,
               flips=flips[::-1], rows=rows[-30:][::-1], curve=curve)
    try:
        snap_fiz = table(iss("analyticalproducts/futoi/securities/mx.json", {"latest": 1}), "futoi")
        snap_fiz = next((r for r in snap_fiz if r["clgroup"] == "FIZ"), None)
        today = msk_now().strftime("%Y-%m-%d")
        closed = [d for d in ds if d < today]
        out["live_journal"] = update_live({d: net[d] for d in closed}, closed, snap_fiz)
    except Exception as e:  # noqa
        print("живой журнал MX:", e, file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"MX: позиция {out['position']} с {cur['start'] if cur else '-'}, итог {out['total']}%, просадка {out['maxdd']}%, "
          f"переворотов {len(flips)}, ожидается {out['pending']}, снимок {live}")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Нужен ключ AlgoPack: секрет MOEX_TOKEN")
    main()
