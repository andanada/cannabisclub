'use strict';
// Cobertura de traduccions: tot text de la interfície escrit al codi (català) ha de tenir traducció a castellà i anglès,
// o bé estar a la llista de textos que són iguals en tots els idiomes (noms propis, sigles).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const arrel = path.join(__dirname, '..');
function carrega(lang) {
  const ctx = {
    localStorage: { getItem: () => lang, setItem() {} }, navigator: { language: lang },
    document: { documentElement: {}, addEventListener() {}, title: '' }, MutationObserver: class { observe() {} },
    location: { reload() {} }, confirm: () => true, prompt: () => '', alert: () => {},
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const f of ['i18n-es.js', 'i18n-en.js', 'i18n.js']) vm.runInContext(fs.readFileSync(path.join(arrel, f), 'utf8'), ctx, { filename: f });
  const { tr, I18N } = vm.runInContext('({ tr, I18N })', ctx);
  return Object.assign((t) => tr(t), { te: (t) => Object.prototype.hasOwnProperty.call(I18N[lang], t) });
}

// Mateix text en tots els idiomes (sigles, noms propis, formats).
const IGUALS = new Set(['Bizum', 'IBAN', 'PIN', 'TOTP', 'RFID', 'NFC', 'PDF', 'CSV', 'NIF', 'DNI', 'IVA', 'Stock', 'Local', 'Total', 'Email', 'WhatsApp', 'Més que un Club', 'SHA-256']);

function literals(src) {
  const out = new Set();
  for (const m of src.matchAll(/'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"/g)) out.add((m[1] ?? m[2]).replace(/\\'/g, "'"));
  return [...out];
}
// Sembla un text de pantalla: comença en majúscula, té minúscules i espais o és prou llarg, i no és codi/ruta/identificador.
const esText = (s) => /^[A-ZÀ-Ý«¿¡][^\n]*[a-zà-ÿ]/.test(s) && s.length >= 4 && !/[_=<>{}$\\]|\.js|\.css|https?:/.test(s) && /\s/.test(s)
  && !/^M\d/.test(s) && !/[\s:(\-·]$/.test(s) && !/\)\:/.test(s); // exclou camins SVG i fragments que després se'ls enganxa una dada (els cobreixen els patrons)

test('tots els textos de les vistes tenen traducció a castellà i anglès', () => {
  const trEs = carrega('es'), trEn = carrega('en');
  const fitxers = fs.readdirSync(arrel).filter((f) => /^(views-.*|app|util)\.js$/.test(f));
  const sensePas = [];
  for (const f of fitxers) {
    for (const s of literals(fs.readFileSync(path.join(arrel, f), 'utf8')).filter(esText)) {
      if (IGUALS.has(s)) continue;
      if ((trEs(s) === s && !trEs.te(s)) || (trEn(s) === s && !trEn.te(s))) sensePas.push(`${f}: ${s}`);
    }
  }
  assert.deepEqual(sensePas.slice(0, 400), [], `${sensePas.length} textos sense traduir`);
});
