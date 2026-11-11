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
    "max_drawdown": 0.50,         # покупки: если цена ниже годового максимума больше чем на 50% — «падающий нож», в подборку не берём
    "max_target": 0.20,           # цель не дальше ±20% от цены: дальше — уже не сделка на 20 дней
    "mom_change": 0.05,           # моментум: рост за день от 5%
    "mom_quiet_days": 20,         # «первый день»: до этого N дней без роста ≥5%
    "mom_volume_mult": 1.5,       # объём в день импульса ≥ 1.5× средний за 20 дней
    "mom_rr": 2.0,                # цель моментума = вход + 2 × риск
    "min_turnover_mln": 50,       # акции вне индекса с оборотом ниже не анализируем, млн ₽ в день (средний за 20 дней)
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
            r = S.get(f"{BASE}/{path}", params=params, timeout=(10, 20))
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
def load_index():
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


LISTLEVEL = {}


def load_exclude():
    f = Path(__file__).parent / "exclude.txt"
    if not f.exists():
        return set()
    return {ln.split("#")[0].strip().upper() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.split("#")[0].strip()}


def load_universe():
    """Все акции режима TQBR минус exclude.txt; фильтр по обороту — после загрузки свечей."""
    excl = load_exclude()
    index = [t for t in load_index() if t not in excl]
    try:
        rows = table(iss("engines/stock/markets/shares/boards/TQBR/securities.json",
                         {"iss.only": "securities", "securities.columns": "SECID,LISTLEVEL"}), "securities")
        all_t = [r["SECID"] for r in rows if r.get("SECID") and r["SECID"] not in excl]
        for r in rows:
            if r.get("SECID"):
                LISTLEVEL[r["SECID"]] = r.get("LISTLEVEL")
    except Exception as e:  # noqa
        print("Список акций не загрузился, только индекс:", e, file=sys.stderr)
        all_t = []
    return index, list(dict.fromkeys(index + all_t))


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
            if target > c * (1 + P["max_target"]):
                target = c * (1 + P["max_target"])
                tnote = "цель ограничена +20%, ближайший уровень дальше"
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
            if target < c * (1 - P["max_target"]):
                target = c * (1 - P["max_target"])
                tnote = "цель ограничена −20%, ближайший уровень дальше"
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
            "stop_pct": round(-abs(stop / c - 1) * 100, 1),
            "target_pct": round(abs(target / c - 1) * 100, 1),
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


def short_comment(sig, side):
    """3–5 слов: почему покупка/продажа."""
    parts = []
    for t in sig:
        if t.startswith("на поддержке"):
            parts.append("поддержка")
        elif t.startswith("у сопротивления"):
            parts.append("сопротивление")
        elif t.startswith("откат к EMA200"):
            parts.append("EMA200 ↑" if "вверх" in t else "EMA200")
        elif t.startswith("пробой EMA200") or t.startswith("отскок вниз от EMA200"):
            parts.append("ниже EMA200")
        elif t.startswith("пробой сопротивления"):
            parts.append("пробой на объёме")
        elif t.startswith("пробой поддержки"):
            parts.append("пробой поддержки")
        elif "дивергенция" in t:
            parts.append("дивергенция RSI")
        elif t.startswith("RSI"):
            parts.append("разворот RSI")
        if "свеча разворота" in t:
            parts.append(t.split("свеча разворота: ")[1])
    return " + ".join(dict.fromkeys(parts))


def momentum(ticker, name, bars):
    """Первый за N дней дневной рост ≥ mom_change на повышенном объёме."""
    n = len(bars)
    if n < 25:
        return None
    ch = [None] + [bars[i]["c"] / bars[i - 1]["c"] - 1 for i in range(1, n)]
    last, chg = bars[-1], ch[-1]
    if chg is None or chg < P["mom_change"]:
        return None
    if any(c is not None and c >= P["mom_change"] for c in ch[-1 - P["mom_quiet_days"]:-1]):
        return None
    avgv = sum(b["v"] for b in bars[-21:-1]) / 20
    vm = last["v"] / avgv if avgv else 0
    if vm < P["mom_volume_mult"]:
        return None
    c = last["c"]
    stop = last["l"] * 0.995
    risk = c - stop
    if risk <= 0:
        return None
    target = c + P["mom_rr"] * risk
    turnover = sum(b["val"] for b in bars[-20:]) / 20 / 1e6
    return {
        "ticker": ticker, "name": name, "side": "buy", "strategy": "momentum",
        "signals": [f"рост +{chg * 100:.1f}% за день — первый за {P['mom_quiet_days']} дней, объём ×{vm:.1f}"],
        "count": 1, "rating": "🚀", "rating_label": "моментум",
        "date": last["date"], "close": round(c, 4), "entry": round(c, 4),
        "stop": round(stop, 4), "target": round(target, 4),
        "stop_pct": round(-risk / c * 100, 1), "target_pct": round((target / c - 1) * 100, 1),
        "rr": P["mom_rr"], "target_note": "цель = 2 × риск",
        "change_pct": round(chg * 100, 1), "volume_mult": round(vm, 1),
        "rsi": None, "ema200": None, "turnover_mln": round(turnover, 1), "low_liquidity": False,
        "comment": f"Импульс +{chg * 100:.1f}% на объёме ×{vm:.1f}", "top": True, "conflict": False,
        "supports": [], "resistances": [],
    }


