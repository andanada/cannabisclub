'use strict';
// Errors de taulell: botons que envien formularis sense voler, cerca amb dades velles, estils que la CSP bloqueja.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dir = path.join(__dirname, '..');
const text = (f) => fs.readFileSync(path.join(dir, f), 'utf8');
const fonts = fs.readdirSync(dir).filter((f) => f.endsWith('.js') && !f.startsWith('i18n'));

// DOM mínim: prou per executar h() d'util.js.
function carregaUtil() {
  const el = (tag) => ({ tag, attrs: {}, kids: [], listeners: {}, className: '',
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, f) { this.listeners[k] = f; }, append(...k) { this.kids.push(...k); } });
  const ctx = { document: { createElement: el, createTextNode: (t) => ({ nodeType: 3, text: t }), querySelector: () => null },
    sessionStorage: { getItem: () => null, setItem() {} } };
  vm.createContext(ctx);
  vm.runInContext(text('util.js') + '\nthis.h = h; this.guardTots = typeof guardTots === "function" ? guardTots : null;', ctx);
  return ctx;
}

test('un botó sense «type» no envia mai el formulari on és (type=button per defecte)', () => {
  const { h } = carregaUtil();
  assert.equal(h('button', { onclick() {} }, 'Tria').attrs.type, 'button');
  assert.equal(h('button', null, 'Tria').attrs.type, 'button');
  assert.equal(h('button', { type: 'submit' }, 'Envia').attrs.type, 'submit');
  assert.equal(h('div', null).attrs.type, undefined);
});

test('guardTots desactiva tots els botons mentre dura l\'acció i els torna a activar', async () => {
  const { guardTots } = carregaUtil();
  assert.equal(typeof guardTots, 'function');
  const a = { disabled: false }, b = { disabled: false }, c = { disabled: false };
  const out = { replaceChildren() {} };
  let durant = null;
  await guardTots([a, b, c], out, async () => { durant = [a.disabled, b.disabled, c.disabled]; });
  assert.deepEqual(durant, [true, true, true]);
  assert.deepEqual([a.disabled, b.disabled, c.disabled], [false, false, false]);
  await guardTots([a, b], out, async () => { throw new Error('x'); });   // també després d'un error
  assert.deepEqual([a.disabled, b.disabled], [false, false]);
});

test('la cerca de soci dona prioritat al carnet acabat de passar sobre un document que hagi quedat escrit', () => {
  const { triaCerca } = require('../validacio.js');
  assert.deepEqual(triaCerca('12345678Z', 'ABC123'), { per: 'carnet', valor: 'ABC123' });
  assert.deepEqual(triaCerca('', ' ABC123 '), { per: 'carnet', valor: 'ABC123' });
  assert.deepEqual(triaCerca(' 12345678z ', ''), { per: 'document', valor: '12345678z' });
  assert.deepEqual(triaCerca(' ', ''), { per: null, valor: '' });
});

test('Dispensar: els tres botons es bloquegen junts i la cerca buida els dos camps', () => {
  const v = text('views-dispensar.js');
  assert.match(v, /guardTots\(\[btnEfectiu, btnTargeta, btnBizum, btnMoneder, btnRegal, btnApart\]/);
  assert.match(v, /triaCerca\(doc\.value, carnet\.value\)/);
  assert.match(v, /doc\.value = ''/);
});

test('cap vista passa «style» a h(): la CSP (style-src self) bloqueja els estils en línia', () => {
  // («style: 'currency'» és una opció d'Intl.NumberFormat, no un atribut)
  for (const f of fonts) assert.doesNotMatch(text(f), /\bstyle: ?['"`](?!currency)/, f);
});

test('l\'entrada amb carnet es pot enviar amb l\'Intro del lector (cal un botó d\'enviament al formulari)', () => {
  const a = text('app.js');
  const form = a.slice(a.indexOf("class: 'auth-carnet'"));
  assert.match(form.slice(0, form.indexOf("fetch('/auth/opcions')")), /type: 'submit'/);
});

test('assignar un carnet normalitza la lectura igual que la cerca', () => {
  assert.match(text('views-socis.js'), /socis\/\$\{m\.id\}\/carnet`[^\n]*normalizeScan/);
});

test('dispensació, quota i despesa envien una referència d\'operació (client_ref) creada en preparar el formulari', () => {
  const d = text('views-dispensar.js'), g = text('views-gestio.js');
  assert.equal((d.match(/const ref = novaRef\(\)/g) || []).length, 2);
  assert.match(d, /body = \{ client_ref: ref, member_id/);
  assert.match(d, /quotes`, \{ method: 'POST', body: \{ client_ref: ref/);
  assert.match(g, /'\/despeses', \{ method: 'POST', body: \{ client_ref: ref/);
  const { novaRef } = (() => { const c = { document: { querySelector: () => null }, sessionStorage: { getItem: () => null } }; vm.createContext(c); vm.runInContext(text('util.js') + '\nthis.novaRef = novaRef;', c); return c; })();
  const a = novaRef(), b = novaRef();
  assert.match(a, /^[A-Za-z0-9-]{16,64}$/);   // el mateix patró que valida el servidor
  assert.notEqual(a, b);
});

test('el service worker: totes les pàgines i fitxers de l\'aplicació hi són, no n\'hi ha de fantasma, i no desa errors', () => {
  const sw = text('sw.js');
  const shell = [...sw.match(/const SHELL = \[([^\]]*)\]/)[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
  const idx = text('index.html');
  const usats = [...idx.matchAll(/(?:src|href)="(\/[^"#?]+)"/g)].map((m) => m[1]);
  for (const u of usats) assert.ok(shell.includes(u), `index.html usa ${u} i no és a la SHELL de sw.js`);
  for (const u of shell) assert.ok(u === '/' || fs.existsSync(path.join(dir, u.slice(1))), `sw.js llista ${u} i no existeix`);
  assert.match(sw, /if \(r\.ok && r\.type === 'basic'\)/);
});

test('hi ha avís de versió nova quan canvia el service worker, i només es recarrega si ho demana l usuari', () => {
  const a = text('app.js');
  assert.match(a, /controllerchange/);
  assert.match(a, /jaTeControlador/);
  assert.equal((a.match(/location\.reload\(\)/g) || []).length, 1);                  // l'únic reload és el del botó
  assert.match(a, /onclick: \(\) => location\.reload\(\)/);
});

test('el PIN del carnet no es deixa omplir pel gestor de contrasenyes (omplia l usuari al camp del carnet)', () => {
  const a = text('app.js');
  assert.match(a, /pin-input', type: 'password', inputmode: 'numeric', autocomplete: 'new-password'/);
});
