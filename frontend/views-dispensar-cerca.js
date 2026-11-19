'use strict';
// Cerca única de soci (nom, cognoms, DNI/NIE/passaport o carnet RFID) i llista de socis dins del club per ordre d'entrada.
// Compartit per Dispensar i Accés.

// Foto gran i ben visible del soci (la mateixa a totes les pantalles). Es carrega a part; sense foto, la inicial.
function fotoSoci(id, nom, mida) {
  const box = h('div', { class: 'foto-soci', 'aria-hidden': 'true' }, (nom || '?').slice(0, 1).toUpperCase());
  box.style.setProperty('--m', (mida || 64) + 'px');
  api(`/socis/${id}/foto`).then((f) => {
    if (!f || !f.image_base64) return;
    const img = h('img', { src: `data:${f.mime || 'image/jpeg'};base64,${f.image_base64}`, alt: '' });
    box.replaceChildren(img);
  }).catch(() => {});
  return box;
}

const horaEntrada = (iso) => new Date(iso).toLocaleTimeString(loc(), { hour: '2-digit', minute: '2-digit' });

// Cerca un soci amb el que s'hagi escrit o passat pel lector. Torna {m} si n'hi ha un de sol, o {llista} si n'hi ha diversos.
async function cercaSoci(text) {
  const valor = text.trim();
  if (!valor) return { buit: true };
  const codi = normalizeScan(valor, await readerProfile());
  const prova = async (fn) => { try { return await fn(); } catch (e) { return null; } };
  const perCarnet = !/\s/.test(valor) && await prova(() => api(`/locals/${S.local}/socis/carnet`, { method: 'POST', body: { codi } }));
  if (perCarnet) return { m: perCarnet, via: 'carnet' };
  if (!/\s/.test(valor)) {
    const perDoc = await prova(() => api(`/locals/${S.local}/socis/cerca`, { method: 'POST', body: { document: valor } }));
    if (perDoc) return { m: perDoc, via: 'document' };
  }
  const llista = await api(`/locals/${S.local}/socis?q=${encodeURIComponent(valor)}`);
  if (llista.length === 1) return { m: await api(`/socis/${llista[0].id}`), via: 'nom' };
  return { llista };
}

// Caixa de cerca: `onTria(m)` s'executa amb el soci trobat. Mostra la llista de coincidències quan n'hi ha diverses.
function capsaCerca(onTria, extra) {
  const camp = h('input', { class: 'card-input', type: 'search', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false',
    placeholder: 'Nom, cognoms, DNI/NIE/passaport o passa el carnet pel lector', 'aria-label': 'Cercar soci' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cercar');
  let torn = 0;
  const form = h('form', { class: 'card cerca-soci', onsubmit: (e) => {
    e.preventDefault();
    const meva = ++torn;
    const valor = camp.value;
    guard(btn, out, async () => {
      const r = await cercaSoci(valor);
      if (meva !== torn || r.buit) return;
      camp.value = '';
      if (r.m) { await onTria(r.m, r.via); return; }
      out.replaceChildren(r.llista.length ? h('ul', { class: 'llista-acces' }, r.llista.map((s) => {
        const b = h('button', { type: 'button', class: 'fila-acces' }, fotoSoci(s.id, s.nom, 40), h('strong', null, s.nom), h('span', { class: 'muted' }, `[${s.codi}] ${s.estat}`));
        b.addEventListener('click', () => guard(b, out, async () => onTria(await api(`/socis/${s.id}`), 'nom')));
        return h('li', null, b);
      })) : msg('err', 'No s\'ha trobat cap soci amb aquesta cerca.'));
    });
    setTimeout(() => camp.focus(), 0);
  } }, h('div', { class: 'cerca-fila' }, camp, btn), out, extra || null);
  if (window.matchMedia && window.matchMedia('(pointer: fine)').matches) setTimeout(() => { if (document.body.contains(camp)) camp.focus(); }, 0);
  return form;
}

// Llista de socis dins el club (per ordre d'entrada) amb foto gran, hora i avís d'incidències. `onTria(soci)` en prémer una fila.
async function llistaDins(onTria, accioFila) {
  const e = await api(`/locals/${S.local}/acces`);
  const cap = h('div', { class: 'llista-dins-cap' }, h('h3', null, 'Socis al club · per ordre d\'entrada'), h('span', { class: 'pill' }, String(e.dins.length)));
  if (!e.dins.length) return h('div', { class: 'card' }, cap, h('p', { class: 'muted' }, 'Ara mateix no hi ha ningú dins.'));
  return h('div', { class: 'card' }, cap, h('ul', { class: 'llista-dins' }, e.dins.map((s) => {
    const fila = h('button', { type: 'button', class: 'fila-dins' }, fotoSoci(s.id, s.nom, 56),
      h('div', { class: 'fila-dins-nom' }, h('strong', null, s.nom), h('span', { class: 'muted' }, `[${s.codi}] ${s.tipus}`)),
      h('span', { class: 'fila-dins-hora' }, horaEntrada(s.entrada)),
      s.incidencia ? h('span', { class: 'pill warn' }, '⚠ Incidència') : h('span'));
    fila.addEventListener('click', () => onTria(s));
    return h('li', null, h('div', { class: 'fila-dins-box' }, fila, accioFila ? accioFila(s) : null));
  })));
}

VIEWS.dispensar = async () => {
  const arrel = h('div');
  const inici = async () => {
    arrel.replaceChildren(pageHead('Dispensar', 'Busca el soci o tria\'l de la llista dels que són dins.'),
      capsaCerca(async (m) => obreDispensacio(m)),
      await llistaDins(async (s) => obreDispensacio(await api(`/socis/${s.id}`))));
  };
  const obreDispensacio = async (m) => arrel.replaceChildren(await pantallaDispensar(m, inici));
  await inici();
  return arrel;
};
