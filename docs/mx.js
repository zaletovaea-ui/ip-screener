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

  const tm = s => s ? (s.length > 10 ? s.slice(8, 10) + "." + s.slice(5, 7) + " " + s.slice(11) : dt(s)) : "—";
  function events(L, n) {
    const ev = ((L && L.events) || []).slice().reverse().slice(0, n);
    if (!ev.length) return "<tr><td>Сделок пока нет</td></tr>";
    return `<tr><th>Время</th><th>Действие</th><th>Контракт</th><th class="num">Цена</th><th class="num">Результат</th><th>Причина</th></tr>` +
      ev.map(e => `<tr><td>${tm(e.time)}</td><td><span class="pill ${e.action.startsWith("Открываем") ? (e.side === "long" ? "buy" : "sell") : "neu"}">${e.action}</span></td>
        <td>${e.contract || ""}</td><td class="num">${f(e.price)}</td><td class="num ${cl(e.result)}">${e.result != null ? pc(e.result) : ""}</td><td class="cm">${e.reason || ""}</td></tr>`).join("") +
      (L.position ? `<tr><td colspan="6" class="nm">Сейчас: <b>${L.position === "long" ? "лонг" : "шорт"} ${L.contract}</b> с ${tm(L.entry_time)} по ${f(L.entry)} · цена ${f(L.last_price)} (${L.last_time}) · <b class="${cl(L.current)}">${pc(L.current)}</b> · обновлено ${tm(L.updated)}</td></tr>` : "");
  }

  window.ipMxRender = (m) => {
    if (!m) return;
    const P = m.params, L = m.live_journal || {};
    const last = m.rows[0] || {};
    const d3 = L.d3_now ?? last.d3;
    const prog = Math.min(100, Math.abs(d3 || 0) / P.threshold * 100);
    document.getElementById("mx-events").innerHTML = events(L, 50);
    const top = document.getElementById("mx-events-top"); if (top) top.innerHTML = events(L, 4);
    const now = document.getElementById("mx-now");
    if (now) now.innerHTML = [
      ["Позиция сейчас", `${pos(L.position)}<div class="nm" style="margin-top:6px">${L.position ? `${L.contract || ""} с ${tm(L.entry_time)}` : "после ручного выхода — вход по следующему сигналу"}</div>`, true],
      ["Вход → цена сейчас", `${f(L.entry)} → ${f(L.last_price)}<div class="nm" style="margin-top:6px">на ${L.last_time || ""}</div>`, true],
      ["Текущая сделка", `<span class="${cl(L.current)}">${pc(L.current)}</span>${L.position && window.ipCloseBtn ? `<div style="font-size:13px">${window.ipCloseBtn("mx", L.entry_time, L.last_price, L.contract)}</div>` : ""}`],
      ["Физлица за 3 дня", `<span class="${cl(d3)}">${sg(d3)}</span><div style="height:6px;background:#E2E8F0;border-radius:3px;margin-top:8px;overflow:hidden"><i style="display:block;height:100%;width:${prog}%;background:${prog >= 100 ? "#DC2626" : "#1F5CFF"}"></i></div><div class="nm">переворот при ${d3 >= 0 ? "+" : "−"}${f(P.threshold)} · на ${L.snap_time || ""}</div>`],
    ].map(([k, v, h]) => `<div class="card"><div class="k">${k}</div><div class="v" style="font-size:${h ? 20 : 24}px">${v}</div></div>`).join("");
    const tr = (L.trades || []).slice().reverse();
    const wins = tr.filter(t => t.result > 0).length;
    const js = document.getElementById("mx-jstats");
    if (js) js.innerHTML = [
      ["Закрыто сделок", f(tr.length)],
      ["Прибыльных", tr.length ? `${wins} из ${tr.length}` : "—"],
      ["Итог закрытых сделок", `<span class="${cl(L.closed_return)}">${pc(L.closed_return)}</span>`],
      ["Итог с учётом открытой", `<span class="${cl(L.total_return)}">${pc(L.total_return)}</span>`],
    ].map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
    const tt = document.getElementById("mx-trades");
    if (tt) tt.innerHTML = `<tr><th>Позиция</th><th>Контракт</th><th>Открыта</th><th class="num">Вход</th><th>Закрыта</th><th class="num">Выход / сейчас</th><th class="num">Результат</th></tr>` +
      (L.position ? `<tr><td>${pos(L.position)} <span class="pill tgt">открыта</span></td><td>${L.contract}</td><td>${tm(L.entry_time)}</td><td class="num">${f(L.entry)}</td><td class="nm">ещё открыта</td><td class="num">${f(L.last_price)}<div class="nm">сейчас, ${L.last_time || ""}</div></td><td class="num ${cl(L.current)}">${pc(L.current)}</td></tr>` : "") +
      (tr.map(t => `<tr><td>${pos(t.side)}${t.manual ? ' <span class="pill neu">вручную</span>' : ""}</td><td>${t.contract || ""}</td><td>${tm(t.open_time)}</td><td class="num">${f(t.open_price)}</td><td>${tm(t.close_time)}</td><td class="num">${f(t.close_price)}</td><td class="num ${cl(t.result)}">${pc(t.result)}</td></tr>`).join("")
        || `<tr><td colspan="7" class="nm">Закрытых сделок пока нет — текущая закроется при перевороте.</td></tr>`);
    const as = document.getElementById("asof-mx");
    if (as) as.textContent = `Обновлено ${tm(L.updated)} · данные каждые 10 минут, 07:00–23:50 МСК`;
    document.getElementById("mx-cards").innerHTML = [
      ["Позиция сейчас", `${pos(L.position || m.position)}<div class="nm" style="margin-top:6px">${L.contract || ""} с ${tm(L.entry_time)} по ${f(L.entry)} · ${pc(L.current)}</div>`, true],
      ["Изменение физлиц за 3 дня", `<span class="${cl(d3)}">${sg(d3)}</span><div style="height:6px;background:#E2E8F0;border-radius:3px;margin-top:8px;overflow:hidden"><i style="display:block;height:100%;width:${prog}%;background:${prog >= 100 ? "#DC2626" : "#1F5CFF"}"></i></div><div class="nm">порог ${f(P.threshold)} контр. · на ${L.snap_time || ""}</div>`],
      ["С начала наблюдения (12.11.26)", pc(L.total_return ?? m.live_return)],
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
      `С ${dt(P.live_from)} (наблюдение) переворот делается сразу внутри дня, как только изменение за 3 дня (включая сегодня) пересекает порог, по текущей цене ближнего фьючерса MX; данные обновляются каждые 10 минут. ` +
      `График и итог «с 2023 года» — расчёт на истории: смена позиции по открытию следующего дня, по индексу Мосбиржи, 0,03% на переворот.`;
  };

  // Идея для вкладки «Формирование идей»: текущая позиция MX.
  window.ipMxIdeas = (m) => {
    const L = m && m.live_journal;
    if (!L || !L.position) return [];
    const buy = L.position === "long", e = L.last_price || L.entry, P = m.params;
    const d3 = L.d3_now;
    return [{
      ticker: L.contract, name: "Фьючерс на индекс Мосбиржи MX", side: buy ? "buy" : "sell", strategy: "mx",
      date: (L.entry_time || "").slice(0, 10), top: true, count: 1, rating: "",
      close: L.entry, last: e, entry_limit: e, stop: null, take1: null, take2: null,
      comment: `${buy ? "лонг" : "шорт"} против физлиц`,
      idea: [
        `Физлица за 3 дня ${d3 < 0 ? "сократили" : "нарастили"} чистую позицию во фьючерсе MX на ${Math.abs(d3 || 0).toLocaleString("ru-RU")} контрактов${Math.abs(d3 || 0) >= P.threshold ? " — это выше нашего порога 10 000" : ""}.`,
        `Работаем против толпы: физлица ${buy ? "продают индекс" : "покупают индекс"}, мы — ${buy ? "в лонге" : "в шорте"}. На истории с 2023 года такой подход дал +${Math.round(m.total)}% при просадке ${Math.abs(m.maxdd).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%.`,
      ],
      risk: "физлица могут оказаться правы на сильной новости; стоп не ставим — на истории он ухудшал результат, выходим только переворотом.",
      signals: ["MX против физлиц"],
    }];
  };
})();
