// Раздел «Открытый интерес физлиц»: сигналы против толпы, таблица ОИ, журнал.
(function () {
  const f = (x, d) => x == null ? "—" : Number(x).toLocaleString("ru-RU", { minimumFractionDigits: d ?? 0, maximumFractionDigits: d ?? 0 });
  const px = x => { if (x == null) return "—"; x = +x; const d = x >= 1000 ? 0 : x >= 100 ? 1 : x >= 1 ? 2 : 4; return f(x, d); };
  const sg = (x, d) => x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + f(Math.abs(x), d ?? 0);
  const pc = x => x == null ? "—" : (x > 0 ? "▲ +" : x < 0 ? "▼ −" : "") + f(Math.abs(x), 1) + "%";
  const cl = x => x > 0 ? "up" : x < 0 ? "down" : "";
  const dt = s => s ? s.slice(8, 10) + "." + s.slice(5, 7) : "—";
  const tk = (t, n) => `<a class="tk" href="https://www.tradingview.com/chart/?symbol=MOEX:${t}" target="_blank" rel="noopener">${t}</a><div class="nm">${n || ""}</div>`;
  const side = s => s === "buy" ? '<span class="pill buy">Лонг акции</span>' : '<span class="pill sell">Шорт акции</span>';
  const mln = x => x == null ? "" : `<div class="nm">${sg(x, Math.abs(x) >= 100 ? 0 : 1)} млн ₽</div>`;
  // изменение позиции физлиц: цвет по направлению их позиции (рост лонга — зелёный), подсветка по силе
  const rel = r => `<td class="num ${Math.abs(r.rel_pct) >= 10 ? "hl10" : ""}"><b class="${cl(r.rel_pct)}">${sg(r.rel_pct, 1)}%</b></td>`;

  function sigRows(rows) {
    if (!rows.length) return "<tr><td>Нет сигналов</td></tr>";
    return `<tr><th>Идея</th><th>Сигнал</th><th>Тикер</th><th class="num">Физлица изм. за день</th><th class="num">% позиции</th><th class="num">Цена при сигнале</th><th>Статус</th><th class="num">Вход</th><th class="num">Стоп</th><th class="num">Результат</th></tr>` +
      rows.map(s => `<tr><td>${side(s.side)}</td><td>${dt(s.signal_date)}</td><td>${tk(s.ticker, s.name)}</td>
        <td class="num ${cl(s.d_net)}">${sg(s.d_net)} контр.${mln(s.d_net_mln)}</td>
        <td class="num"><b>${sg(s.rel_pct, 1)}%</b></td><td class="num">${px(s.ref_price)}</td>
        <td>${s.status === "ждёт входа" ? '<span class="pill neu">вход по открытию</span>' : `<span class="pill ${s.status === "открыт" ? "tgt" : (s.result_pct > 0 ? "tgt" : "sell")}">${s.status}</span>`}</td>
        <td class="num">${s.entry ? px(s.entry) + `<div class="nm">${dt(s.opened)}</div>` : "—"}</td>
        <td class="num">${s.stop ? px(s.stop) + `<div class="nm">${s.trailing ? "трейлинг" : pc(s.stop_pct)}</div>` : "—"}</td>
        <td class="num ${cl(s.result_pct ?? s.current_pct)}">${s.result_pct != null ? pc(s.result_pct) : s.current_pct != null ? pc(s.current_pct) : "—"}${(s.status === "открыт" || s.status === "ждёт входа") && window.ipCloseBtn ? window.ipCloseBtn("oi", s.id, s.last_price || s.ref_price, s.ticker) : ""}</td></tr>`).join("");
  }

  function table(rows, onlySide) {
    if (onlySide) rows = rows.filter(r => r.side);
    if (!rows.length) return "<tr><td>Нет бумаг с изменением ≥10%</td></tr>";
    return `<tr><th>Идея</th><th>Тикер</th><th class="num">Цена</th><th class="num">Физлица: лонг</th><th class="num">Шорт</th><th class="num">Чистая позиция</th>
      <th class="num">Изм. за день</th><th class="num">% позиции</th><th class="num">Изм. за неделю</th><th class="num">Физлиц в лонге / шорте</th></tr>` +
      rows.map(r => `<tr><td>${r.side ? side(r.side) : Math.abs(r.rel_pct) >= 5 ? '<span class="pill neu">заметно</span>' : ""}</td><td>${tk(r.ticker, r.name)}<div class="nm">фьючерс ${r.code}, ${f(r.lot)} акц.</div></td>
        <td class="num">${px(r.price)}<div class="nm ${cl(r.change_pct)}">${pc(r.change_pct)}</div></td>
        <td class="num">${f(r.long)}<div class="nm ${cl(r.d_long)}">${sg(r.d_long)}</div></td>
        <td class="num">${f(r.short)}<div class="nm ${cl(-r.d_short)}">${sg(r.d_short)}</div></td>
        <td class="num"><b>${sg(r.net)}</b>${mln(r.net_mln)}</td>
        <td class="num ${cl(r.d_net)}">${sg(r.d_net)}${mln(r.d_net_mln)}</td>${rel(r)}
        <td class="num ${cl(r.d_net_week)}">${sg(r.d_net_week)}${mln(r.d_net_week_mln)}</td>
        <td class="num">${f(r.long_num)} / ${f(r.short_num)}<div class="nm">${sg(r.d_long_num)} / ${sg(r.d_short_num)}</div></td></tr>`).join("");
  }

  window.ipOiRender = (oi, jr) => {
    const asof = document.getElementById("asof-oi");
    if (!oi) { asof.textContent = "Данных пока нет."; return; }
    asof.textContent = `Открытый интерес: ${oi.mode === "сейчас" ? "сейчас" : "итог дня"} ${dt(oi.date)} ${oi.time || ""} · фьючерсов на акции: ${oi.rows.length} · обновлено ${oi.updated.slice(11)} МСК`;
    document.getElementById("o-all").innerHTML = table(oi.rows, false);
    document.getElementById("o-cand").innerHTML = table(oi.rows, true);
    const sigs = (jr && jr.signals) || [];
    const active = sigs.filter(s => s.status === "ждёт входа" || s.status === "открыт").reverse();
    document.getElementById("o-sell").innerHTML = sigRows(active.filter(s => s.side === "sell"));
    document.getElementById("o-buy").innerHTML = sigRows(active.filter(s => s.side === "buy"));
    document.getElementById("o-open").innerHTML = sigRows(active);
    document.getElementById("o-closed").innerHTML = sigRows(sigs.filter(s => !["ждёт входа", "открыт"].includes(s.status)).reverse());
    const st = (jr && jr.stats) || {};
    document.getElementById("o-stats").innerHTML = [
      ["Всего сигналов", st.total ?? 0], ["Ждут входа", st.pending ?? 0], ["Открыто", st.open ?? 0], ["Закрыто", st.closed ?? 0],
      ["Доля прибыльных", st.win_rate != null ? f(st.win_rate) + "%" : "—", true],
      ["Средний результат", st.avg_result != null ? pc(st.avg_result) : "—"],
    ].map(([k, v, h]) => `<div class="card${h ? " hl" : ""}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  };

  // активные сигналы → «Формирование идей»
  window.ipOiIdeas = (jr) => {
    const P = (jr && jr.params) || {};
    return ((jr && jr.signals) || []).filter(s => s.status === "ждёт входа" || s.status === "открыт").map(s => {
      const buy = s.side === "buy", e = s.entry || s.ref_price, a = s.atr || e * 0.03;
      const stop = s.stop || (buy ? e - (P.atr_k || 1.5) * a : e + (P.atr_k || 1.5) * a);
      const r = Math.abs(e - stop);
      const crowd = buy ? "шорт" : "лонг";
      return {
        ticker: s.ticker, name: s.name, side: s.side, strategy: "oi", date: s.signal_date, top: true, count: 1, rating: "👥",
        close: e, entry_limit: buy ? e * 1.01 : e * 0.99, stop, take1: buy ? e + 2 * r : e - 2 * r, take2: buy ? e + 3 * r : e - 3 * r,
        comment: s.comment,
        idea: [
          `Физлица за день резко нарастили ${crowd} во фьючерсе на ${s.name}: ${s.d_net > 0 ? "+" : "−"}${Math.abs(s.d_net).toLocaleString("ru-RU")} контрактов${s.d_net_mln != null ? ` (≈${Math.abs(s.d_net_mln).toLocaleString("ru-RU")} млн руб.)` : ""}, это ${Math.abs(s.rel_pct).toLocaleString("ru-RU")}% их позиции.`,
          `Толпа массово ставит на ${buy ? "падение" : "рост"}, а на нашей истории после таких всплесков акция чаще шла против физлиц. Поэтому идея — ${buy ? "лонг" : "шорт"} акции.`,
        ],
        risk: `сценарий отменяется при ${buy ? "падении ниже" : "росте выше"} ${px(stop)} руб. (1,5 среднего дневного размаха). Физлица могут оказаться правы на сильной новости — проверьте новостной фон перед входом.`,
        signals: [s.comment],
      };
    });
  };
})();
