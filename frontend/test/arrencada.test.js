// Els scripts (defer) corren amb readyState 'interactive': arrencar abans de DOMContentLoaded executa boot() sense les vistes (configItems is not defined).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

test("app.js no arrenca amb readyState 'loading' (es perd amb defer) sinó amb 'complete' o DOMContentLoaded", () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
  assert.ok(!/readyState === 'loading'/.test(src), "no s'ha de comparar amb 'loading'");
  assert.ok(/readyState === 'complete'\) arrenca\(\); else document\.addEventListener\('DOMContentLoaded', arrenca\)/.test(src));
});
