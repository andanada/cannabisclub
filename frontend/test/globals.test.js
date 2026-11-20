'use strict';
// Tots els scripts comparteixen l'àmbit global: dos `const`/`let`/`class` amb el mateix nom a fitxers diferents donen
// SyntaxError al navegador i la pantalla sencera deixa de carregar (node --check un a un no ho veu).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script[^>]*\ssrc="\/?([^"?]+\.js)/g)].map((m) => m[1]).filter((f) => fs.existsSync(path.join(dir, f)));

test('cap declaració global lexical repetida entre scripts', () => {
  const vist = new Map();
  const dups = [];
  for (const f of scripts) {
    const src = fs.readFileSync(path.join(dir, f), 'utf8');
    for (const m of src.matchAll(/^(?:const|let|class)\s+([A-Za-z_$][\w$]*)/gm)) {
      if (vist.has(m[1]) && vist.get(m[1]) !== f) dups.push(`${m[1]}: ${vist.get(m[1])} i ${f}`);
      else vist.set(m[1], f);
    }
  }
  assert.deepStrictEqual(dups, []);
});
