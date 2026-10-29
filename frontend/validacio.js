'use strict';
// Validacions d'un soci a la pantalla (resposta immediata). El servidor torna a validar-ho tot: això només és ajuda per a qui escriu.

const LLETRES_DNI = 'TRWAGMYFPDXBNJZSQVHLCKE';

// Torna {ok, tipus, text}. tipus: 'dni' | 'nie' | 'passaport' | null
function validaDocument(valor) {
  const doc = String(valor || '').replace(/\s+/g, '').toUpperCase();
  if (!doc) return { ok: false, tipus: null, text: '' };
  let numero = null;
  let tipus = null;
  if (/^\d{8}[A-Z]$/.test(doc)) { numero = parseInt(doc.slice(0, 8), 10); tipus = 'dni'; }
  else if (/^[XYZ]\d{7}[A-Z]$/.test(doc)) { numero = parseInt('XYZ'.indexOf(doc[0]) + doc.slice(1, 8), 10); tipus = 'nie'; }
  else if (/^[A-Z0-9]{5,20}$/.test(doc)) return { ok: true, tipus: 'passaport', text: 'Passaport o altre document' };
  else return { ok: false, tipus: null, text: 'Només lletres i xifres (DNI, NIE o passaport)' };
  if (LLETRES_DNI[numero % 23] !== doc[8]) return { ok: false, tipus, text: 'La lletra de control no és correcta' };
  return { ok: true, tipus, text: tipus === 'dni' ? 'DNI vàlid' : 'NIE vàlid' };
}

// Edat en anys complerts a la data `avui` (per defecte, avui). Torna null si la data no és vàlida.
function edatDe(naixement, avui) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(naixement || ''));
  if (!m) return null;
  const [, a, me, d] = m.map(Number);
  const ref = avui || new Date();
  if (new Date(a, me - 1, d).getMonth() !== me - 1) return null;
  let edat = ref.getFullYear() - a;
  if (ref.getMonth() + 1 < me || (ref.getMonth() + 1 === me && ref.getDate() < d)) edat -= 1;
  return edat;
}

function validaNaixement(valor, avui) {
  if (!valor) return { ok: false, text: '' };
  const edat = edatDe(valor, avui);
  if (edat === null || edat < 0 || edat > 120) return { ok: false, text: 'Data no vàlida' };
  if (edat < 18) return { ok: false, text: 'Ha de ser major d\'edat (' + edat + ' anys)' };
  return { ok: true, text: edat + ' anys' };
}

function validaCorreu(valor) {
  const v = String(valor || '').trim();
  if (!v) return { ok: true, text: '' };
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v) ? { ok: true, text: '' } : { ok: false, text: 'El correu no sembla vàlid' };
}

function validaTelefon(valor) {
  const v = String(valor || '').replace(/[\s.-]/g, '');
  if (!v) return { ok: true, text: '' };
  return /^\+?\d{9,15}$/.test(v) ? { ok: true, text: '' } : { ok: false, text: 'El telèfon ha de tenir de 9 a 15 xifres' };
}

if (typeof module !== 'undefined') module.exports = { validaDocument, edatDe, validaNaixement, validaCorreu, validaTelefon };
