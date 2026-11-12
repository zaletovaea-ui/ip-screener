// Вкладка «Формирование идей» (видна только в режиме редактора: ссылка с ?editor=1).
// Отмеченные идеи и правки хранятся в этом браузере (localStorage), поэтому сообщения
// «тейк» и «стоп» можно сделать и через несколько дней, когда идея уже ушла из скана.
(function () {
  const LS = "ipIdeas.v1";
  const url = new URL(location.href);
  let editor = false;
  try {
    if (url.searchParams.get("editor") === "1") localStorage.setItem("ipEditor", "1");
    if (url.searchParams.get("editor") === "0") localStorage.removeItem("ipEditor");
    editor = localStorage.getItem("ipEditor") === "1";
  } catch (e) { editor = url.searchParams.get("editor") === "1"; }
  if ((window.IP_CONFIG || {}).ideasForAll) editor = true;
  if (!editor) return;
  document.querySelectorAll(".nav-ideas").forEach(b => b.classList.remove("hidden"));

  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(LS) || "{}"); } catch (e) {}
  const persist = () => { try { localStorage.setItem(LS, JSON.stringify(saved)); } catch (e) {} };
  const touch = d => { d.updated = Date.now(); persist(); syncSoon(); };

  let companies = {}, scan = [], market = null, current = null;

  // ---------- синхронизация через приватный репозиторий GitHub ----------
  const CFG = window.IP_CONFIG || {};
  const TK = "ipIdeasToken";
  let token = ""; try { token = localStorage.getItem(TK) || ""; } catch (e) {}
  let remoteSha = null, syncTimer = null, syncState = token ? "…" : "off";
  const b64e = s => btoa(unescape(encodeURIComponent(s)));
  const b64d = s => decodeURIComponent(escape(atob(s.replace(/\n/g, ""))));
  const api = (method, body) => fetch(`https://api.github.com/repos/${CFG.ideasRepo}/contents/${CFG.ideasPath}`, {
    method, cache: "no-store",
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined });

  function merge(remote) {  // по каждой идее побеждает более свежая правка; удаление хранится как метка
    let changed = false;
    for (const [id, r] of Object.entries(remote || {})) {
      const l = saved[id];
      if (!l || (r.updated || 0) > (l.updated || 0)) { saved[id] = r; }
    }
    for (const [id, l] of Object.entries(saved)) {
      const r = (remote || {})[id];
      if (!r || (l.updated || 0) > (r.updated || 0)) changed = true;
    }
    return changed;
  }

  async function pull() {
    const res = await api("GET");
    if (res.status === 404) { remoteSha = null; return {}; }
    if (!res.ok) throw new Error(res.status === 401 ? "токен не подходит" : "GitHub " + res.status);
    const j = await res.json(); remoteSha = j.sha;
    return JSON.parse(b64d(j.content) || "{}");
  }

  async function sync() {
    if (!token) { syncState = "off"; showSync(); return; }
    syncState = "…"; showSync();
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const remote = await pull();
        const needPush = merge(remote);
        persist();
        if (!needPush) break;
        const res = await api("PUT", { message: "Идеи: обновление", content: b64e(JSON.stringify(saved, null, 1)), ...(remoteSha ? { sha: remoteSha } : {}) });
        if (res.ok) { remoteSha = (await res.json()).content.sha; break; }
        if (res.status !== 409 && res.status !== 422) throw new Error("GitHub " + res.status);
      }
      syncState = "ok:" + new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    } catch (e) { syncState = "err:" + e.message; }
    showSync(); renderList(); if (current && !saved[current]) current = null;
  }
  const syncSoon = () => { clearTimeout(syncTimer); syncTimer = setTimeout(sync, 1200); };

  function showSync() {
    const el = document.getElementById("ideas-sync"); if (!el) return;
    // синхронизация необязательна: панель видна, только если она подключена или открыта ссылка с ?sync=1
    if (syncState === "off" && url.searchParams.get("sync") !== "1") { el.innerHTML = ""; return; }
    if (syncState === "off") el.innerHTML = `<span>Идеи хранятся только в этом браузере.</span> <button class="btn" id="sync-on">Подключить синхронизацию</button>`;
    else if (syncState === "…") el.innerHTML = `<span>☁ Синхронизация…</span>`;
    else if (syncState.startsWith("ok")) el.innerHTML = `<span>☁ Синхронизировано в ${syncState.slice(3)}</span> <button class="btn" id="sync-now">Обновить</button> <button class="btn" id="sync-off">Отключить</button>`;
    else el.innerHTML = `<span class="warn">Синхронизация: ${esc(syncState.slice(4))}</span> <button class="btn" id="sync-on">Ввести токен заново</button> <button class="btn" id="sync-now">Повторить</button>`;
    const on = document.getElementById("sync-on");
    if (on) on.onclick = () => {
      el.innerHTML = `<input id="sync-tok" type="password" placeholder="Вставьте токен GitHub (github_pat_…)" style="flex:1;min-width:240px;height:40px;border:1px solid #CBD5E1;border-radius:8px;padding:0 10px"> <button class="btn" id="sync-save">Сохранить</button>`;
      document.getElementById("sync-save").onclick = () => {
        token = document.getElementById("sync-tok").value.trim();
        try { localStorage.setItem(TK, token); } catch (e) {}
        sync();
      };
    };
    const now = document.getElementById("sync-now"); if (now) now.onclick = sync;
    const off = document.getElementById("sync-off"); if (off) off.onclick = () => {
      if (!confirm("Отключить синхронизацию в этом браузере? Идеи в GitHub останутся.")) return;
      token = ""; try { localStorage.removeItem(TK); } catch (e) {} syncState = "off"; showSync();
    };
  }

  const fp = x => { x = +x; if (!isFinite(x)) return ""; const d = x >= 1000 ? 0 : x >= 100 ? 1 : x >= 1 ? 2 : 4; return x.toFixed(d); };
  const pc = (a, b) => ((b / a - 1) * 100);
  const sgn = x => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(1);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const idOf = r => `${r.date}-${r.ticker}-${r.side}-${r.strategy || "ta"}`;

  function fromScan(r) {
    const co = companies[r.ticker] || [];
    const buy = r.side === "buy";
    return {
      id: idOf(r), ticker: r.ticker, side: r.side, strategy: r.strategy || "ta", date: r.date,
      name: co[0] || (r.name || r.ticker).replace(/\s*-?\s*а[оп]$/i, "").trim(),
      sector: co[1] || "", type: r.strategy === "momentum" ? "моментум" : r.strategy === "volume" ? "объёмы" : r.strategy === "oi" ? "открытый_интерес" : "техническая",
      rating: r.rating, comment: r.comment || "",
      price: fp(r.close), entry: fp(r.entry_limit ?? r.close * (buy ? 1.01 : 0.99)),
      stop: fp(r.stop), take1: fp(r.take1 ?? r.target), take2: fp(r.take2 ?? r.target),
      share: "5", idea: (r.idea || r.signals || []).join(" "), risk: r.risk || "",
      link: "", take1_done: false, note: "",
    };
  }

  // ---------- тексты ----------
  function post(d) {
    const buy = d.side === "buy", e = +d.price;
    const p = x => sgn(buy ? pc(e, +x) : -pc(e, +x)) + "%";
    return [
      "🔹🔹", "#идея", "",
      `${d.name} #${d.ticker}`,
      buy ? "#акция_спекуляция" : "#акция_спекуляция #шорт",
      d.sector ? `Сектор: #${d.sector.replace(/\s+/g, "_")}` : null,
      `Тип: #${d.type.replace(/\s+/g, "_")}`, "",
      "🔹в чем идея?",
      `- ${d.idea}`,
      d.risk ? `Риски – ${d.risk}` : null, "",
      `🔹Вход: с текущих ${buy ? "не выше" : "не ниже"} ${d.entry} руб.`,
      `🔹Стоп: ${d.stop} руб. (${p(d.stop)})`,
      `🔹Тейк 1: ${d.take1} руб. (${p(d.take1)})  Тейк 2: ${d.take2} руб. (${p(d.take2)})`, "",
      `Доля до ${d.share}%`,
      "❗️Не является индивидуальной инвестиционной рекомендацией.",
    ].filter(x => x !== null).join("\n");
  }

  const ideaRef = d => d.link ? `[рамках спекулятивной идеи](${d.link})` : "рамках спекулятивной идеи";

  function msgTake(d, n) {
    const buy = d.side === "buy", e = +d.price, t = n === 1 ? d.take1 : d.take2;
    const r = buy ? pc(e, +t) : -pc(e, +t);
    const lines = ["📌 ТЕЙК ПРОФИТ", "",
      `#${d.ticker} котировки ${d.name} достигли ${n === 1 ? "первого" : "второго"} уровня фиксации прибыли ${t} руб. (${sgn(r)}%) в ${ideaRef(d)}.`, ""];
    if (n === 1) {
      lines.push(`Фиксируем половину позиции, стоп переносим в безубыток — на уровень входа ${d.price} руб.`);
      lines.push(`Доля ${+d.share / 2}%.`);
    } else {
      lines.push("Сработал тейк-профит на остаток позиции.");
      lines.push("Доля 0%. Не забудьте снять стоп лосс.");
    }
    if (d.note) lines.push("", d.note);
    return lines.join("\n");
  }

  function msgStop(d) {
    const buy = d.side === "buy", e = +d.price;
    let level = d.stop, res = buy ? pc(e, +d.stop) : -pc(e, +d.stop);
    if (d.take1_done) {  // после первого тейка стоп в безубытке: половина закрыта в плюс, половина в ноль
      level = d.price;
      res = (buy ? pc(e, +d.take1) : -pc(e, +d.take1)) / 2;
    }
    const lines = ["❗️СТОП", "",
      `#${d.ticker} В ${ideaRef(d).replace("рамках спекулятивной идеи", "рамках отдельной спекулятивной идеи")} по акциям ${d.name} сработал стоп на уровне ${level} руб.${d.take1_done ? " (безубыток после первого тейка)" : ""}`, "",
      `Общий результат спекуляции ${sgn(res)}%`];
    if (d.note) lines.push("", d.note);
    return lines.join("\n");
  }

  // ---------- копирование: в Telegram ссылка вставится ссылкой ----------
  async function copy(text, btn) {
    const html = esc(text).replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2">$1</a>').replace(/\n/g, "<br>");
    const plain = text.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "$1 ($2)");
    try {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([plain], { type: "text/plain" }) })]);
    } catch (e) {
      try { await navigator.clipboard.writeText(plain); }
      catch (e2) { const ta = document.createElement("textarea"); ta.value = plain; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
    }
    const old = btn.textContent; btn.textContent = "Скопировано ✓"; setTimeout(() => btn.textContent = old, 1500);
  }

  // ---------- список ----------
  function row(d, checked, isSaved) {
    const pill = d.strategy === "momentum" ? '<span class="pill mom-p">Моментум</span>'
      : d.strategy === "oi" ? `<span class="pill oi-p">ОИ физлиц · ${d.side === "buy" ? "лонг" : "шорт"}</span>`
      : d.strategy === "volume" ? `<span class="pill vol-p">Объёмы · ${d.side === "buy" ? "покупка" : "продажа"}</span>`
      : d.side === "buy" ? '<span class="pill buy">Покупка</span>' : '<span class="pill sell">Продажа</span>';
    return `<label class="irow${current === d.id ? " cur" : ""}" data-id="${d.id}">
      <input type="checkbox" ${checked ? "checked" : ""} data-id="${d.id}">
      <span class="it"><b>${d.ticker}</b> <span class="nm">${esc(d.name)}</span></span>
      <span>${pill}</span><span class="ir">${d.rating || ""}</span>
      <span class="nm ic">${isSaved ? "идея от " + d.date.split("-").reverse().join(".") : esc(d.comment)}</span></label>`;
  }

  function renderList() {
    const mine = Object.values(saved).filter(d => !d.deleted).sort((a, b) => b.date.localeCompare(a.date));
    const fresh = scan.filter(r => !saved[idOf(r)] || saved[idOf(r)].deleted).map(fromScan);
    const top = fresh.filter(d => scan.find(r => idOf(r) === d.id).top);
    const rest = fresh.filter(d => !scan.find(r => idOf(r) === d.id).top);
    document.getElementById("ideas-list").innerHTML =
      (mine.length ? `<div class="ih">Мои идеи (${mine.length})</div>` + mine.map(d => row(d, true, true)).join("") : "") +
      `<div class="ih">Подборка дня, моментум, объёмы и ОИ физлиц</div>` + (top.map(d => row(d, false)).join("") || '<div class="nm" style="padding:8px 12px">нет</div>') +
      `<div class="ih">Остальные сигналы скана</div>` + rest.map(d => row(d, false)).join("");
    document.querySelectorAll("#ideas-list input[type=checkbox]").forEach(cb => cb.onchange = () => {
      const id = cb.dataset.id;
      if (cb.checked) {
        const r = scan.find(x => idOf(x) === id);
        if (r) { saved[id] = fromScan(r); touch(saved[id]); }
        current = id;
      } else {
        if (!confirm("Убрать идею из «Моих идей»? Правки по ней удалятся.")) { cb.checked = true; return; }
        saved[id] = { id, deleted: true, date: saved[id]?.date || "" }; touch(saved[id]);
        if (current === id) current = null;
      }
      renderList(); renderPanel();
    });
    document.querySelectorAll("#ideas-list .irow").forEach(l => l.onclick = ev => {
      if (ev.target.tagName === "INPUT") return;
      ev.preventDefault();
      if (saved[l.dataset.id] && !saved[l.dataset.id].deleted) { current = l.dataset.id; renderList(); renderPanel(); }
    });
  }

  // ---------- панель ----------
  const F = [["name", "Компания"], ["sector", "Сектор (хештег)"], ["type", "Тип (хештег)"], ["share", "Доля до, %"],
             ["price", "Цена входа (от неё считаются %)"], ["entry", "Вход: не выше / не ниже, руб."], ["stop", "Стоп, руб."], ["take1", "Тейк 1, руб."], ["take2", "Тейк 2, руб."]];

  function renderPanel() {
    const box = document.getElementById("ideas-panel");
    const d = current && saved[current] && !saved[current].deleted ? saved[current] : null;
    if (!d) { box.innerHTML = '<div class="empty">Поставьте галочку у бумаги слева — здесь появится идея: вход, стоп, тейки и готовый пост.</div>'; return; }
    box.innerHTML = `
      <div class="ph"><div><b class="pt">${d.ticker}</b> <span class="nm">${esc(d.name)} · сигнал от ${d.date.split("-").reverse().join(".")}</span></div></div>
      <div class="fg">${F.map(([k, l]) => `<label class="f"><span>${l}</span><input data-k="${k}" value="${esc(d[k])}"></label>`).join("")}</div>
      <label class="f"><span>🔹 В чем идея</span><textarea data-k="idea" rows="5">${esc(d.idea)}</textarea></label>
      <label class="f"><span>Риски</span><textarea data-k="risk" rows="2">${esc(d.risk)}</textarea></label>
      <div class="ibar"><b>Пост идеи</b><button class="btn" id="cp-post">Скопировать</button></div>
      <pre class="out" id="out-post"></pre>
      <h3 class="ih2">Сопровождение</h3>
      <label class="f"><span>Ссылка на пост идеи в Telegram (вставьте после публикации)</span><input data-k="link" value="${esc(d.link)}" placeholder="https://t.me/c/..."></label>
      <label class="f"><span>Комментарий к сообщению (необязательно)</span><input data-k="note" value="${esc(d.note)}" placeholder="Например: закрываем на новостях, возможен откат"></label>
      <label class="chk"><input type="checkbox" data-k="take1_done" ${d.take1_done ? "checked" : ""}> Тейк 1 уже сработал (стоп перенесён в безубыток)</label>
      <div class="acts"><button class="btn tk" data-m="t1">📌 Тейк 1</button><button class="btn tk" data-m="t2">📌 Тейк 2</button><button class="btn st" data-m="st">❗️ Стоп</button></div>
      <div id="msg-wrap" class="hidden"><div class="ibar"><b id="msg-title"></b><button class="btn" id="cp-msg">Скопировать</button></div><pre class="out" id="out-msg"></pre></div>`;
    const upd = () => { document.getElementById("out-post").textContent = post(d); };
    box.querySelectorAll("[data-k]").forEach(el => el.oninput = el.onchange = () => {
      d[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value; touch(d); upd();
      if (lastMsg) showMsg(lastMsg);
    });
    let lastMsg = null;
    const showMsg = m => {
      lastMsg = m;
      document.getElementById("msg-wrap").classList.remove("hidden");
      document.getElementById("msg-title").textContent = m === "st" ? "Сообщение: стоп" : `Сообщение: тейк ${m === "t1" ? 1 : 2}`;
      document.getElementById("out-msg").textContent = m === "st" ? msgStop(d) : msgTake(d, m === "t1" ? 1 : 2);
    };
    box.querySelectorAll("[data-m]").forEach(b => b.onclick = () => showMsg(b.dataset.m));
    document.getElementById("cp-post").onclick = e => copy(post(d), e.target);
    document.getElementById("cp-msg").onclick = e => copy(document.getElementById("out-msg").textContent, e.target);
    upd();
  }

  window.ipIdeasInit = async (rep, extra) => {
    try { companies = await (await fetch("data/companies.json?v=" + Date.now())).json(); } catch (e) {}
    scan = (rep?.results || []).concat(extra || []).sort((a, b) => (b.top - a.top) || ((b.strategy === "momentum") - (a.strategy === "momentum")) || (b.count - a.count));
    market = rep?.market;
    renderList(); renderPanel(); showSync();
    if (token) sync();
  };
})();
