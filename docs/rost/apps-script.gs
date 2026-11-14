/**
 * Помощник «Рост и доход» — отдаёт данные портфеля сайту.
 * ОТДЕЛЬНЫЙ проект на script.google.com (не трогает скрипты внутри таблицы).
 * Только читает таблицу, ничего в ней не меняет.
 * 1) Запустите функцию setup() один раз — в журнале появится ключ.
 * 2) Развернуть → Новое развертывание → Веб-приложение:
 *    «Запуск от имени: я», «Доступ: все». Скопируйте URL.
 * 3) На сайте нажмите ⚙ и вставьте URL и ключ.
 * Без ключа скрипт ничего не отдаёт.
 */
const SHEET_ID = '1x8ddsI65ldrkJKEwwU5oVoJE6N69ruuk0BJXlFmwMYY';
// лист: сколько первых столбцов читать (0 — все)
const SHEETS = {'Summary': 0, 'All': 0, 'Transactions': 9, 'Closed Deals': 9,
                'Пополнения': 4, 'Portfolio Log': 2, 'Base': 8};
const CACHE_SEC = 600; // данные кешируются на 10 минут

function doGet(e) {
  const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || !e || !e.parameter || e.parameter.token !== token) {
    return out_({ error: 'unauthorized' });
  }
  const fresh = e.parameter.fresh === '1';
  const json = (!fresh && cacheGet_()) || cachePut_(JSON.stringify(build_()));
  return ContentService.createTextOutput(json).setMimeType(ContentService.MimeType.JSON);
}

function build_() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const tz = ss.getSpreadsheetTimeZone();
  const res = { updated: new Date().toISOString(), sheets: {} };
  Object.keys(SHEETS).forEach(function (name) {
    const sh = ss.getSheetByName(name);
    if (!sh) return;
    const lr = sh.getLastRow(), lc = sh.getLastColumn();
    if (!lr || !lc) { res.sheets[name] = []; return; }
    const nc = SHEETS[name] ? Math.min(SHEETS[name], lc) : lc;
    const values = sh.getRange(1, 1, lr, nc).getValues();
    const rows = values.map(function (r) {
      const rr = r.map(function (c) {
        return c instanceof Date ? Utilities.formatDate(c, tz, 'yyyy-MM-dd') : c;
      });
      let k = rr.length;
      while (k > 0 && (rr[k - 1] === '' || rr[k - 1] === null)) k--;
      return rr.slice(0, k);
    });
    while (rows.length && rows[rows.length - 1].length === 0) rows.pop();
    res.sheets[name] = rows;
  });
  return res;
}

// кеш хранит куски по 90 КБ (ограничение Google — 100 КБ на значение)
function cacheGet_() {
  const c = CacheService.getScriptCache();
  const n = c.get('rid_n');
  if (!n) return null;
  const keys = []; for (let i = 0; i < +n; i++) keys.push('rid_' + i);
  const parts = c.getAll(keys);
  let s = '';
  for (let i = 0; i < +n; i++) { if (parts['rid_' + i] == null) return null; s += parts['rid_' + i]; }
  return s;
}
function cachePut_(s) {
  try {
    const c = CacheService.getScriptCache(), obj = {}, size = 90000;
    let n = 0;
    for (let i = 0; i < s.length; i += size) obj['rid_' + (n++)] = s.slice(i, i + size);
    obj['rid_n'] = String(n);
    c.putAll(obj, CACHE_SEC);
  } catch (err) {}
  return s;
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function setup() {
  const t = Utilities.getUuid().replace(/-/g, '');
  PropertiesService.getScriptProperties().setProperty('TOKEN', t);
  Logger.log('Ваш ключ для сайта: ' + t);
}
