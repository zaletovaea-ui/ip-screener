#!/usr/bin/env python3
"""
Технический скринер акций Мосбиржи (дневной таймфрейм).

Сигналы по инструкции проекта «MCP ФИНАМ»:
  Покупка: поддержка, EMA200, пробой сопротивления, RSI (выход из перепроданности / бычья дивергенция)
  Продажа: сопротивление, EMA200 вниз, пробой поддержки, RSI (выход из перекупленности / медвежья дивергенция)

Данные: публичный ISS Мосбиржи (ключ не нужен). Если задан MOEX_TOKEN,
запросы идут через apis.moex.com (AlgoPack) с этим ключом.

Результат: results/latest.json, results/latest.md, results/YYYY-MM-DD.json
"""
import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

import requests

# ---------------- Параметры (можно менять под стратегию) ----------------
P = {
    "history_days": 560,          # календарных дней истории (≈ 380 торговых, хватает на EMA200)
    "level_lookback": 250,        # окно поиска уровней, торговых дней (≈ 12 мес.)
    "pivot_window": 5,            # свечей слева и справа для локального экстремума
    "level_tolerance": 0.015,     # касания в пределах 1.5% объединяются в один уровень
    "min_touches": 2,             # минимум касаний для уровня
    "near_level": 0.02,           # цена в пределах 2% от уровня
    "near_ema": 0.015,            # цена в пределах ±1.5% от EMA200
    "ema_slope_days": 20,         # наклон EMA200 сравниваем с её значением N дней назад
    "breakout_pct": 0.01,         # закрытие за уровнем на 1%+
    "breakout_recent": 5,         # пробой учитываем, если он был за последние N дней
    "volume_mult": 1.5,           # объём в день пробоя ≥ 1.5× средний за 20 дней
    "rsi_period": 14,
    "rsi_low": 30,
    "rsi_high": 70,
    "rsi_cross_recent": 3,        # пересечение 30/70 за последние N дней
    "div_lookback": 60,           # окно поиска дивергенций
    "div_recent": 10,             # второй экстремум дивергенции не старше N дней
    "min_turnover_mln": 50,       # ниже — предупреждение о ликвидности, млн ₽ в день
}

UNIVERSE_FALLBACK = [
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "GMKN", "PLZL", "TATN", "SNGS", "SNGSP",
    "YDEX", "T", "VTBR", "MGNT", "CHMF", "NLMK", "MAGN", "ALRS", "MTSS", "PHOR",
    "IRAO", "HYDR", "FEES", "RUAL", "AFKS", "MOEX", "OZON", "X5", "PIKK", "SMLT",
    "AFLT", "TRNFP", "SBERP", "TATNP", "CBOM", "BSPB", "ENPG", "HEAD", "VKCO", "POSI",
    "ASTR", "UPRO", "LEAS", "SVCB", "UGLD", "MTLR", "RTKM", "SELG", "FLOT", "GAZP",
]

TOKEN = os.environ.get("MOEX_TOKEN", "").strip()
BASE = "https://apis.moex.com/iss" if TOKEN else "https://iss.moex.com/iss"
S = requests.Session()
if TOKEN:
    S.headers["Authorization"] = f"Bearer {TOKEN}"
S.headers["User-Agent"] = "ip-screener/1.0"


def iss(path, params=None):
    params = dict(params or {})
    params.setdefault("iss.meta", "off")
    for attempt in range(4):
        try:
            r = S.get(f"{BASE}/{path}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def table(js, name):
    t = js.get(name, {})
    cols = t.get("columns", [])
    return [dict(zip(cols, row)) for row in t.get("data", [])]


# ---------------- Загрузка данных ----------------
def load_universe():
    try:
        rows = table(iss("statistics/engines/stock/markets/index/analytics/IMOEX.json",
                         {"limit": 100}), "analytics")
        tickers = [r.get("ticker") or r.get("secids") for r in rows]
        tickers = [t for t in tickers if t]
        if len(tickers) >= 20:
            return list(dict.fromkeys(tickers))
    except Exception as e:  # noqa
        print("Состав индекса не загрузился, беру запасной список:", e, file=sys.stderr)
    return list(dict.fromkeys(UNIVERSE_FALLBACK))


def load_names(tickers):
    names = {}
    try:
        rows = table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
                         {"iss.only": "securities", "securities.columns": "SECID,SHORTNAME"}),
                     "securities")
        names = {r["SECID"]: r["SHORTNAME"] for r in rows}
    except Exception:  # noqa
        pass
    return {t: names.get(t, t) for t in tickers}


