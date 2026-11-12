// Раздел «Аномальные объёмы»: сигналы дня, журнал, все аномалии.
(function () {
  const f = (x, d) => x == null ? "—" : Number(x).toLocaleString("ru-RU", { minimumFractionDigits: d ?? 0, maximumFractionDigits: d ?? 0 });
  const px = x => { if (x == null) return "—"; x = +x; const d = x >= 1000 ? 0 : x >= 100 ? 1 : x >= 1 ? 2 : 4; return f(x, d); };
  const pc = (x) => x == null ? "—" : (x > 0 ? "▲ +" : x < 0 ? "▼ −" : "") + f(Math.abs(x), 1) + "%";
  const cl = x => x > 0 ? "up" : x < 0 ? "down" : "";
  const mln = x => x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + f(Math.abs(x), Math.abs(x) >= 100 ? 0 : 1);
  const dt = s => s ? s.slice(8, 10) + "." + s.slice(5, 7) + (s.length > 10 ? " " + s.slice(11, 16) : "") : "—";
  const tk = (t, n) => `<a class="tk" href="https://www.tradingview.com/chart/?symbol=MOEX:${t}" target="_blank" rel="noopener">${t}</a><div class="nm">${n || ""}</div>`;
  const side = s => s === "buy" ? '<span class="pill buy">Покупка</span>' : s === "sell" ? '<span class="pill sell">Продажа</span>' : '<span class="pill neu">без направления</span>';
  const bar = v => `<span style="display:inline-block;width:56px;height:6px;border-radius:3px;background:#FEE2E2;vertical-align:middle;margin-right:6px;overflow:hidden"><i style="display:block;height:100%;width:${v}%;background:var(--up)"></i></span>${v}%`;

  function sigTable(rows) {
    if (!rows.length) return "<tr><td>Пока сигналов нет</td></tr>";
    return `<tr><th>Время</th><th>Тикер</th><th class="num">Объём ×</th><th>Покупатели</th><th class="num">За день</th><th class="num">Цена при сигнале</th><th class="num">Сейчас</th><th class="num">Нетто сегодня</th><th class="num">Нетто 20 дн.</th><th class="num">Оборот, млн ₽</th></tr>` +
      rows.map(r => {
        const ch = r.side === "sell" ? (1 - r.price / r.first_price) * 100 : (r.price / r.first_price - 1) * 100;
        return `<tr><td>${r.first_time}</td><td>${tk(r.ticker, r.name)}</td><td class="num"><b>×${f(r.ratio, 1)}</b><div class="nm">при сигнале ×${f(r.first_ratio, 1)}</div></td>
        <td>${bar(r.buy_share)}</td><td class="num ${cl(r.change_pct)}">${pc(r.change_pct)}</td><td class="num">${px(r.first_price)}</td>
        <td class="num">${px(r.price)}<div class="nm ${cl(ch)}">${pc(ch)}</div></td>
        <td class="num ${cl(r.net_today_mln)}">${mln(r.net_today_mln)}</td><td class="num ${cl(r.net30_mln)}">${mln(r.net30_mln)}</td><td class="num">${f(r.value_mln)}</td></tr>`;
      }).join("");
  }

  function allTable(rows) {
    if (!rows.length) return "<tr><td>Аномалий нет</td></tr>";
    return `<tr><th>Тикер</th><th>Направление</th><th class="num">Объём ×</th><th>Покупатели</th><th class="num">За день</th><th class="num">Положение в диапазоне дня</th><th class="num">Цена</th><th class="num">Нетто сегодня</th><th class="num">Оборот, млн ₽</th><th>Данные на</th></tr>` +
      rows.map(r => `<tr><td>${tk(r.ticker, r.name)}</td><td>${side(r.side)}</td><td class="num"><b>×${f(r.ratio, 1)}</b></td><td>${bar(r.buy_share)}</td>
        <td class="num ${cl(r.change_pct)}">${pc(r.change_pct)}</td><td class="num">${r.range_pos}%</td><td class="num">${px(r.price)}</td>
        <td class="num ${cl(r.net_today_mln)}">${mln(r.net_today_mln)}</td><td class="num">${f(r.value_mln)}</td><td>${r.time}</td></tr>`).join("");
  }

  function journal(rows, closed, P) {
    if (!rows.length) return `<tr><td>${closed ? "Закрытых сигналов пока нет" : "Открытых сигналов нет"}</td></tr>`;
    if (closed) return `<tr><th>Тикер</th><th>Направление</th><th>Открыт</th><th class="num">Вход</th><th>Итог</th><th>Закрыт</th><th class="num">Дней</th><th class="num">Результат</th><th>Сигнал</th></tr>` +
      rows.map(s => `<tr><td>${tk(s.ticker, s.name)}</td><td>${side(s.side)}</td><td>${dt(s.opened_at)}</td><td class="num">${px(s.entry)}</td>
        <td><span class="pill ${s.result_pct > 0 ? "tgt" : "sell"}">${s.status}</span></td><td>${dt(s.closed_at || s.closed)}</td><td class="num">${s.days ?? 0}</td>
        <td class="num ${cl(s.result_pct)}">${pc(s.result_pct)}</td><td class="cm">${s.comment || ""}</td></tr>`).join("");
    return `<tr><th>Тикер</th><th>Направление</th><th>Открыт</th><th class="num">Вход</th><th class="num">Стоп</th><th class="num">Сейчас</th><th>В сделке</th><th class="num">Результат</th><th>Сигнал</th></tr>` +
      rows.map(s => {
        const days = s.days || 0, max = P.max_days || 10;
        return `<tr><td>${tk(s.ticker, s.name)}</td><td>${side(s.side)}</td><td>${dt(s.opened_at)}</td><td class="num">${px(s.entry)}</td>
        <td class="num">${px(s.stop)}${s.trailing ? '<div class="nm">трейлинг</div>' : `<div class="nm">${pc(s.stop_pct)}</div>`}</td>
        <td class="num">${px(s.last_price)}</td>
        <td><span style="display:inline-block;width:70px;height:6px;border-radius:3px;background:#E2E8F0;vertical-align:middle;overflow:hidden"><i style="display:block;height:100%;width:${Math.min(100, days / max * 100)}%;background:var(--blue)"></i></span> ${days} из ${max}</td>
        <td class="num ${cl(s.current_pct)}">${pc(s.current_pct)}${window.ipCloseBtn ? window.ipCloseBtn("volume", s.id, s.last_price, s.ticker) : ""}</td><td class="cm">${s.comment || ""}</td></tr>`;
      }).join("");
  }

  window.ipVolumeRender = (vol, jr) => {
    const asof = document.getElementById("asof-vol");
    if (!vol) {
      asof.textContent = "Данных пока нет: первый расчёт нормы объёмов идёт на сервере.";
      ["v-buy", "v-sell", "v-all"].forEach(id => document.getElementById(id).innerHTML = "<tr><td>Данных пока нет</td></tr>");
    } else {
      asof.textContent = `Обновлено ${dt(vol.updated)} МСК · аномалий сейчас: ${vol.anomalies.length} · сигналов за день: ${vol.signals.length}` +
        (vol.norm_days < 20 ? ` · норма по ${vol.norm_days} дням` : "");
      document.getElementById("v-buy").innerHTML = sigTable(vol.signals.filter(r => r.side === "buy"));
      document.getElementById("v-sell").innerHTML = sigTable(vol.signals.filter(r => r.side === "sell"));
      document.getElementById("v-all").innerHTML = allTable(vol.anomalies);
    }
    const P = (jr && jr.params) || (vol && vol.params) || {};
    if (jr) {
      const st = jr.stats || {};
      document.getElementById("v-stats").innerHTML = [
        ["Всего сигналов", st.total ?? 0], ["Открыто", st.open ?? 0], ["Закрыто", st.closed ?? 0],
        ["Доля прибыльных", st.win_rate != null ? f(st.win_rate, 0) + "%" : "—", true],
        ["Средний результат", st.avg_result != null ? pc(st.avg_result) : "—"],
        ["Стоп / трейлинг / объём против / срок", st.closed ? `${st["стоп"] || 0} / ${st["трейлинг"] || 0} / ${st["объём против"] || 0} / ${st["истёк"] || 0}` : "—"],
      ].map(([k, v, h]) => `<div class="card${h ? " hl" : ""}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
      const sigs = jr.signals || [];
      document.getElementById("v-open").innerHTML = journal(sigs.filter(s => s.status === "открыт"), false, P);
      document.getElementById("v-closed").innerHTML = journal(sigs.filter(s => s.status !== "открыт").reverse(), true, P);
    }
    document.getElementById("v-rules").textContent =
      `Правила: вход — цена в момент сигнала; стоп — за минимумом (максимумом) дня сигнала, но не ближе ${f((P.min_stop || 0.015) * 100, 1)}% и не дальше ${f((P.max_stop || 0.08) * 100, 0)}%; ` +
      `с ${P.trail_from || 5}-го дня — трейлинг-стоп ${f((P.trail || 0.014) * 100, 1)}% от лучшего закрытия; максимум ${P.max_days || 10} торговых дней; ` +
      `досрочный выход, если против позиции пришёл объём ≥${P.against_ratio || 2}× нормы и его инициаторы ≥${f((P.against_share || 0.6) * 100, 0)}%. ` +
      `В день входа стоп проверяется по 5-минутным свечам, дальше — по дневным.`;
  };

  // сигналы дня → карточки для «Формирования идей»
  window.ipVolumeIdeas = (vol) => {
    if (!vol) return [];
    const P = vol.params || {};
    return vol.signals.map(r => {
      const buy = r.side === "buy", e = r.first_price;
      let stop = buy ? r.day_low * (1 - (P.stop_pad || 0.005)) : r.day_high * (1 + (P.stop_pad || 0.005));
      stop = buy ? Math.max(Math.min(stop, e * (1 - (P.min_stop || 0.015))), e * (1 - (P.max_stop || 0.08)))
                 : Math.min(Math.max(stop, e * (1 + (P.min_stop || 0.015))), e * (1 + (P.max_stop || 0.08)));
      const risk = Math.abs(e - stop);
      const who = buy ? "покупатели" : "продавцы", share = buy ? r.buy_share : 100 - r.buy_share;
      return {
        ticker: r.ticker, name: r.name, side: r.side, strategy: "volume", date: vol.date, top: true, count: 1, rating: "📊",
        close: e, entry_limit: buy ? e * 1.01 : e * 0.99, stop,
        take1: buy ? e + 2 * risk : e - 2 * risk, take2: buy ? e + 3 * risk : e - 3 * risk, target: buy ? e + 3 * risk : e - 3 * risk,
        comment: `Объём ×${r.first_ratio} нормы, ${who} ${share}%`,
        idea: [
          `Аномальный объём: к ${r.first_time} оборот в ${String(r.first_ratio).replace(".", ",")} раза выше обычного для этого времени дня (медиана за 20 торговых дней).`,
          `Сделки инициировали ${who} — ${share}% оборота, цена ${buy ? "растёт" : "снижается"} на ${String(Math.abs(r.change_pct)).replace(".", ",")}% за день и держится в ${buy ? "верхней" : "нижней"} части дневного диапазона.`,
          `Нетто-поток ${buy ? "покупателей" : "продавцов"} за день — ${Math.abs(r.net_today_mln)} млн руб.: в бумагу ${buy ? "пришли" : "вышли"} крупные деньги.`,
        ],
        risk: `сценарий отменяется при ${buy ? "уходе цены ниже" : "росте цены выше"} ${px(stop)} руб. (${buy ? "минимум" : "максимум"} дня сигнала). Объёмный импульс может быть разовым: если на следующий день объём против позиции, выходим досрочно.`,
        signals: [r.comment || ""],
      };
    });
  };
})();
