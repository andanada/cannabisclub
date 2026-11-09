'use strict';
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
  return vm.runInContext('({ tr })', ctx);
}

test('les vistes noves de privacitat i controls són JavaScript vàlid', () => {
  for (const f of ['views-rgpd.js', 'views-club.js', 'views-alta.js']) new vm.Script(fs.readFileSync(path.join(arrel, f), 'utf8'), { filename: f });
});

test('les vistes noves estan enllaçades a index.html i al service worker', () => {
  const idx = fs.readFileSync(path.join(arrel, 'index.html'), 'utf8'), sw = fs.readFileSync(path.join(arrel, 'sw.js'), 'utf8');
  for (const f of ['/views-rgpd.js', '/views-club.js']) {
    assert.ok(idx.includes(f), `index.html: ${f}`);
    assert.ok(sw.includes(f), `sw.js: ${f}`);
  }
});

test('textos de privacitat i controls traduïts a castellà i anglès', () => {
  const es = carrega('es').tr, en = carrega('en').tr;
  assert.equal(es('Retenció de dades'), 'Retención de datos');
  assert.equal(en('Lots i traçabilitat'), 'Batches and traceability');
  assert.equal(es('El soci està pendent d\'aprovació per un gestor'), 'El socio está pendiente de aprobación por un gestor');
  assert.equal(en('El soci ja està suprimit'), 'The member has already been erased');
});

test('patrons amb dades: el servidor diu «calen N dies» i els noms de soci no es toquen', () => {
  const es = carrega('es').tr, en = carrega('en').tr;
  assert.equal(es('El soci encara està en el període d\'espera (7 dies des de l\'alta)'), 'El socio todavía está en el periodo de espera (7 días desde el alta)');
  assert.equal(en('Bloquejat per la política de conservació: calen 365 dies des de la baixa'), 'Blocked by the retention policy: 365 days since leaving are required');
  assert.equal(es('Traçabilitat del lot L-001'), 'Trazabilidad del lote L-001');
  assert.equal(es('Excepcions de límit · Anna Prova'), 'Excepciones de límite · Anna Prova');
});
