'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { analyzeScale, analyzeKeystrokes, analyzePointer, browserSupport } = require('../diagnostic.js');
const { parsePesLine } = require('../bascula.js');

test('bàscula: pes estable en la unitat del perfil = tot correcte', () => {
  const r = analyzeScale(['   12.50 g  '], { unit: 'g' }, parsePesLine);
  assert.equal(r.ok, true);
  assert.equal(r.reading.mg, 12500);
  assert.deepEqual(r.checks.map((c) => c.id), ['rebut', 'pes', 'unitat', 'estable']);
});

test('bàscula: sense resposta, resposta que no és un pes, unitat diferent i lectura inestable', () => {
  assert.equal(analyzeScale([], { unit: 'g' }, parsePesLine).checks[0].ok, false);
  const brossa = analyzeScale(['ERR 12 BAD'], { unit: 'g' }, parsePesLine);
  assert.equal(brossa.ok, false);
  assert.equal(brossa.checks.find((c) => c.id === 'pes').ok, false);
  const unitat = analyzeScale(['0.45 kg'], { unit: 'g' }, parsePesLine);
  assert.equal(unitat.checks.find((c) => c.id === 'unitat').ok, false);
  const inestable = analyzeScale(['10.0 g ?'], { unit: 'g' }, parsePesLine);
  assert.equal(inestable.checks.find((c) => c.id === 'estable').ok, false);
  assert.equal(inestable.ok, false);
});

const teclat = (text, gap, fi) => {
  const keys = [...text].map((c, i) => ({ key: c, t: i * gap }));
  if (fi) keys.push({ key: fi, t: text.length * gap });
  return keys;
};

test('lector: ritme ràpid + terminador correcte = reconegut', () => {
  const r = analyzeKeystrokes(teclat('CLB-ABC123', 8, 'Enter'), { terminador: 'enter', longitud_min: 4, prefix: '' });
  assert.equal(r.ok, true);
  assert.equal(r.code, 'CLB-ABC123');
});

test('lector: escrit a mà (lent), terminador equivocat, prefix absent i codi curt', () => {
  const lent = analyzeKeystrokes(teclat('CLB-ABC123', 300, 'Enter'), { terminador: 'enter', longitud_min: 4 });
  assert.equal(lent.checks.find((c) => c.id === 'velocitat').ok, false);
  const tab = analyzeKeystrokes(teclat('CLB-ABC123', 8, 'Enter'), { terminador: 'tab', longitud_min: 4 });
  assert.equal(tab.checks.find((c) => c.id === 'terminador').ok, false);
  const prefix = analyzeKeystrokes(teclat('ABC12345', 8, 'Enter'), { terminador: 'enter', prefix: '#', longitud_min: 4 });
  assert.equal(prefix.checks.find((c) => c.id === 'prefix').ok, false);
  const curt = analyzeKeystrokes(teclat('AB1', 8, 'Enter'), { terminador: 'enter', longitud_min: 4 });
  assert.equal(curt.ok, false);
  assert.equal(analyzeKeystrokes([], {}).ok, false);
});

test('lector: el prefix del lector s\'ignora en la longitud i en el codi', () => {
  const r = analyzeKeystrokes(teclat('#CLB-1234', 8, 'Enter'), { terminador: 'enter', prefix: '#', longitud_min: 8 });
  assert.equal(r.code, 'CLB-1234');
  assert.equal(r.ok, true);
});

const traç = (n, pointerType, pressure) => Array.from({ length: n }, (_, i) => (
  i === 0 ? { type: 'down', pointerType, pressure } : { type: 'move', pointerType, pressure }));

test('tauleta: traços suficients i moviment continu', () => {
  const ev = [...traç(15, 'mouse', 0.5), ...traç(15, 'mouse', 0.5)];
  assert.equal(analyzePointer(ev, { tracos_min: 2, pressio: false }).ok, true);
  assert.equal(analyzePointer(ev.slice(0, 15), { tracos_min: 2 }).ok, false);
  assert.equal(analyzePointer([{ type: 'down', pointerType: 'touch' }], { tracos_min: 1 }).checks.find((c) => c.id === 'moviment').ok, false);
});

test('tauleta: un llapis sense pressió es detecta quan el perfil la demana', () => {
  const sense = analyzePointer(traç(20, 'pen', 0), { tracos_min: 1, pressio: true });
  assert.equal(sense.checks.find((c) => c.id === 'pressio').ok, false);
  const amb = analyzePointer(traç(20, 'pen', 0.6), { tracos_min: 1, pressio: true });
  assert.equal(amb.ok, true);
  assert.equal(amb.pressure, true);
});

test('capacitats del navegador', () => {
  assert.deepEqual(browserSupport({ serial: {}, nfc: false, secure: true, pointer: true }), { serial: true, nfc: false, secure: true, pointer: true });
  assert.deepEqual(browserSupport(null), { serial: false, nfc: false, secure: false, pointer: false });
});
