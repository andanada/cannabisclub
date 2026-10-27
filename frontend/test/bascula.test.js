'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parsePesLine, Bascula } = require('../bascula.js');

test('format OHAUS estable, inestable, net i brut', () => {
  assert.deepEqual(pick(parsePesLine('      2.500 g')), { mg: 2500, unit: 'g', stable: true, mode: null });
  assert.deepEqual(pick(parsePesLine('      2.481 g ?')), { mg: 2481, unit: 'g', stable: false, mode: null });
  assert.deepEqual(pick(parsePesLine('     12.34 g   N')), { mg: 12340, unit: 'g', stable: true, mode: 'N' });
  assert.deepEqual(pick(parsePesLine('     12.34 g ? G')), { mg: 12340, unit: 'g', stable: false, mode: 'G' });
});
test('unitats i coma decimal', () => {
  assert.equal(parsePesLine('0,750 kg').mg, 750000);
  assert.equal(parsePesLine('1500 mg').mg, 1500);
  assert.equal(parsePesLine('1 oz').mg, 28350);
  assert.equal(parsePesLine('-0.020 g').mg, -20);
  assert.equal(parsePesLine('5.000').unit, 'g');          // sense unitat: s'assumeix grams
});
test('unitat no suportada i línies que no són pes', () => {
  assert.throws(() => parsePesLine('3.0 pcs'), /no suportada/);
  assert.equal(parsePesLine('Err'), null);
  assert.equal(parsePesLine('ES'), null);
  assert.equal(parsePesLine(''), null);
});

function pick(p) { return { mg: p.mg, unit: p.unit, stable: p.stable, mode: p.mode }; }

// Port sèrie simulat: respon a «IP» amb la seqüència que se li dona.
function fakeSerial(responses, opts) {
  const o = opts || {};
  const sent = [];
  let ctrl; let i = 0;
  const enc = new TextEncoder(); const dec = new TextDecoder();
  const readable = new ReadableStream({ start(c) { ctrl = c; } });
  const writable = new WritableStream({ write(chunk) {
    const cmd = dec.decode(chunk).trim(); sent.push(cmd);
    if (cmd === 'IP') {
      const r = responses[Math.min(i++, responses.length - 1)];
      if (o.split) { ctrl.enqueue(enc.encode(r.slice(0, 5))); setTimeout(() => ctrl.enqueue(enc.encode(r.slice(5) + '\r\n')), 5); }
      else ctrl.enqueue(enc.encode(r + '\r\n'));
    }
  } });
  const port = { readable, writable, async open() {}, async close() { try { ctrl.close(); } catch (_) {} } };
  return { serial: { async requestPort() { return port; } }, sent };
}

test('readStable espera a que el pes sigui estable', async () => {
  const f = fakeSerial(['   2.481 g ?', '   2.497 g ?', '   2.500 g']);
  const b = new Bascula({ serial: f.serial }); await b.connect();
  const r = await b.readStable({ pollMs: 30, timeoutMs: 2000 });
  assert.equal(r.mg, 2500); assert.equal(r.stable, true);
  assert.deepEqual(f.sent, ['IP', 'IP', 'IP']);
  await b.disconnect();
});

test('readStable falla si mai s\'estabilitza', async () => {
  const f = fakeSerial(['   2.481 g ?']);
  const b = new Bascula({ serial: f.serial }); await b.connect();
  await assert.rejects(b.readStable({ pollMs: 20, timeoutMs: 200 }), /no s'estabilitza/);
  await b.disconnect();
});

test('línia trencada en dos blocs es recompon', async () => {
  const f = fakeSerial(['   7.250 g'], { split: true });
  const b = new Bascula({ serial: f.serial }); await b.connect();
  assert.equal((await b.readStable({ pollMs: 60, timeoutMs: 2000 })).mg, 7250);
  await b.disconnect();
});

test('unitat no suportada es notifica en lloc de donar un pes erroni', async () => {
  const f = fakeSerial(['   3.000 pcs']);
  const b = new Bascula({ serial: f.serial }); await b.connect();
  await assert.rejects(b.readStable({ pollMs: 20, timeoutMs: 300 }), /no suportada/);
  await b.disconnect();
});

test('tara i zero envien les ordres T i Z; sense connexió falla', async () => {
  const f = fakeSerial(['1 g']);
  const b = new Bascula({ serial: f.serial });
  await assert.rejects(b.send('T'), /no està connectada/);
  await b.connect(); await b.tare(); await b.zero();
  assert.deepEqual(f.sent, ['T', 'Z']);
  await b.disconnect();
});

test('sense Web Serial el missatge és clar', async () => {
  await assert.rejects(new Bascula({ serial: null }).connect(), /no admet ports sèrie/);
});
