#!/usr/bin/env python3
"""
Аномальные объёмы (AlgoPack SuperCandles / tradestats, 5-минутные свечи с разделением покупатели/продавцы).

  python volscan.py intraday   — каждые 15 минут во время торгов: ищет аномалии, открывает сделки,
                                  проверяет стопы по 5-минутным свечам сегодняшнего дня
  python volscan.py nightly    — ночью: дописывает закрытый день в профиль объёмов (норму),
                                  ведёт сделки по дневным правилам (трейлинг, срок, объём против позиции)

Норма объёма: для каждой бумаги — медиана за последние NORM_DAYS дней накопленного оборота
к тому же времени дня (шаг 15 минут, с 07:00 до 24:00 МСК).

Файлы: data/vol_profile.json (профиль, хранится в кэше GitHub Actions, не в репозитории),
       docs/data/volume.json (сигналы и аномалии дня), docs/data/journal_volume.json (журнал).
"""
import json
import statistics
import sys
import datetime as dt
from pathlib import Path

from moexapi import TOKEN, iss, table, paged

ROOT = Path(__file__).parent
PROFILE = ROOT / "data" / "vol_profile.json"
OUT = ROOT / "docs" / "data" / "volume.json"
JOURNAL = ROOT / "docs" / "data" / "journal_volume.json"

V = {
    "norm_days": 20,          # окно нормы, торговых дней
    "min_days": 10,           # меньше дней истории — бумагу не оцениваем
    "ratio": 3.0,             # оборот к этому времени ≥ 3× нормы — аномалия
    "buy_share": 0.58,        # покупка: покупатели инициировали ≥ 58% оборота за день
    "sell_share": 0.42,       # продажа: покупатели ≤ 42% (продавцы ≥ 58%)
    "min_change": 1.5,        # изменение цены за день, % (покупка ≥ +1.5, продажа ≤ −1.5)
    "range_pos": 0.6,         # покупка: цена в верхних 40% дневного диапазона (продажа — в нижних 40%)
    "min_value_mln": 30,      # оборот за день, млн ₽
    "stop_pad": 0.005,        # стоп на 0.5% за минимумом (максимумом) дня сигнала
    "min_stop": 0.015,        # стоп не ближе 1.5% от входа
    "max_stop": 0.08,         # и не дальше 8% (иначе стоп = 8%)
    "trail_from": 5,          # трейлинг-стоп включается с 5-го дня в сделке
    "trail": 0.014,           # трейлинг: 1.4% от максимального закрытия (минимального — для продажи)
    "max_days": 10,           # максимум 10 торговых дней в сделке
    "against_ratio": 2.0,     # выход: дневной оборот ≥ 2× нормы против позиции…
    "against_share": 0.6,     # …и инициаторы против позиции ≥ 60%
    "cooldown": 7,            # календарных дней без повторного входа после стопа
}

SLOT0 = 7 * 60          # 07:00
SLOT = 15               # шаг, минут
NSLOTS = (24 * 60 - SLOT0) // SLOT  # до 24:00


def msk_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=3)


def slot_of(hhmm):
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return max(0, min(NSLOTS - 1, (h * 60 + m - SLOT0) // SLOT))


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return default


def save_json(p, obj, indent=1):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def shares():
    """Акции режима TQBR (без фондов) минус стоп-лист: {secid: name}."""
    rows = table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
                     {"iss.only": "securities", "securities.columns": "SECID,SHORTNAME,SECTYPE"}), "securities")
    excl = set()
    f = ROOT / "exclude.txt"
    if f.exists():
        excl = {ln.split("#")[0].strip().upper() for ln in f.read_text(encoding="utf-8").splitlines() if ln.split("#")[0].strip()}
    return {r["SECID"]: r["SHORTNAME"] for r in rows if str(r.get("SECTYPE")) in ("1", "2", "D") and r["SECID"] not in excl}


def day_bars(date):
    """Все 5-минутные свечи tradestats за дату, сгруппированные по бумагам."""
    rows = paged("datashop/algopack/eq/tradestats.json", {"date": date})
    by = {}
    for r in rows:
        by.setdefault(r["secid"], []).append(r)
    for v in by.values():
        v.sort(key=lambda r: r["tradetime"])
    return by


def summarize(bars):
    """Сводка дня по бумаге: накопленный оборот по 15-минутным слотам, покупатели/продавцы, OHLC."""
    cum = [0] * NSLOTS
    per = [0.0] * NSLOTS
    vb = vs = 0.0
    for b in bars:
        per[slot_of(b["tradetime"])] += float(b["val"] or 0)
        vb += float(b["val_b"] or 0)
        vs += float(b["val_s"] or 0)
    run = 0.0
    for i in range(NSLOTS):
        run += per[i]
        cum[i] = round(run / 1000)  # тыс. ₽
    return {"cum": cum, "val": round(run), "vb": round(vb), "vs": round(vs),
            "o": bars[0]["pr_open"], "h": max(b["pr_high"] for b in bars), "l": min(b["pr_low"] for b in bars),
            "c": bars[-1]["pr_close"]}


