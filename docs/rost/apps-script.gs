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
const SHEETS = ['Summary', 'All', 'Transactions', 'Closed Deals', 'Пополнения',
                'Portfolio Log', 'Тейки для идей', 'Base'];

function doGet(e) {
  const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || !e || !e.parameter || e.parameter.token !== token) {
    return out_({ error: 'unauthorized' });
  }
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const tz = ss.getSpreadsheetTimeZone();
  const res = { updated: new Date().toISOString(), sheets: {} };
  SHEETS.forEach(function (name) {
    const sh = ss.getSheetByName(name);
    if (!sh) return;
    const values = sh.getDataRange().getValues();
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
  return out_(res);
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
