// Вкладка «MX против физлиц»: позиция всегда против физлиц, переворот при изменении их позиции за 3 дня ≥ порога.
(function () {
  const f = (x, d) => x == null ? "—" : Number(x).toLocaleString("ru-RU", { minimumFractionDigits: d ?? 0, maximumFractionDigits: d ?? 0 });
  const sg = (x, d) => x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + f(Math.abs(x), d ?? 0);
  const pc = x => x == null ? "—" : (x > 0 ? "▲ +" : x < 0 ? "▼ −" : "") + f(Math.abs(x), 1) + "%";
  const cl = x => x > 0 ? "up" : x < 0 ? "down" : "";
  const dt = s => s ? s.slice(8, 10) + "." + s.slice(5, 7) + "." + s.slice(2, 4) : "—";
  const pos = p => p === "long" || p > 0 ? '<span class="pill buy">Лонг MX</span>' : p === "short" || p < 0 ? '<span class="pill sell">Шорт MX</span>' : '<span class="pill neu">вне рынка</span>';

  function chart(curve, liveFrom) {
    if (!curve || curve.length < 2) return "";
    const W = 1000, H = 220, P = 30;
    const ys = curve.map(c => c[1]), mn = Math.min(0, ...ys), mx = Math.max(...ys);
    const x = i => P + i / (curve.length - 1) * (W - 2 * P), y = v => H - P - (v - mn) / (mx - mn || 1) * (H - 2 * P);
    const pts = curve.map((c, i) => `${x(i).toFixed(1)},${y(c[1]).toFixed(1)}`).join(" ");
    const li = curve.findIndex(c => c[0] >= liveFrom);
    const years = []; let prevY = "";
    curve.forEach((c, i) => { if (c[0].slice(0, 4) !== prevY) { prevY = c[0].slice(0, 4); years.push([i, prevY]); } });
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
      <line x1="${P}" x2="${W - P}" y1="${y(0)}" y2="${y(0)}" stroke="#E2E8F0"/>
      ${years.map(([i, yy]) => `<line x1="${x(i)}" x2="${x(i)}" y1="${P / 2}" y2="${H - P}" stroke="#F1F5F9"/><text x="${x(i) + 4}" y="${H - 8}" font-size="12" fill="#64748B">${yy}</text>`).join("")}
      <polyline points="${pts}" fill="none" stroke="#1F5CFF" stroke-width="2.5"/>
      ${li > 0 ? `<line x1="${x(li)}" x2="${x(li)}" y1="${P / 2}" y2="${H - P}" stroke="#0F2042" stroke-dasharray="4 4"/><text x="${x(li) - 6}" y="${P / 2 + 10}" font-size="12" fill="#0F2042" text-anchor="end">старт наблюдения</text>` : ""}
      <text x="${W - P}" y="${y(ys[ys.length - 1]) - 8}" font-size="13" font-weight="600" fill="#0F2042" text-anchor="end">${sg(ys[ys.length - 1], 1)}%</text>
    </svg>`;
  }

  window.ipMxRender = (m) => {
    if (!m) return;
    const P = m.params, c = m.current || {};
    const last = m.rows[0] || {};
    const prog = Math.min(100, Math.abs(last.d3 || 0) / P.threshold * 100);
    document.getElementById("mx-cards").innerHTML = [
      ["Позиция сейчас", `${pos(m.position)}<div class="nm" style="margin-top:6px">с ${dt(c.start)} по ${f(c.entry, 0)} · ${pc(c.current)}</div>`, true],
      ["Изменение физлиц за 3 дня", `<span class="${cl(last.d3)}">${sg(last.d3)}</span><div style="height:6px;background:#E2E8F0;border-radius:3px;margin-top:8px;overflow:hidden"><i style="display:block;height:100%;width:${prog}%;background:${prog >= 100 ? "#DC2626" : "#1F5CFF"}"></i></div><div class="nm">порог ${f(P.threshold)} контр.${m.pending ? " · завтра переворот: " + (m.pending === "long" ? "лонг" : "шорт") : ""}</div>`],
      ["С начала наблюдения (12.11.26)", pc(m.live_return)],
      ["Итог с 2023 года", pc(m.total)],
      ["Индекс за то же время", pc(m.index_change)],
      ["Макс. просадка", pc(m.maxdd)],
    ].map(([k, v, h]) => `<div class="card"><div class="k">${k}</div><div class="v" style="font-size:${h ? 20 : 24}px">${v}</div></div>`).join("");
    document.getElementById("mx-chart").innerHTML = chart(m.curve, P.live_from) +
      `<div class="nm" style="margin-top:6px">По годам: ${Object.entries(m.by_year).map(([y, v]) => `${y}: <b class="${cl(v)}">${sg(v, 1)}%</b>`).join(" · ")}</div>`;
    document.getElementById("mx-rows").innerHTML = `<tr><th>Дата</th><th class="num">Физлица: лонг</th><th class="num">Шорт</th><th class="num">Чистая позиция</th><th class="num">Изм. за день</th><th class="num">Изм. за 3 дня</th><th>Сигнал</th><th class="num">Индекс</th><th>Позиция стратегии</th></tr>` +
      m.rows.map(r => `<tr><td>${dt(r.date)}${r.intraday ? '<div class="nm">внутри дня</div>' : ""}</td><td class="num">${f(r.long)}</td><td class="num">${f(r.short)}</td>
        <td class="num"><b>${sg(r.net)}</b></td><td class="num ${cl(r.d1)}">${sg(r.d1)}</td>
        <td class="num ${Math.abs(r.d3 || 0) >= P.threshold ? "hl10" : ""}"><b class="${cl(r.d3)}">${sg(r.d3)}</b></td>
        <td>${r.signal ? pos(r.signal) : ""}</td><td class="num">${f(r.index, 2)}</td><td>${pos(r.pos)}</td></tr>`).join("");
    document.getElementById("mx-flips").innerHTML = `<tr><th>Позиция</th><th>Открыта</th><th class="num">Вход</th><th>Закрыта</th><th class="num">Выход</th><th class="num">Результат</th></tr>` +
      m.flips.slice(0, 40).map(t => `<tr><td>${pos(t.side)}${t.live ? ' <span class="pill tgt">наблюдение</span>' : ""}</td><td>${dt(t.start)}</td><td class="num">${f(t.entry, 2)}</td>
        <td>${t.exit ? dt(t.exit) : "открыта"}</td><td class="num">${t.exit_price ? f(t.exit_price, 2) : "—"}</td>
        <td class="num ${cl(t.result ?? t.current)}">${pc(t.result ?? t.current)}</td></tr>`).join("");
    document.getElementById("mx-rules").textContent =
      `Правило: если чистая позиция физлиц во фьючерсе MX за ${P.window} торговых дня выросла на ${f(P.threshold)} контрактов и больше — стоим в шорте; снизилась на ${f(P.threshold)} и больше — в лонге; иначе держим текущую позицию. ` +
      `Смена позиции — по открытию следующего дня. Результат по индексу Мосбиржи, с учётом 0,03% на каждый переворот. До ${dt(P.live_from)} — расчёт на истории, с ${dt(P.live_from)} — наблюдение.`;
  };
})();
