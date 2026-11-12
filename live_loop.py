#!/usr/bin/env python3
"""Живое обновление в течение дня: каждые 10 минут (07:00–23:50 МСК, пн–пт) — объёмы, ОИ физлиц, MX.
Работает ~5 ч 40 мин, затем workflow перезапускает сам себя. Каждое обновление сразу публикуется (git push)."""
import subprocess
import sys
import time
import datetime as dt

STEP = 600
LIMIT = 5 * 3600 + 40 * 60
start = time.time()


def msk():
    return dt.datetime.utcnow() + dt.timedelta(hours=3)


def trading(now):
    return now.weekday() < 5 and "06:58" <= now.strftime("%H:%M") <= "23:52"


def sh(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(" ".join(cmd), "→", r.returncode, (r.stdout + r.stderr).strip()[-400:], flush=True)
    return r.returncode


from pathlib import Path
MARK = Path("docs/data/nightly_done.txt")


def nightly_due(now):
    """Ночной пересчёт после торгового дня: 00:05–02:00 МСК вт–сб, один раз на дату."""
    if not (now.weekday() in (1, 2, 3, 4, 5) and "00:05" <= now.strftime("%H:%M") <= "02:00"):
        return False
    done = MARK.read_text().strip() if MARK.exists() else ""
    return done != now.strftime("%Y-%m-%d")


def publish(msg):
    sh("git", "add", "-A", "docs/data", "results")
    if sh("git", "commit", "-qm", msg) == 0:
        for _ in range(3):
            if sh("git", "pull", "--rebase", "-X", "theirs", "origin", "main") == 0 and sh("git", "push") == 0:
                break
            time.sleep(5)


while time.time() - start < LIMIT:
    t0 = time.time()
    now = msk()
    if nightly_due(now):
        for script in (["python", "screener.py"], ["python", "volscan.py", "nightly"], ["python", "oiscan.py", "nightly"], ["python", "mxscan.py"]):
            sh(*script)
        MARK.write_text(now.strftime("%Y-%m-%d"))
        publish(f"Ночной пересчёт {now:%Y-%m-%d %H:%M}")
    elif trading(now):
        for script in (["python", "volscan.py", "intraday"], ["python", "oiscan.py", "intraday"], ["python", "mxscan.py"]):
            sh(*script)
        publish(f"Живое обновление {now:%Y-%m-%d %H:%M}")
    else:
        print(now.strftime("%H:%M"), "вне торгов", flush=True)
    time.sleep(max(30, STEP - (time.time() - t0)))
sys.exit(0)
