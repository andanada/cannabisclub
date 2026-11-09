'use strict';
// Un apòstrof dins d'una cadena amb cometa simple trenca tot el fitxer (SyntaxError) i
// la vista deixa de carregar. Aquesta prova detecta qualsevol .js del front mal format.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const dir = path.join(__dirname, '..');
const fitxers = fs.readdirSync(dir).filter((f) => f.endsWith('.js'));

test('hi ha fitxers .js al front', () => {
  assert.ok(fitxers.length > 5);
});

for (const f of fitxers) {
  test(`node --check ${f}`, () => {
    const r = spawnSync(process.execPath, ['--check', path.join(dir, f)], { encoding: 'utf8' });
    assert.strictEqual(r.status, 0, r.stderr);
  });
}
