'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '..');
const text = (f) => fs.readFileSync(path.join(dir, f), 'utf8');

test('el menú Gestió ha desaparegut i Configuració el substitueix per a la gerència', () => {
  const app = text('app.js');
  assert.doesNotMatch(app, /\['gestio', 'Gestió'/);
  assert.doesNotMatch(app, /VIEWS\.gestio/);
  assert.doesNotMatch(app, /estoc-avancat/);
  assert.match(app, /\['config', 'Configuració', isManager,/);
});

test('el que es treu de la UI (9.1) ja no té pantalla', () => {
  const cfg = text('views-config.js') + text('views-stock-inventari.js');
  for (const r of [/monedesSection/, /VIEWS\['estoc-avancat'\]/, /priceLinesSection\s*\]/, /warehousesSection\s*\]/, /containersSection\s*\]/, /containerTypesSection\s*\]/, /rulesSection\s*\]/]) assert.doesNotMatch(cfg, r);
  assert.doesNotMatch(text('views-gastos.js'), /secComptes|'comptabilitat'/);
  assert.doesNotMatch(text('views-club.js'), /VIEWS\.club|'Límits per soci'/);
});

test('9.2: categories, gastos, controls (llibres, lots) i privacitat passen a Configuració', () => {
  const c = text('views-config.js');
  for (const id of ['categories', 'gastos', 'controls', 'rgpd', 'seguretat', 'local']) assert.match(c, new RegExp(`\\['${id}',`));
  assert.match(c, /\['lots', 'Lots i traçabilitat'/);
  assert.match(c, /\['llibres', 'Llibres'/);
  assert.match(c, /Excepcions de límit per soci/);   // els límits per soci queden només a Local i límits
});

test('els treballadors no veuen cap opció de configuració i l\'encarregat només la seva part', () => {
  const c = text('views-config.js');
  assert.match(c, /return isManager\(\) \? items\.filter/);
  assert.match(c, /: \[\];/);
  const enc = c.match(/CONFIG_ENCARREGAT = \[([^\]]*)\]/)[1];
  for (const id of ['usuaris', 'bascules', 'quotes', 'normes', 'local']) assert.doesNotMatch(enc, new RegExp(`'${id}'`));
  for (const id of ['gastos', 'controls', 'categories', 'rgpd']) assert.match(enc, new RegExp(`'${id}'`));
});

test('el menú de Descomptes del treballador amb privilegi es conserva', () => {
  const app = text('app.js');
  assert.match(app, /\['descomptes', 'Descomptes', \(\) => !isManager\(\) && !!S\.me\.pot_editar_descomptes\]/);
  assert.match(app, /VIEWS_EXTRA = \['compte', 'descomptes'\]/);
  assert.match(text('views-gestio.js'), /VIEWS\.descomptes = /);
});

test('9.4: Gastos té «Pendents de revisió» i ja no mostra comptes comptables', () => {
  const g = text('views-gastos.js');
  assert.match(g, /\['pendents', 'Pendents de revisió', secPendents\]/);
  assert.match(g, /gastos\/pendents/);
  assert.match(g, /\/revisio/);
  assert.doesNotMatch(g, /Compte comptable|gastos\/comptes/);
});

test('Mòdul 6: l\'entrada d\'estoc envia el preu pagat per aquella entrada', () => {
  const e = text('views-stock-existencies.js');
  assert.match(e, /cost_cent: cost\.value\.trim\(\) \? parseEur\(cost\.value\) : null/);
  assert.match(e, /Preu pagat per aquesta entrada/);
  assert.match(text('views-club.js'), /cost_cent: c && c\.trim\(\)/);
});

test('Usuaris: els rols parlen del rol del dia i de l\'accés complet', () => {
  const a = text('views-admin.js'), c = text('views-config.js');
  assert.match(a, /Recepció \/ Dispensari/);
  assert.match(c, /rol del dia/);
  assert.match(c, /accés complet/);
});

test('Donacions i Monedero: la distinció és als textos', () => {
  const c = text('views-config.js');
  assert.match(c, /Donacions: els diners que donen els socis/);
  assert.match(c, /Monedero: la part del perfil de cada soci/);
});
