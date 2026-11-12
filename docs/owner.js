// Режим владельца: ручное закрытие позиций в журналах.
// Включается ссылкой с ?owner=1 (один раз ввести токен GitHub) — дальше кнопки «Закрыть» видны в этом браузере.
// Закрытие дописывается в docs/data/manual.json репозитория, сервер применяет его в течение ~10 минут.
(function () {
  const REPO = "zaletovaea-ui/ip-screener", FILE = "docs/data/manual.json", TK = "ipOwnerToken";
  const url = new URL(location.href);
  let token = ""; try { token = localStorage.getItem(TK) || ""; } catch (e) {}
  const pending = new Set();
  window.ipOwnerOn = () => !!token;

  window.ipCloseBtn = (section, id, price, label) => {
    if (!token || !id) return "";
    if (pending.has(section + "|" + id)) return '<div class="nm" style="margin-top:4px">закрытие отправлено</div>';
    return `<button class="mc" data-sec="${section}" data-id="${id}" data-px="${price ?? ""}" data-lb="${label || ""}">Закрыть</button>`;
  };

  const b64 = s => btoa(unescape(encodeURIComponent(s)));
  const unb64 = s => decodeURIComponent(escape(atob(s.replace(/\n/g, ""))));
  const api = (method, body) => fetch(`https://api.github.com/repos/${REPO}/contents/${FILE}${method === "GET" ? "?ref=main&t=" + Date.now() : ""}`, {
    method, headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined, cache: "no-store",
  });

  async function send(rec) {
    for (let i = 0; i < 3; i++) {
      const r = await api("GET");
      let data = { closes: [] }, sha;
      if (r.ok) { const js = await r.json(); sha = js.sha; try { data = JSON.parse(unb64(js.content)); } catch (e) {} }
      else if (r.status !== 404) throw new Error("GitHub " + r.status + (r.status === 401 ? " — токен не подходит" : ""));
      data.closes = (data.closes || []).filter(c => !(c.section === rec.section && c.id === rec.id)).concat([rec]);
      const w = await api("PUT", { message: `Ручное закрытие ${rec.section} ${rec.label || rec.id}`, content: b64(JSON.stringify(data, null, 1)), sha, branch: "main" });
      if (w.ok) return;
      if (w.status !== 409 && w.status !== 422) throw new Error("GitHub " + w.status);
    }
    throw new Error("не удалось записать, попробуйте ещё раз");
  }

  const mskNow = () => new Date(Date.now() + 3 * 3600e3).toISOString().slice(0, 16).replace("T", " ");

  document.addEventListener("click", async ev => {
    const b = ev.target.closest(".mc"); if (!b) return;
    ev.preventDefault();
    const { sec, id, px, lb } = b.dataset;
    const price = prompt(`Выход из позиции ${lb}.\nЦена выхода (по умолчанию — последняя цена):`, px);
    if (price === null) return;
    const p = parseFloat(String(price).replace(",", ".").replace(/\s/g, ""));
    if (!(p > 0)) { alert("Нужна цена числом"); return; }
    const note = prompt("Комментарий (необязательно):", "") || "";
    b.disabled = true; b.textContent = "Отправляю…";
    try {
      await send({ section: sec, id, price: p, time: mskNow(), note, label: lb });
      pending.add(sec + "|" + id);
      b.outerHTML = '<div class="nm" style="margin-top:4px">закрытие отправлено ✓<br>появится в журнале за ~10 мин</div>';
    } catch (e) { b.disabled = false; b.textContent = "Закрыть"; alert("Не получилось: " + e.message); }
  });

  // уже отправленные, но ещё не применённые закрытия
  fetch("data/manual.json?v=" + Date.now()).then(r => r.ok ? r.json() : null).then(d => {
    (d?.closes || []).forEach(c => pending.add(c.section + "|" + c.id));
    document.querySelectorAll(".mc").forEach(b => {
      if (pending.has(b.dataset.sec + "|" + b.dataset.id)) b.outerHTML = '<div class="nm" style="margin-top:4px">закрытие отправлено</div>';
    });
  }).catch(() => {});

  // панель входа владельца
  function bar() {
    if (url.searchParams.get("owner") !== "1") return;
    const el = document.createElement("div");
    el.className = "ownerbar";
    const draw = () => {
      el.innerHTML = token
        ? `<span>Режим владельца: кнопки «Закрыть» в журналах включены.</span> <button class="btn" id="own-off">Выключить</button>`
        : `<span>Ручное закрытие позиций:</span> <input id="own-tok" type="password" placeholder="токен GitHub (github_pat_…)"> <button class="btn" id="own-save">Включить</button>`;
      const s = el.querySelector("#own-save"); if (s) s.onclick = () => { token = el.querySelector("#own-tok").value.trim(); try { localStorage.setItem(TK, token); } catch (e) {} location.reload(); };
      const o = el.querySelector("#own-off"); if (o) o.onclick = () => { token = ""; try { localStorage.removeItem(TK); } catch (e) {} location.reload(); };
    };
    draw();
    const w = document.querySelectorAll(".wrap"); (w[1] || document.body).prepend(el);
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", bar) : bar();
})();