def pick_top(results, n_buy=5, n_sell=3, min_rr=1.0):
    """Топ по инструкции: больше сигналов выше, затем лучший риск/прибыль; R/R < 1 отсекаем."""
    by = {}
    for r in results:
        if r.get("strategy", "ta") == "ta":
            by.setdefault(r["ticker"], {})[r["side"]] = r
    top = []
    for side, n in (("buy", n_buy), ("sell", n_sell)):
        rows = [r for r in results if r["side"] == side and (r["rr"] or 0) >= min_rr
                and not r["low_liquidity"] and r.get("strategy", "ta") == "ta" and not r.get("risk_flags")]
        # конфликт: по бумаге сигналов в другую сторону не меньше — пропускаем
        rows = [r for r in rows if by[r["ticker"]].get("sell" if side == "buy" else "buy", {}).get("count", 0) < r["count"]]
        rows.sort(key=lambda x: (x["count"], min(x["rr"], 3)), reverse=True)
        chosen = []
        for r in rows:
            base = r["ticker"][:-1] if r["ticker"].endswith("P") else r["ticker"]
            if any(c == base or c[:-1] == base for c in chosen):  # обычка/префы — одна бумага
                continue
            chosen.append(r["ticker"])
            if len(chosen) == n:
                break
        top += [t + ":" + side for t in chosen]
    return top


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
        rows = [r for r in report["results"] if r["side"] == side and r.get("strategy", "ta") == "ta"]
        lines += [f"## {title} ({len(rows)})", "",
                  "| Тикер | Компания | Сигналы | Рейтинг | Цена | Вход | Стоп | Стоп, % | Цель | Цель, % | R/R |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['ticker']} | {r['name']} | {r['count']} | {r['rating']} | {r['close']} | "
                         f"{r['entry']} | {r['stop']} | {r['stop_pct']}% | {r['target']} | +{r['target_pct']}% | {r['rr']} |")
        lines.append("")
        for r in rows:
            lines.append(f"**{r['ticker']}** — " + "; ".join(r["signals"])
                         + (" ⚠️ низкая ликвидность" if r["low_liquidity"] else ""))
        lines.append("")
    moms = [r for r in report["results"] if r.get("strategy") == "momentum"]
    lines += [f"## Моментум ({len(moms)})", ""]
    for r in moms:
        lines.append(f"- **{r['ticker']}** {r['name']}: {r['signals'][0]}; вход {r['entry']}, "
                     f"стоп {r['stop']} ({r['stop_pct']}%), цель {r['target']} (+{r['target_pct']}%)")
    lines.append("")
    lines.append("Не является индивидуальной инвестиционной рекомендацией.")
    return "\n".join(lines)


BARS = {}


def main():
    index, candidates = load_universe()
    names = load_names(candidates)
    results, errors, tickers, skipped, moms = [], {}, [], 0, []
    for t in candidates:
        try:
            bars = load_candles(f"engines/stock/markets/shares/boards/TQBR/securities/{t}/candles.json")
            if not bars or bars[-1]["date"] < (dt.date.today() - dt.timedelta(days=10)).isoformat():
                skipped += 1  # бумага не торгуется
                continue
            turnover = sum(b["val"] for b in bars[-20:]) / min(20, len(bars)) / 1e6
            if t not in index and turnover < P["min_turnover_mln"]:
                skipped += 1
                continue
            tickers.append(t)
            BARS[t] = bars
            r = analyze(t, names.get(t, t), bars)
            if r:
                results.extend(r)
            m = momentum(t, names.get(t, t), bars)
            if m:
                moms.append(m)
        except Exception as e:  # noqa
            errors[t] = str(e)[:200]
        time.sleep(0.1)
    results.sort(key=rank_key, reverse=True)
    for r in results + moms:
        flags = []
        bars = BARS.get(r["ticker"], [])
        if LISTLEVEL.get(r["ticker"]) == 3 and r["ticker"] not in index:
            flags.append("3-й уровень листинга")
        if r["side"] == "buy" and bars:
            hi = max(b["h"] for b in bars[-250:])
            dd = 1 - r["close"] / hi
            if dd > P["max_drawdown"]:
                flags.append(f"падающий нож: −{dd * 100:.0f}% от годового максимума")
        if r["side"] == "buy" and r.get("strategy", "ta") == "ta" and all(
                ("RSI" in t or "дивергенция" in t) for t in r["signals"]):
            flags.append("только сигнал RSI — без уровня")
        r["risk_flags"] = flags
        if flags and r.get("strategy") == "momentum":
            r["top"] = False
    for r in results:
        r["strategy"] = "ta"
        r["comment"] = short_comment(r["signals"], r["side"])
        r["conflict"] = any(x["ticker"] == r["ticker"] and x["side"] != r["side"] for x in results)
    top = set(pick_top(results))
    for r in results:
        r["top"] = f"{r['ticker']}:{r['side']}" in top
    moms.sort(key=lambda x: x["change_pct"], reverse=True)
    results += moms
    report = {
        "asof": max((r["date"] for r in results), default=dt.date.today().isoformat()),
        "generated_utc": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "source": "apis.moex.com (AlgoPack)" if TOKEN else "iss.moex.com",
        "universe": tickers, "index": index, "candidates": len(candidates), "params": P, "market": market_background(),
        "results": results, "errors": errors,
    }
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    js = json.dumps(report, ensure_ascii=False, indent=1)
    (out / "latest.json").write_text(js, encoding="utf-8")
    (out / f"{report['asof']}.json").write_text(js, encoding="utf-8")
    (out / "latest.md").write_text(to_md(report), encoding="utf-8")
    import tracker
    tracker.update(report, BARS, load_candles)
    docs = Path(__file__).parent / "docs" / "data"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "latest.json").write_text(js, encoding="utf-8")
    print(f"Готово: проверено {len(candidates)}, в анализе {len(tickers)} (из них индекс {len(index)}), "
          f"отсеяно по обороту {skipped}, сигналов {len(results)}, ошибок {len(errors)}")


if __name__ == "__main__":
    main()
