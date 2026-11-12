"""Ручное закрытие позиций с сайта.

Сайт (в режиме владельца) дописывает запись в docs/data/manual.json:
  {"closes": [{"section": "ta|volume|oi|mx", "id": "<id сигнала>", "price": 123.4, "time": "2026-11-12 15:40", "note": ""}]}
Сканеры при каждом запуске закрывают такие сигналы со статусом «вручную» по указанной цене.
"""
import json
from pathlib import Path

PATH = Path(__file__).parent / "docs" / "data" / "manual.json"


def closes(section):
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return {}
    return {c["id"]: c for c in data.get("closes", []) if c.get("section") == section and c.get("id")}


def apply(sigs, section):
    cl = closes(section)
    n = 0
    for s in sigs:
        c = cl.get(s.get("id"))
        if not c or s.get("status") not in ("открыт", "ждёт входа"):
            continue
        when = c.get("time") or ""
        if s["status"] == "ждёт входа" or not s.get("entry"):
            s.update(status="отменён", closed=when[:10], closed_at=when, close_price=None, result_pct=0.0)
        else:
            px = float(c.get("price") or s.get("last_price") or s["entry"])
            e = s["entry"]
            res = round(((px / e - 1) if s["side"] == "buy" else (1 - px / e)) * 100, 2)
            s.update(status="вручную", closed=when[:10], closed_at=when, close_price=px, result_pct=res)
        if c.get("note"):
            s["close_note"] = c["note"]
        n += 1
    return n
