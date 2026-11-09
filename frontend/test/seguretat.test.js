'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '..');
const fonts = fs.readdirSync(dir).filter((f) => f.endsWith('.js') && !f.startsWith('i18n'));
const text = (f) => fs.readFileSync(path.join(dir, f), 'utf8');

test('cap vista envia el document ni el codi del carnet a la URL', () => {
  for (const f of fonts) {
    assert.doesNotMatch(text(f), /socis\/cerca\?|socis\/carnet\?/, f);
  }
});

test('la fitxa del dispensador no assumeix document ni telèfon', () => {
  const v = text('views-dispensar.js');
  assert.doesNotMatch(v, /m\.document \+/);
  assert.match(v, /m\.document \?/);
});

test('els PIN nous es demanen de 6 a 8 xifres', () => {
  assert.doesNotMatch(text('views-admin.js'), /4 a 8 xifres/);
});
