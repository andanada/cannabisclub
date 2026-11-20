'use strict';
// Mòdul 8: pestanyes d'estadístiques, sense «Distribució per gènere», amb els nous informes i sense estils en línia.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const llegeix = (f) => fs.readFileSync(path.join(__dirname, '..', f), 'utf8');

test('8: pestanyes Rendibilitat per producte i Resum mensual; el gènere ja no hi és', () => {
  const est = llegeix('views-estadistiques.js'), nou = llegeix('views-estadistiques-resum.js');
  assert.match(est, /\['rendibilitat', 'Rendibilitat per producte', statRendibilitat\]/);
  assert.match(est, /\['resum', 'Resum mensual', statResum\]/);
  assert.doesNotMatch(est, /Distribució per gènere/);
  assert.match(est, /Top 10 socis que vénen més sovint/);
  assert.ok(est.indexOf('Top 10 socis que vénen més sovint') < est.indexOf("'Nous socis per mes'"), 'nous socis per mes va més avall');
  assert.match(nou, /window\.print\(\)/);
  assert.match(nou, /resum-mensual\.csv/);
  assert.doesNotMatch(nou, /style:|setAttribute\('style'/);
  assert.match(llegeix('index.html'), /views-estadistiques-resum\.js/);
});
