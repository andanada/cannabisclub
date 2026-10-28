'use strict';
// Carnets: creador (genera el codi, el imprimeix amb codi de barres i, si es pot, el grava en una etiqueta NFC)
// i configuració del lector. Un carnet nou substitueix l'anterior del soci.

// ---------- Codi de barres Code 128 (conjunt B, tot ASCII imprimible) ----------
const CODE128 = ['212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213', '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
  '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211', '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
  '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331', '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
  '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214', '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
  '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141', '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
  '114131', '311141', '411131', '211412', '211214', '211232'];
const CODE128_STOP = '2331112';

// Retorna la llista d'amples alternats barra/espai del text (inici B + dades + control + final).
function code128Widths(text) {
  if (!/^[\x20-\x7e]+$/.test(text)) throw new Error('El codi de barres només admet caràcters ASCII visibles');
  const values = [104];
  let sum = 104;
  [...text].forEach((c, i) => { const v = c.charCodeAt(0) - 32; values.push(v); sum += v * (i + 1); });
  values.push(sum % 103);
  return values.map((v) => CODE128[v]).join('') + CODE128_STOP;
}

// SVG del codi de barres (sense estils en línia). `mòdul` és l'amplada d'una barra mínima.
function barcodeSvg(text) {
  const widths = code128Widths(text);
  const NS = 'http://www.w3.org/2000/svg';
  const quiet = 10;
  const total = [...widths].reduce((a, w) => a + Number(w), 0) + quiet * 2;
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${total} 40`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('class', 'barcode');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Codi de barres ' + text);
  let x = quiet;
  [...widths].forEach((w, i) => {
    const n = Number(w);
    if (i % 2 === 0) {
      const r = document.createElementNS(NS, 'rect');
      r.setAttribute('x', x); r.setAttribute('y', 0); r.setAttribute('width', n); r.setAttribute('height', 40); r.setAttribute('fill', '#000');
      svg.append(r);
    }
    x += n;
  });
  return svg;
}

// ---------- Lector: perfil ----------
async function readerProfile() {
  try {
    const l = await api(`/locals/${S.local}/dispositius?kind=lector`);
    return (l.find((p) => p.per_defecte) || l[0] || { config: null }).config;
  } catch (_) { return null; }
}

// Normalitza una lectura segons el perfil del lector (treu el prefix, passa a majúscules, comprova la longitud).
function normalizeScan(text, cfg) {
  let c = String(text || '').trim();
  if (cfg && cfg.prefix && c.startsWith(cfg.prefix)) c = c.slice(cfg.prefix.length);
  if (!cfg || cfg.majuscules !== false) c = c.toUpperCase();
  if (cfg && c.length < cfg.longitud_min) throw new Error(`Lectura massa curta (mínim ${cfg.longitud_min} caràcters). Torna-ho a provar.`);
  return c;
}

// ---------- Creador de carnets ----------

function printableCard(member, codi, photoSrc) {
  const nom = h('div', { class: 'nom' }, member.nom);
  return h('div', { class: 'print-area' }, h('div', { class: 'carnet-print' },
    photoSrc ? h('img', { src: photoSrc, alt: '' }) : h('div'),
    h('div', null, nom, h('div', null, 'Soci núm. ' + member.id), h('div', null, 'Local ' + (localActual() ? localActual().nom : ''))),
    barcodeSvg(codi), h('div', { class: 'codi-text' }, codi)));
}

async function cardCreator() {
  const out = h('div');
  const result = h('div');
  const doc = h('input', { placeholder: 'DNI / NIE / passaport', autocapitalize: 'characters', autocomplete: 'off' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cercar soci');
  const cfg = await readerProfile();
  return h('div', null, h('div', { class: 'steps' }, h('span', { class: 'pill', 'aria-current': 'step' }, '1 · Triar el soci'), h('span', { class: 'pill' }, '2 · Generar'), h('span', { class: 'pill' }, '3 · Imprimir o gravar')),
    h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        const m = await api(`/locals/${S.local}/socis/cerca?document=${encodeURIComponent(doc.value.trim())}`);
        result.replaceChildren(memberCardStep(m, cfg));
      });
    } }, h('h3', null, 'Soci'), field('Document del soci', doc), h('div', { class: 'actions' }, btn), out), result);
}

function memberCardStep(m, cfg) {
  const out = h('div');
  const area = h('div');
  const gen = h('button', { class: 'primary', type: 'button' }, m.te_carnet ? 'Generar un carnet nou (substitueix l\'actual)' : 'Generar carnet');
  gen.addEventListener('click', () => guard(gen, out, async () => {
    if (m.te_carnet && !confirm('Aquest soci ja té un carnet. El nou el substituirà i l\'antic deixarà de servir. Continuar?')) return;
    const r = await api(`/socis/${m.id}/carnet/generar`, { method: 'POST', body: { prefix: (cfg && cfg.prefix_generat) || 'CLB' } });
    m.te_carnet = true;
    let photo = null;
    if (m.te_foto) { try { const f = await api(`/socis/${m.id}/foto`); photo = `data:${f.mime};base64,${f.image_base64}`; } catch (_) { /* sense foto */ } }
    area.replaceChildren(h('div', { class: 'card' }, h('h3', null, 'Carnet generat'),
      msg('ok', 'Aquest codi només es mostra ara (al servidor només en queda l\'empremta). Imprimeix-lo o grava\'l abans de sortir d\'aquesta pantalla.'),
      h('div', { class: 'secret' }, r.codi), printableCard(m, r.codi, photo), cardOutputs(r.codi, cfg)));
    gen.disabled = true;
  }));
  return h('div', { class: 'card' }, h('div', { class: 'big' }, m.nom), h('p', { class: 'muted' }, m.te_carnet ? 'Ja té carnet.' : 'Encara no té carnet.'),
    h('div', { class: 'actions' }, gen), out, area);
}

// Imprimir i, si el navegador ho permet (Chrome a Android, HTTPS), gravar el codi en una etiqueta NFC.
function cardOutputs(codi, cfg) {
  const out = h('div');
  const print = h('button', { class: 'primary', type: 'button' }, 'Imprimir el carnet');
  print.addEventListener('click', () => window.print());
  const bar = h('div', { class: 'actions' }, print);
  if ('NDEFReader' in window) {
    const nfc = h('button', { type: 'button' }, 'Gravar en una etiqueta NFC');
    nfc.addEventListener('click', () => guard(nfc, out, async () => {
      out.replaceChildren(msg('ok', 'Acosta l\'etiqueta NFC al dispositiu…'));
      await new NDEFReader().write({ records: [{ recordType: 'text', data: codi }] });
      out.replaceChildren(msg('ok', 'Etiqueta gravada. Comprova-la llegint-la amb el lector.'));
    }));
    bar.append(nfc);
  } else {
    bar.append(h('span', { class: 'muted' }, 'La gravació NFC només està disponible a Chrome per a Android amb HTTPS.'));
  }
  return h('div', null, bar, out);
}

async function cardsSection() {
  return sections('carnets', [['crear', 'Crear carnet', cardCreator], ['lector', 'Lector', () => deviceSection('lector')]]);
}