def load_candles(path):
    frm = (dt.date.today() - dt.timedelta(days=P["history_days"])).isoformat()
    out, start = [], 0
    while True:
        rows = table(iss(path, {"interval": 24, "from": frm, "start": start}), "candles")
        if not rows:
            break
        out.extend(rows)
        start += len(rows)
        if len(rows) < 500:
            break
    bars = []
    for r in out:
        if r.get("close") is None:
            continue
        bars.append({
            "date": str(r["begin"])[:10],
            "o": float(r["open"]), "h": float(r["high"]),
            "l": float(r["low"]), "c": float(r["close"]),
            "v": float(r.get("volume") or 0), "val": float(r.get("value") or 0),
        })
    return bars


# ---------------- Индикаторы ----------------
def ema(vals, n):
    if len(vals) < n:
        return [None] * len(vals)
    k = 2 / (n + 1)
    out = [None] * (n - 1)
    e = sum(vals[:n]) / n
    out.append(e)
    for v in vals[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(vals, n=14):
    out = [None] * len(vals)
    if len(vals) <= n:
        return out
    gains = [max(vals[i] - vals[i - 1], 0) for i in range(1, len(vals))]
    losses = [max(vals[i - 1] - vals[i], 0) for i in range(1, len(vals))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(vals)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def pivots(bars, key, kind, w, end=None):
    """Индексы локальных минимумов (kind='low') или максимумов ('high')."""
    end = len(bars) if end is None else end
    res = []
    for i in range(w, end - w):
        x = bars[i][key]
        win = [bars[j][key] for j in range(i - w, i + w + 1)]
        hit = (kind == "low" and x == min(win)) or (kind == "high" and x == max(win))
        if hit and (not res or i - res[-1] > w):  # плоское дно/вершина = одно касание
            res.append(i)
    return res


def touches(n):
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} касание"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} касания"
    return f"{n} касаний"


def cluster_levels(bars, idxs, key):
    """Объединяет экстремумы, лежащие в пределах tolerance, в уровни с числом касаний."""
    pts = sorted((bars[i][key], i) for i in idxs)
    levels, cur = [], []
    for price, i in pts:
        if cur and price > cur[0][0] * (1 + P["level_tolerance"]):
            levels.append(cur)
            cur = []
        cur.append((price, i))
    if cur:
        levels.append(cur)
    out = []
    for grp in levels:
        if len(grp) >= P["min_touches"]:
            out.append({
                "price": sum(p for p, _ in grp) / len(grp),
                "touches": len(grp),
                "last_idx": max(i for _, i in grp),
            })
    return out


def find_levels(bars, end=None):
    end = len(bars) if end is None else end
    start = max(0, end - P["level_lookback"])
    sub = bars[start:end]
    w = P["pivot_window"]
    sup = cluster_levels(sub, pivots(sub, "l", "low", w), "l")
    res = cluster_levels(sub, pivots(sub, "h", "high", w), "h")
    for lv in sup + res:
        lv["last_idx"] += start
    return sup, res


# ---------------- Свечные модели ----------------
def is_hammer(b):
    body = abs(b["c"] - b["o"])
    rng = b["h"] - b["l"]
    if rng <= 0:
        return False
    lower = min(b["o"], b["c"]) - b["l"]
    upper = b["h"] - max(b["o"], b["c"])
    return lower >= 2 * max(body, rng * 0.05) and upper <= rng * 0.25


def is_shooting_star(b):
    body = abs(b["c"] - b["o"])
    rng = b["h"] - b["l"]
    if rng <= 0:
        return False
    lower = min(b["o"], b["c"]) - b["l"]
    upper = b["h"] - max(b["o"], b["c"])
    return upper >= 2 * max(body, rng * 0.05) and lower <= rng * 0.25


def bull_engulf(p, b):
    return p["c"] < p["o"] and b["c"] > b["o"] and b["c"] >= p["o"] and b["o"] <= p["c"]


def bear_engulf(p, b):
    return p["c"] > p["o"] and b["c"] < b["o"] and b["c"] <= p["o"] and b["o"] >= p["c"]


def reversal_candle(bars, side):
    if len(bars) < 2:
        return None
    p, b = bars[-2], bars[-1]
    if side == "buy":
        if bull_engulf(p, b):
            return "бычье поглощение"
        if is_hammer(b):
            return "молот"
    else:
        if bear_engulf(p, b):
            return "медвежье поглощение"
        if is_shooting_star(b):
            return "падающая звезда"
    return None


# ---------------- Сигналы ----------------
def divergence(bars, rs, side):
    n = len(bars)
    lo = max(P["rsi_period"] + 1, n - P["div_lookback"])
    w = 3
    if side == "buy":
        idx = [i for i in pivots(bars, "l", "low", w, end=n) if i >= lo]
        # последний бар тоже может быть минимумом (правой стороны ещё нет)
        if n - 1 - w >= 0 and bars[-1]["l"] <= min(b["l"] for b in bars[-w - 1:]):
            idx.append(n - 1)
        if len(idx) >= 2:
            a, b = idx[-2], idx[-1]
            if (n - 1 - b) <= P["div_recent"] and bars[b]["l"] < bars[a]["l"] \
                    and rs[a] is not None and rs[b] is not None and rs[b] > rs[a] and rs[a] < 40:
                return f"бычья дивергенция ({bars[a]['date']} → {bars[b]['date']})"
    else:
        idx = [i for i in pivots(bars, "h", "high", w, end=n) if i >= lo]
        if bars[-1]["h"] >= max(b["h"] for b in bars[-w - 1:]):
            idx.append(n - 1)
        if len(idx) >= 2:
            a, b = idx[-2], idx[-1]
            if (n - 1 - b) <= P["div_recent"] and bars[b]["h"] > bars[a]["h"] \
                    and rs[a] is not None and rs[b] is not None and rs[b] < rs[a] and rs[a] > 60:
                return f"медвежья дивергенция ({bars[a]['date']} → {bars[b]['date']})"
    return None


def analyze(ticker, name, bars):
    if len(bars) < 230:
        return None
    closes = [b["c"] for b in bars]
    e200 = ema(closes, 200)
    rs = rsi(closes, P["rsi_period"])
    last = bars[-1]
    c = last["c"]
    sup, res = find_levels(bars, end=len(bars) - 1)  # уровни строим без последней свечи
    vol20 = [sum(b["v"] for b in bars[i - 20:i]) / 20 if i >= 20 else None for i in range(len(bars))]
    turnover = sum(b["val"] for b in bars[-20:]) / 20 / 1e6

    out = {"buy": [], "sell": []}
    notes = {"buy": [], "sell": []}
    used_levels = {"buy": None, "sell": None}

    # 1. Поддержка / сопротивление
    for lv in sorted(sup, key=lambda x: -x["price"]):
        L = lv["price"]
        if c >= L and (c - L) / L <= P["near_level"]:
            txt = f"на поддержке {L:.2f} ({touches(lv['touches'])}, до уровня {(c - L) / L * 100:.1f}%)"
            cnd = reversal_candle(bars, "buy")
            if cnd:
                txt += f", свеча разворота: {cnd}"
            out["buy"].append(txt)
            used_levels["buy"] = L
            break
    for lv in sorted(res, key=lambda x: x["price"]):
        L = lv["price"]
        if c <= L and (L - c) / L <= P["near_level"]:
            txt = f"у сопротивления {L:.2f} ({touches(lv['touches'])}, до уровня {(L - c) / L * 100:.1f}%)"
            cnd = reversal_candle(bars, "sell")
            if cnd:
                txt += f", свеча разворота: {cnd}"
            out["sell"].append(txt)
            used_levels["sell"] = L
            break

    # 2. EMA200
    E = e200[-1]
    Eprev = e200[-1 - P["ema_slope_days"]]
    slope_up = E is not None and Eprev is not None and E > Eprev
    if E:
        dist = (c - E) / E
        if 0 <= dist <= P["near_ema"]:
            out["buy"].append(f"откат к EMA200 {E:.2f} (+{dist * 100:.1f}%), наклон "
                              + ("вверх — откат в восходящем тренде" if slope_up else "вниз — слабее"))
        # закрепление ниже: 2+ последних закрытия ниже EMA200, а 10 дней назад было выше
        below = 0
        for k in range(1, 6):
            if e200[-k] and bars[-k]["c"] < e200[-k]:
                below += 1
            else:
                break
        was_above = any(e200[-k] and bars[-k]["c"] > e200[-k] for k in range(below + 1, 11))
        if 2 <= below <= 5 and was_above:
            out["sell"].append(f"пробой EMA200 {E:.2f} вниз, {below} закрытия ниже")
        elif not slope_up and c < E and last["h"] >= E * (1 - P["near_ema"]):
            out["sell"].append(f"отскок вниз от EMA200 {E:.2f} при нисходящем наклоне")

    # 3. Пробои за последние N дней
    n = len(bars)
    for k in range(n - P["breakout_recent"], n):
        if k < 21:
            continue
        s_k, r_k = find_levels(bars, end=k)
        b, prev = bars[k], bars[k - 1]
        vm = b["v"] / vol20[k] if vol20[k] else 0
        for lv in r_k:
            R = lv["price"]
            if prev["c"] <= R * (1 + P["breakout_pct"]) and b["c"] >= R * (1 + P["breakout_pct"]) \
                    and vm >= P["volume_mult"] and c > R:
                retest = any(bars[j]["l"] <= R * 1.01 for j in range(k + 1, n))
                out["buy"].append(f"пробой сопротивления {R:.2f} {b['date']} на объёме ×{vm:.1f}"
                                  + (", был ретест уровня" if retest else ""))
                used_levels["buy"] = used_levels["buy"] or R
                break
        for lv in s_k:
            Sv = lv["price"]
            if prev["c"] >= Sv * (1 - P["breakout_pct"]) and b["c"] <= Sv * (1 - P["breakout_pct"]) \
                    and vm >= P["volume_mult"] and c < Sv:
                out["sell"].append(f"пробой поддержки {Sv:.2f} {b['date']} на объёме ×{vm:.1f}")
                used_levels["sell"] = used_levels["sell"] or Sv
                break

    # 4. RSI
    r_now = rs[-1]
    rc = P["rsi_cross_recent"]
    for k in range(n - rc, n):
        if rs[k - 1] is not None and rs[k] is not None:
            if rs[k - 1] < P["rsi_low"] <= rs[k]:
                out["buy"].append(f"RSI вышел из перепроданности ({rs[k - 1]:.0f} → {rs[k]:.0f}, {bars[k]['date']})")
                break
    for k in range(n - rc, n):
        if rs[k - 1] is not None and rs[k] is not None:
            if rs[k - 1] > P["rsi_high"] >= rs[k]:
                out["sell"].append(f"RSI вышел из перекупленности ({rs[k - 1]:.0f} → {rs[k]:.0f}, {bars[k]['date']})")
                break
    d = divergence(bars, rs, "buy")
    if d:
        out["buy"].append(d)
    d = divergence(bars, rs, "sell")
    if d:
        out["sell"].append(d)

    # ---- выбор направления и план сделки ----
    results = []
    all_sup = sorted([lv["price"] for lv in sup])
    all_res = sorted([lv["price"] for lv in res])
    low20 = min(b["l"] for b in bars[-20:])
    high20 = max(b["h"] for b in bars[-20:])
    hi52 = max(b["h"] for b in bars[-250:])
    lo52 = min(b["l"] for b in bars[-250:])
    for side in ("buy", "sell"):
        sig = out[side]
        if not sig:
            continue
        if side == "buy":
            entry = c
            base = used_levels["buy"] or max([s for s in all_sup if s <= c], default=low20)
            stop = min(base, low20 if base > c else base) * 0.99
            if E and E < c and (c - E) / E <= P["near_ema"] and not used_levels["buy"]:
                stop = min(stop, E * 0.985)
            target = min([r for r in all_res if r > c], default=hi52 if hi52 > c * 1.01 else None)
            if target is None:
                target = c + 2 * (c - stop)
                tnote = "цель расчётная (2× риск), выше нет уровней"
            else:
                tnote = ""
            risk, reward = c - stop, target - c
        else:
            entry = c
            base = used_levels["sell"] or min([r for r in all_res if r >= c], default=high20)
            stop = max(base, high20 if base < c else base) * 1.01
            target = max([s for s in all_sup if s < c], default=lo52 if lo52 < c * 0.99 else None)
            if target is None:
                target = c - 2 * (stop - c)
                tnote = "цель расчётная (2× риск), ниже нет уровней"
            else:
                tnote = ""
            risk, reward = stop - c, c - target
        rr = reward / risk if risk > 0 else None
        cnt = len(sig)
        results.append({
            "ticker": ticker, "name": name, "side": side,
            "signals": sig, "count": cnt,
            "rating": "⭐" * min(cnt, 3),
            "rating_label": "сильный сетап" if cnt >= 3 else ("интересно" if cnt == 2 else "на радар"),
            "date": last["date"], "close": round(c, 4),
            "entry": round(entry, 4), "stop": round(stop, 4), "target": round(target, 4),
            "rr": round(rr, 2) if rr else None, "target_note": tnote,
            "ema200": round(E, 4) if E else None, "ema200_slope_up": slope_up,
            "rsi": round(r_now, 1) if r_now else None,
            "turnover_mln": round(turnover, 1),
            "low_liquidity": turnover < P["min_turnover_mln"],
            "supports": [round(x, 2) for x in all_sup if x < c][-3:],
            "resistances": [round(x, 2) for x in all_res if x > c][:3],
        })
    return results


def market_background():
    try:
        bars = load_candles("engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json")
        closes = [b["c"] for b in bars]
        e = ema(closes, 200)
        if e[-1] is None:
            return None
        return {"date": bars[-1]["date"], "close": round(closes[-1], 2), "ema200": round(e[-1], 2),
                "above": closes[-1] > e[-1], "dist_pct": round((closes[-1] / e[-1] - 1) * 100, 1),
                "slope_up": e[-1] > e[-21]}
    except Exception as ex:  # noqa
        print("Индекс не загрузился:", ex, file=sys.stderr)
        return None


def rank_key(x):
    return (x["count"], (x["rr"] or 0), not x["low_liquidity"])


def to_md(report):
    lines = [f"# Скан акций Мосбиржи — {report['asof']}", ""]
    m = report["market"]
    if m:
        lines.append(f"**Фон рынка:** индекс Мосбиржи {m['close']} — "
                     + ("выше" if m["above"] else "ниже")
                     + f" EMA200 ({m['ema200']}, {m['dist_pct']:+.1f}%), наклон EMA200 "
                     + ("вверх" if m["slope_up"] else "вниз") + ".")
        lines.append("")
    for side, title in (("buy", "Покупка"), ("sell", "Продажа")):
        rows = [r for r in report["results"] if r["side"] == side]
        lines += [f"## {title} ({len(rows)})", "",
                  "| Тикер | Компания | Сигналы | Рейтинг | Цена | Вход | Стоп | Цель | R/R |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['ticker']} | {r['name']} | {r['count']} | {r['rating']} | {r['close']} | "
                         f"{r['entry']} | {r['stop']} | {r['target']} | {r['rr']} |")
        lines.append("")
        for r in rows:
            lines.append(f"**{r['ticker']}** — " + "; ".join(r["signals"])
                         + (" ⚠️ низкая ликвидность" if r["low_liquidity"] else ""))
        lines.append("")
    lines.append("Не является индивидуальной инвестиционной рекомендацией.")
    return "\n".join(lines)


def main():
    tickers = load_universe()
    names = load_names(tickers)
    results, errors = [], {}
    for t in tickers:
        try:
            bars = load_candles(f"engines/stock/markets/shares/boards/TQBR/securities/{t}/candles.json")
            r = analyze(t, names.get(t, t), bars)
            if r:
                results.extend(r)
        except Exception as e:  # noqa
            errors[t] = str(e)[:200]
        time.sleep(0.15)
    results.sort(key=rank_key, reverse=True)
    report = {
        "asof": max((r["date"] for r in results), default=dt.date.today().isoformat()),
        "generated_utc": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "source": "apis.moex.com (AlgoPack)" if TOKEN else "iss.moex.com",
        "universe": tickers, "params": P, "market": market_background(),
        "results": results, "errors": errors,
    }
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    js = json.dumps(report, ensure_ascii=False, indent=1)
    (out / "latest.json").write_text(js, encoding="utf-8")
    (out / f"{report['asof']}.json").write_text(js, encoding="utf-8")
    (out / "latest.md").write_text(to_md(report), encoding="utf-8")
    print(f"Готово: {len(tickers)} бумаг, сигналов {len(results)}, ошибок {len(errors)}")


if __name__ == "__main__":
    main()
