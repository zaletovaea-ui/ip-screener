#!/usr/bin/env python3
"""Технический анализ в течение дня: обновляет журнал (текущие цены, стопы/цели, ручные закрытия) без нового скана."""
import tracker
from screener import load_candles

if __name__ == "__main__":
    n = tracker.refresh(load_candles)
    print("Журнал ТА обновлён", f"(ручных закрытий: {n})" if n else "")
