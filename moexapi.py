"""Общий доступ к API Мосбиржи: ISS (публичный, задержка 15 мин) или AlgoPack (apim.moex.com, с ключом MOEX_TOKEN, без задержки).

Сервер apim.moex.com подписан российским корневым сертификатом (Минцифры), поэтому к стандартному
набору сертификатов добавляются файлы из папки certs/.
"""
import os
import time
from pathlib import Path

import certifi
import requests

TOKEN = os.environ.get("MOEX_TOKEN", "").strip()
BASE = "https://apim.moex.com/iss" if TOKEN else "https://iss.moex.com/iss"


def _bundle():
    out = Path(__file__).parent / ".ca-bundle.pem"
    if not out.exists():
        parts = [Path(certifi.where()).read_text()]
        for f in sorted((Path(__file__).parent / "certs").glob("*.pem")):
            parts.append(f.read_text())
        out.write_text("\n".join(parts))
    return str(out)


S = requests.Session()
S.headers["User-Agent"] = "ip-screener/1.0"
if TOKEN:
    S.headers["Authorization"] = f"Bearer {TOKEN}"
    S.verify = _bundle()


def iss(path, params=None, tries=4):
    params = dict(params or {})
    params.setdefault("iss.meta", "off")
    for attempt in range(tries):
        try:
            r = S.get(f"{BASE}/{path.lstrip('/')}", params=params, timeout=(10, 30))
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def table(js, name):
    t = js.get(name, {})
    cols = t.get("columns", [])
    return [dict(zip(cols, row)) for row in t.get("data", [])]


def paged(path, params, name="data", page=1000):
    """Все страницы ответа datashop (курсор data.cursor)."""
    out, start = [], 0
    while True:
        js = iss(path, {**params, "start": start})
        rows = table(js, name)
        out.extend(rows)
        cur = table(js, f"{name}.cursor")
        total = cur[0]["TOTAL"] if cur else len(rows)
        start += len(rows)
        if not rows or start >= total:
            break
    return out