# ---------------- профиль (норма) ----------------
def trading_dates(n):
    """Последние n закрытых торговых дней (по дневным свечам индекса)."""
    till = msk_now().date()
    frm = till - dt.timedelta(days=n * 2 + 10)
    rows = table(iss("engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json",
                     {"interval": 24, "from": frm.isoformat(), "till": till.isoformat()}), "candles")
    # выходные сессии (сб/вс) с малыми оборотами в норму не берём
    dates = sorted({str(r["begin"])[:10] for r in rows if dt.date.fromisoformat(str(r["begin"])[:10]).weekday() < 5})
    today = msk_now().strftime("%Y-%m-%d")
    if msk_now().strftime("%H:%M") < "23:55":
        dates = [d for d in dates if d < today]
    return dates[-n:]


def update_profile(universe):
    prof = load_json(PROFILE, {"days": [], "data": {}})
    want = trading_dates(V["norm_days"] + 2)
    missing = [d for d in want if d not in prof["days"]]
    for d in missing:
        print("профиль: загружаю", d, file=sys.stderr)
        by = day_bars(d)
        for t, bars in by.items():
            if t in universe and bars:
                prof["data"].setdefault(t, {})[d] = summarize(bars)
        prof["days"].append(d)
    prof["days"] = sorted(d for d in set(prof["days"]) if dt.date.fromisoformat(d).weekday() < 5)[-(V["norm_days"] + 5):]
    keep = set(prof["days"])
    for t in list(prof["data"]):
        prof["data"][t] = {d: v for d, v in prof["data"][t].items() if d in keep}
        if not prof["data"][t]:
            del prof["data"][t]
    save_json(PROFILE, prof, indent=None)
    return prof


def norm_at(prof, t, slot):
    days = sorted(prof["data"].get(t, {}))[-V["norm_days"]:]
    vals = [prof["data"][t][d]["cum"][slot] for d in days]
    vals = [v for v in vals if v > 0]
    if len(vals) < V["min_days"]:
        return None
    return statistics.median(vals)


def daily_norm(prof, t, before=None):
    days = [d for d in sorted(prof["data"].get(t, {})) if before is None or d < before][-V["norm_days"]:]
    vals = [prof["data"][t][d]["val"] for d in days if prof["data"][t][d]["val"] > 0]
    return statistics.median(vals) if len(vals) >= V["min_days"] else None


def netflow(prof, t, today=None):
    """Нетто-поток (покупатели − продавцы) за дни профиля + сегодня, млн ₽."""
    d = prof["data"].get(t, {})
    s = sum(d[k]["vb"] - d[k]["vs"] for k in sorted(d)[-V["norm_days"]:])
    if today:
        s += today["vb"] - today["vs"]
    return round(s / 1e6, 1)


# ---------------- журнал ----------------
def pnl(side, entry, px):
    return round(((px / entry - 1) if side == "buy" else (1 - px / entry)) * 100, 2)


def close_sig(s, status, px, when, days=None):
    s.update(status=status, closed=when[:10], closed_at=when, close_price=round(px, 6),
             result_pct=pnl(s["side"], s["entry"], px))
    if days is not None:
        s["days"] = days


def stats(sigs):
    closed = [s for s in sigs if s["status"] != "открыт"]
    out = {"total": len(sigs), "open": len(sigs) - len(closed), "closed": len(closed)}
    if closed:
        out.update(win_rate=round(sum(s["result_pct"] > 0 for s in closed) / len(closed) * 100, 1),
                   avg_result=round(sum(s["result_pct"] for s in closed) / len(closed), 2),
                   sum_result=round(sum(s["result_pct"] for s in closed), 2))
        for st in ("стоп", "трейлинг", "объём против", "истёк"):
            out[st] = sum(s["status"] == st for s in closed)
    return out


def check_intraday(s, bars, after):
    """Стоп по 5-минутным свечам сегодняшнего дня, начавшимся не раньше времени `after` (HH:MM)."""
    for b in bars:
        if b["tradetime"][:5] < after:
            continue
        if (s["side"] == "buy" and b["pr_low"] <= s["stop"]) or (s["side"] == "sell" and b["pr_high"] >= s["stop"]):
            close_sig(s, "трейлинг" if s.get("trailing") else "стоп", s["stop"], f"{b['tradedate']} {b['tradetime'][:5]}")
            return True
    return False


