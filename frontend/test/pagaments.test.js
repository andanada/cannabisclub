'use strict';
// Pagaments i caixa: mètodes segons l'ajust del local, tancament amb fons/billets/monedes, foto gran al check-in, Dispensar per a recepció.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dir = path.join(__dirname, '..');
const text = (f) => fs.readFileSync(path.join(dir, f), 'utf8');

function carregaMetodes(locals) {
  const ctx = { S: { me: { locals }, local: 1 }, h: (tag, attrs, ...fills) => ({ tag, attrs, fills }), obreModal() {}, fotoSoci() {} };
  vm.createContext(ctx);
  vm.runInContext(text('views-caixa-pagaments.js') + '\nthis.metodesIngres = metodesIngres;', ctx);
  return (o) => [...ctx.metodesIngres(o)].map((x) => x.attrs.value);
}

test('targeta i Bizum només es poden triar si el local els accepta; els crèdits només a la quota', () => {
  assert.deepEqual(carregaMetodes([{ id: 1 }])(), ['efectiu']);
  assert.deepEqual(carregaMetodes([{ id: 1, targeta_activa: true }])(), ['efectiu', 'targeta', 'bizum']);
  assert.deepEqual(carregaMetodes([{ id: 1, targeta_activa: false }])({ monedero: true }), ['efectiu', 'monedero']);
  assert.deepEqual(carregaMetodes([{ id: 1, targeta_activa: true }])({ monedero: true }), ['efectiu', 'targeta', 'bizum', 'monedero']);
});

test('el tancament de caixa envia fons, billets i monedes i hi ha un sol closeForm', () => {
  const c = text('views-caixa-pagaments.js');
  assert.match(c, /fons_cent: eurOpt\(fons\.value\), billets_cent: eurOpt\(billets\.value\), monedes_cent: eurOpt\(monedes\.value\)/);
  assert.match(c, /fons_darrer_cent/);   // el fons per defecte és l'últim deixat
  assert.match(c, /window\.print\(\)/);  // fulla del TPV imprimible
  assert.doesNotMatch(text('views-gestio.js'), /function closeForm/);
  assert.match(text('views-gestio.js'), /closeForm\]/);
});

test('quota i donacions trien el mètode amb metodesIngres (quota: també crèdits del compte)', () => {
  assert.match(text('views-dispensar.js'), /metodesIngres\(\{ monedero: true \}\)/);
  assert.match(text('views-dispensar.js'), /metodesIngres\(\)\);\s*\n\s*const btn = h\('button', \{ class: 'primary', type: 'submit' \}, 'Afegir donació'\)/);
  assert.match(text('views-acces.js'), /metodesIngres\(\{ monedero: true \}\)/);
});

test('el check-in obre la foto del soci en gran', () => {
  assert.match(text('views-acces.js'), /fotoGranModal\(m\)/);
  assert.match(text('views-caixa-pagaments.js'), /fotoSoci\(m\.id, m\.nom, 320\)/);
});

test('recepció veu Dispensar al menú i hi troba només les no genètiques', () => {
  const a = text('app.js');
  assert.match(a, /const potDispensar = \(\) => potRecepcio\(\) \|\| potDispensari\(\)/);
  assert.match(a, /\['dispensar', 'Dispensar', potDispensar\]/);
  assert.match(text('views-dispensar-carret.js'), /!potDispensari\(\)/);
});

test('el fitxer nou és a index.html i al service worker, i no usa estils en línia', () => {
  assert.match(text('index.html'), /\/views-caixa-pagaments\.js/);
  assert.match(text('sw.js'), /\/views-caixa-pagaments\.js/);
  assert.doesNotMatch(text('views-caixa-pagaments.js'), /\bstyle: ?['"`]/);
});
