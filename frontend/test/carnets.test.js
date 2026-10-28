'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// views-carnets.js és codi de navegador: només defineix funcions, així que es pot carregar en un context buit.
const src = fs.readFileSync(path.join(__dirname, '..', 'views-carnets.js'), 'utf8');
const { code128Widths, normalizeScan, CODE128 } = vm.runInNewContext(src + '\n({ code128Widths, normalizeScan, CODE128 })', {});

function decode(widths) {
  const body = widths.slice(0, -7);
  const vals = [];
  for (let i = 0; i < body.length; i += 6) vals.push(CODE128.indexOf(body.slice(i, i + 6)));
  return { vals, stop: widths.slice(-7) };
}

test('totes les seqüències de Code 128 sumen 11 mòduls (6 amples) i no es repeteixen', () => {
  assert.equal(CODE128.length, 106);
  assert.ok(CODE128.every((p) => [...p].reduce((a, c) => a + Number(c), 0) === 11));
  assert.equal(new Set(CODE128).size, 106);
});

test('codifica amb inici B, dades i dígit de control correcte, i es pot descodificar', () => {
  const text = 'CLB-0123456789';
  const { vals, stop } = decode(code128Widths(text));
  assert.equal(vals[0], 104);
  assert.deepEqual(vals.slice(1, -1).map((v) => String.fromCharCode(v + 32)).join(''), text);
  const sum = vals.slice(0, -1).reduce((acc, v, i) => acc + (i === 0 ? v : v * i), 0);
  assert.equal(vals.at(-1), sum % 103);
  assert.equal(stop, '2331112');
});

test('rebutja caràcters que no són ASCII visible', () => {
  assert.throws(() => code128Widths('Ñandú'), /ASCII/);
  assert.throws(() => code128Widths(''), /ASCII/);
});

test('normalizeScan: majúscules, prefix del lector i longitud mínima', () => {
  const cfg = { prefix: '#', longitud_min: 6, majuscules: true };
  assert.equal(normalizeScan('  #clb-abc123 ', cfg), 'CLB-ABC123');
  assert.throws(() => normalizeScan('#abc', cfg), /massa curta/);
  assert.equal(normalizeScan('abc', null), 'ABC');
  assert.equal(normalizeScan('abc', { majuscules: false, longitud_min: 3, prefix: '' }), 'abc');
});
