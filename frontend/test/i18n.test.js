'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Carrega els diccionaris i i18n.js en un context de navegador simulat amb l'idioma indicat.
function carrega(lang) {
  const ctx = {
    localStorage: { getItem: () => lang, setItem() {} }, navigator: { language: lang },
    document: { documentElement: {}, addEventListener() {}, title: '' }, MutationObserver: class { observe() {} },
    location: { reload() {} }, confirm: () => true, prompt: () => '', alert: () => {},
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const f of ['i18n-es.js', 'i18n-en.js', 'i18n.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '..', f), 'utf8'), ctx, { filename: f });
  return vm.runInContext('({ tr, LANG, I18N, loc })', ctx);
}

test('el català es deixa tal com està', () => {
  const { tr, LANG } = carrega('ca');
  assert.equal(LANG, 'ca');
  assert.equal(tr('Desar'), 'Desar');
});

test('castellà: textos exactes, espais de les vores i dades enganxades', () => {
  const { tr, loc } = carrega('es');
  assert.equal(tr('Desar'), 'Guardar');
  assert.equal(tr('  Desar '), '  Guardar ');
  assert.equal(tr('Soci núm. 5'), 'Socio n.º 5');
  assert.equal(tr('Estoc: 120 g'), 'Stock: 120 g');
  assert.equal(tr('Límits per soci · Local Central'), 'Límites por socio · Local Central');
  assert.equal(tr('Falten traços: n\'hi ha 1 i en calen 3.'), 'Faltan trazos: hay 1 y se necesitan 3.');
  assert.equal(loc(), 'es-ES');
});

test('anglès: missatges del servidor amb dades', () => {
  const { tr, loc } = carrega('en');
  assert.equal(tr('Estoc insuficient'), 'Insufficient stock');
  assert.equal(tr('El local 7 no existeix'), 'Venue 7 does not exist');
  assert.equal(tr('«prefix» ha de tenir com a màxim 8 caràcters visibles'), '"prefix" must have at most 8 visible characters');
  assert.equal(tr('Supera el límit diari del soci'), "Exceeds the member's daily limit");
  assert.equal(loc(), 'en-GB');
});

test('no toca les dades de l\'usuari (noms de locals, productes, socis)', () => {
  for (const lang of ['es', 'en']) {
    const { tr } = carrega(lang);
    for (const dada of ['Local Central', 'Local Nord', 'Amnesia', 'Anna Prova', 'Hash Marroc']) assert.equal(tr(dada), dada, `${lang}: ${dada}`);
  }
});

test('castellà i anglès tenen exactament les mateixes claus i patrons, sense buits', () => {
  const es = carrega('es').I18N, en = carrega('en').I18N;
  assert.deepEqual(Object.keys(es.es).sort(), Object.keys(es.en).sort());
  assert.ok(Object.keys(es.es).length > 300);
  assert.deepEqual(es.pat.es.map((p) => p[0].source), es.pat.en.map((p) => p[0].source));
  for (const lang of ['es', 'en']) {
    assert.ok(Object.values(es[lang]).every((v) => v.trim()), `${lang}: hi ha traduccions buides`);
    assert.ok(es.pat[lang].every(([, t]) => t.trim()));
  }
});

test('els idiomes desconeguts cauen al català', () => {
  assert.equal(carrega('fr').LANG, 'ca');
});
