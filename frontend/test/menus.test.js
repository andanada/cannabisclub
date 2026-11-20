'use strict';
// Menú del club: paginació de la carta, preus, QR i que les vistes no usen estils en línia.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '..');
const text = (f) => fs.readFileSync(path.join(dir, f), 'utf8');
const P = require('../pantalla.js');
const QR = require('../qr.js');

const prods = (n, unitat = 'g') => Array.from({ length: n }, (_, i) => ({ nom: 'P' + i, unitat, disponible: true, preu_cent: 1000 }));
const dades = (cats, extra = {}) => ({ disseny: { mida: 3, orientacio: 'h', columnes: 2, trams: [1, 5, 10], ...extra }, categories: cats });

test('els preus es calculen per tram i es formaten en euros', () => {
  assert.equal(P.preu(1000), '10 €');
  assert.equal(P.preu(1050), '10,50 €');
  assert.equal(P.preuTram({ preu_cent: 1250 }, 5), '62,50 €');
  assert.equal(P.preu(null), '');
});

test('la paginació reparteix en columnes i pàgines, repeteix la capçalera i no perd cap producte', () => {
  const pg = P.paginar(dades([{ nom: 'Weed', productes: prods(30) }, { nom: 'Hash', productes: prods(5) }]));
  assert.ok(pg.length >= 2);
  const files = pg.flat().flat().filter((x) => x.t === 'fila');
  assert.equal(files.length, 35);
  for (const col of pg.flat()) assert.equal(col[0].t, 'cat');   // cap columna comença per un producte sense categoria
  assert.ok(pg.every((p) => p.length <= 2));
});

test('una sola columna i lletra gran donen més pàgines que dues columnes i lletra petita', () => {
  const cats = [{ nom: 'Weed', productes: prods(24) }];
  assert.ok(P.paginar(dades(cats, { columnes: 1, mida: 5 })).length > P.paginar(dades(cats, { columnes: 2, mida: 1 })).length);
  assert.equal(P.paginar(dades([])).length, 0);
});

test('el QR té mida de versió vàlida i els tres quadrats de cerca', () => {
  const m = QR.matriu('https://club.exemple.test/pantalla/' + 'a'.repeat(32));
  assert.ok([21, 25, 29, 33, 37, 41].includes(m.length));
  for (const [x, y] of [[0, 0], [m.length - 7, 0], [0, m.length - 7]]) assert.ok(m[y][x] && m[y + 3][x + 3] && !m[y + 1][x + 1]);
  assert.throws(() => QR.matriu('x'.repeat(400)));
});

test('les vistes del menú no usen estils en línia, no carreguen res extern i són a index.html i al service worker', () => {
  for (const f of ['views-menus.js', 'views-menus-pantalles.js', 'pantalla.js', 'qr.js']) {
    assert.doesNotMatch(text(f), /\bstyle: ?['"`]|setAttribute\(['"]style|innerHTML|https?:\/\/(?!www\.w3\.org)/, f);
  }
  for (const f of ['/views-menus.js', '/views-menus-pantalles.js', '/qr.js', '/pantalla.js', '/pantalla.css']) {
    assert.ok(text('index.html').includes(f) && text('sw.js').includes(f), f);
  }
  assert.match(text('app.js'), /'menus', 'Menú del club', \(\) => te\('menus'\)/);
});