def daily_step(s, d, day, prof):
    """Один закрытый день для открытой сделки (ночью)."""
    if s["status"] != "открыт" or d <= s.get("processed", s["opened"]):
        return
    s["processed"] = d
    if d > s["opened"]:
        s["days"] = s.get("days", 0) + 1
        buy = s["side"] == "buy"
        # стоп за день (если не поймали днём)
        if (buy and day["l"] <= s["stop"]) or (not buy and day["h"] >= s["stop"]):
            close_sig(s, "трейлинг" if s.get("trailing") else "стоп", s["stop"], d)
            return
    s["best_close"] = max(s.get("best_close", s["entry"]), day["c"]) if s["side"] == "buy" else min(s.get("best_close", s["entry"]), day["c"])
    s["last_price"], s["last_date"] = day["c"], d
    s["current_pct"] = pnl(s["side"], s["entry"], day["c"])
    if d == s["opened"]:
        return
    # объём против позиции
    dn = daily_norm(prof, s["ticker"], before=d)
    tot = day["vb"] + day["vs"]
    if dn and tot:
        against = (day["vs"] if s["side"] == "buy" else day["vb"]) / tot
        moved_against = day["c"] < day["o"] if s["side"] == "buy" else day["c"] > day["o"]
        if day["val"] >= V["against_ratio"] * dn and against >= V["against_share"] and moved_against:
            close_sig(s, "объём против", day["c"], d)
            return
    if s["days"] >= V["max_days"]:
        close_sig(s, "истёк", day["c"], d)
        return
    if s["days"] >= V["trail_from"]:
        if s["side"] == "buy":
            ns = s["best_close"] * (1 - V["trail"])
            if ns > s["stop"]:
                s["stop"], s["trailing"] = round(ns, 6), True
        else:
            ns = s["best_close"] * (1 + V["trail"])
            if ns < s["stop"]:
                s["stop"], s["trailing"] = round(ns, 6), True


