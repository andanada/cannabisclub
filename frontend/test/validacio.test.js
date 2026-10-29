'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { validaDocument, edatDe, validaNaixement, validaCorreu, validaTelefon } = require('../validacio.js');

test('DNI i NIE amb lletra de control, i passaport', () => {
  assert.deepEqual(validaDocument('12345678Z'), { ok: true, tipus: 'dni', text: 'DNI vàlid' });
  assert.deepEqual(validaDocument(' 1234 5678 z '), { ok: true, tipus: 'dni', text: 'DNI vàlid' });
  assert.equal(validaDocument('12345678A').ok, false);
  assert.equal(validaDocument('12345678A').text, 'La lletra de control no és correcta');
  assert.deepEqual(validaDocument('X1234567L'), { ok: true, tipus: 'nie', text: 'NIE vàlid' });
  assert.equal(validaDocument('X1234567A').ok, false);
  assert.equal(validaDocument('AB123456').tipus, 'passaport');
  assert.equal(validaDocument('ab').ok, false);
  assert.equal(validaDocument('12-34').ok, false);
  assert.equal(validaDocument('').text, '');
});

test('edat i majoria d\'edat', () => {
  const avui = new Date(2026, 9, 29); // 29/10/2026
  assert.equal(edatDe('2008-10-29', avui), 18);
  assert.equal(edatDe('2008-10-30', avui), 17);
  assert.equal(edatDe('1990-01-01', avui), 36);
  assert.equal(edatDe('2026-02-30', avui), null);
  assert.equal(edatDe('abc', avui), null);
  assert.deepEqual(validaNaixement('2008-10-29', avui), { ok: true, text: '18 anys' });
  assert.equal(validaNaixement('2008-10-30', avui).ok, false);
  assert.equal(validaNaixement('1800-01-01', avui).text, 'Data no vàlida');
  assert.equal(validaNaixement('', avui).ok, false);
});

test('correu i telèfon opcionals', () => {
  assert.equal(validaCorreu('').ok, true);
  assert.equal(validaCorreu('a@b.cat').ok, true);
  assert.equal(validaCorreu('a@b').ok, false);
  assert.equal(validaTelefon('').ok, true);
  assert.equal(validaTelefon('+34 600 11 22 33').ok, true);
  assert.equal(validaTelefon('12345').ok, false);
});