# ---------------- режимы ----------------
def intraday():
    now = msk_now()
    today = now.strftime("%Y-%m-%d")
    prof = load_json(PROFILE, {"days": [], "data": {}})
    if not prof["days"]:
        print("Профиль объёмов пуст — сначала нужен ночной режим.", file=sys.stderr)
    universe = shares()
    by = day_bars(today)
    md = {r["SECID"]: r for r in table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
          {"iss.only": "marketdata", "marketdata.columns": "SECID,LAST,OPEN,HIGH,LOW,LASTTOPREVPRICE,VALTODAY,UPDATETIME"}), "marketdata")}
    names = {}
    try:
        names = {k: v[0] for k, v in load_json(ROOT / "docs" / "data" / "companies.json", {}).items()}
    except Exception:  # noqa
        pass

    prev = load_json(OUT, {})
    first_seen = {x["ticker"]: x for x in prev.get("signals", [])} if prev.get("date") == today else {}
    anomalies = []
    for t, bars in by.items():
        if t not in universe or not bars:
            continue
        m = md.get(t, {})
        last = m.get("LAST") or bars[-1]["pr_close"]
        if not last:
            continue
        sm = summarize(bars)
        slot = slot_of(bars[-1]["tradetime"])
        nm = norm_at(prof, t, slot)
        if not nm:
            continue
        ratio = sm["cum"][slot] / nm if nm else 0
        value = (m.get("VALTODAY") or sm["val"]) / 1e6
        if ratio < V["ratio"] or value < V["min_value_mln"]:
            continue
        tot = sm["vb"] + sm["vs"]
        share = sm["vb"] / tot if tot else 0.5
        hi, lo = m.get("HIGH") or sm["h"], m.get("LOW") or sm["l"]
        pos = (last - lo) / (hi - lo) if hi and lo and hi > lo else 0.5
        chg = m.get("LASTTOPREVPRICE")
        if chg is None:
            pc = prof["data"].get(t, {})
            pcd = sorted(pc)[-1] if pc else None
            chg = (last / pc[pcd]["c"] - 1) * 100 if pcd else 0
        side = None
        if share >= V["buy_share"] and chg >= V["min_change"] and pos >= V["range_pos"]:
            side = "buy"
        elif share <= V["sell_share"] and chg <= -V["min_change"] and pos <= 1 - V["range_pos"]:
            side = "sell"
        anomalies.append({
            "ticker": t, "name": names.get(t) or universe.get(t, t), "side": side,
            "ratio": round(ratio, 1), "buy_share": round(share * 100), "change_pct": round(chg, 2),
            "range_pos": round(pos * 100), "price": last, "value_mln": round(value, 1),
            "net_today_mln": round((sm["vb"] - sm["vs"]) / 1e6, 1), "net30_mln": netflow(prof, t, sm),
            "day_high": hi, "day_low": lo, "time": bars[-1]["tradetime"][:5],
            "updated": str(m.get("UPDATETIME") or "")[:5],
        })
    anomalies.sort(key=lambda x: x["ratio"], reverse=True)

    # сигналы дня: фиксируем первое появление, дальше обновляем показатели
    for a in anomalies:
        if a["side"] and a["ticker"] not in first_seen:
            first_seen[a["ticker"]] = {**a, "first_time": now.strftime("%H:%M"), "first_price": a["price"],
                                       "first_ratio": a["ratio"]}
        elif a["ticker"] in first_seen:
            first_seen[a["ticker"]].update({k: a[k] for k in ("ratio", "buy_share", "change_pct", "price", "value_mln",
                                                              "net_today_mln", "net30_mln", "day_high", "day_low", "time", "range_pos")})
    signals = sorted(first_seen.values(), key=lambda x: x["first_time"])

    # журнал
    j = load_json(JOURNAL, {"signals": []})
    sigs = j["signals"]
    for s in sigs:
        if s["status"] == "открыт" and s["ticker"] in by:
            after = s["opened_at"][11:16] if s["opened"] == today else "00:00"
            if not check_intraday(s, by[s["ticker"]], after):
                lp = (md.get(s["ticker"], {}) or {}).get("LAST")
                if lp:
                    s["last_price"], s["last_date"], s["current_pct"] = lp, today, pnl(s["side"], s["entry"], lp)
    open_t = {s["ticker"] for s in sigs if s["status"] == "открыт"}
    for x in signals:
        t = x["ticker"]
        if t in open_t:
            continue
        if any(s["ticker"] == t and s["side"] == x["side"] and s["status"] in ("стоп",) and
               (dt.date.fromisoformat(today) - dt.date.fromisoformat(s["closed"])).days < V["cooldown"] for s in sigs):
            continue
        if any(s["ticker"] == t and s["opened"] == today for s in sigs):
            continue
        e = x["first_price"]
        if x["side"] == "buy":
            stop = x["day_low"] * (1 - V["stop_pad"])
            stop = min(stop, e * (1 - V["min_stop"]))
            stop = max(stop, e * (1 - V["max_stop"]))
        else:
            stop = x["day_high"] * (1 + V["stop_pad"])
            stop = max(stop, e * (1 + V["min_stop"]))
            stop = min(stop, e * (1 + V["max_stop"]))
        sigs.append({
            "id": f"{today}-{t}-{x['side']}-volume", "strategy": "volume", "ticker": t, "name": x["name"], "side": x["side"],
            "opened": today, "opened_at": f"{today} {x['first_time']}", "entry": e, "stop": round(stop, 6),
            "stop_pct": round(-abs(stop / e - 1) * 100, 1), "target": None,
            "ratio": x["first_ratio"], "buy_share": x["buy_share"], "change_pct": x["change_pct"],
            "comment": f"Объём ×{x['first_ratio']} нормы, покупатели {x['buy_share']}%",
            "status": "открыт", "days": 0, "processed": today if False else None,
            "last_price": e, "last_date": today, "current_pct": 0.0,
        })
        sigs[-1].pop("processed")
        open_t.add(t)
    j["signals"], j["stats"], j["params"] = sigs, stats(sigs), V
    j["updated"] = now.strftime("%Y-%m-%d %H:%M")
    save_json(JOURNAL, j)
    save_json(OUT, {"date": today, "updated": now.strftime("%Y-%m-%d %H:%M"), "source": "AlgoPack tradestats",
                    "params": V, "norm_days": len(prof["days"]), "signals": signals, "anomalies": anomalies})
    print(f"Объёмы {now:%H:%M}: бумаг {len(by)}, аномалий {len(anomalies)}, сигналов {len(signals)}, "
          f"открыто сделок {sum(s['status'] == 'открыт' for s in sigs)}")


def nightly():
    universe = shares()
    prof = update_profile(universe)
    j = load_json(JOURNAL, {"signals": []})
    for s in j["signals"]:
        days = sorted(d for d in prof["data"].get(s["ticker"], {}) if d >= s["opened"])
        for d in days:
            daily_step(s, d, prof["data"][s["ticker"]][d], prof)
    j["stats"], j["params"] = stats(j["signals"]), V
    j["updated"] = msk_now().strftime("%Y-%m-%d %H:%M")
    save_json(JOURNAL, j)
    print(f"Профиль: {len(prof['days'])} дней ({prof['days'][0] if prof['days'] else '-'} … "
          f"{prof['days'][-1] if prof['days'] else '-'}), бумаг {len(prof['data'])}. Журнал: {j['stats']}")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Нужен ключ AlgoPack: секрет MOEX_TOKEN")
    {"intraday": intraday, "nightly": nightly}[sys.argv[1] if len(sys.argv) > 1 else "intraday"]()
