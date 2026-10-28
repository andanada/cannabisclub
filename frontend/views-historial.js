'use strict';
// Historial de la caixa i dels moviments d'estoc amb el botó «Corregir».
// Els registres no s'editen ni s'esborren: una correcció crea un apunt/moviment de contrapartida.

const horaCa = (iso) => new Date(iso).toLocaleString(loc(), { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

// Demana el motiu (mínim 3 caràcters, com exigeix el servidor) i envia la correcció.
async function demanaCorreccio(url, onDone) {
  const nota = (window.prompt('Motiu de la correcció (mínim 3 caràcters):') || '').trim();
  if (!nota) return;
  await api(url, { method: 'POST', body: { nota } });
  toast('Correcció registrada');
  onDone();
}

function historyTable(cols, rows, buit) {
  return h('div', { class: 'card' }, h('table', null,
    h('thead', null, h('tr', null, cols.map(([t, num]) => h('th', { class: num ? 'num' : '' }, t)))),
    h('tbody', null, rows.length ? rows : h('tr', null, h('td', { colspan: cols.length, class: 'muted' }, buit)))));
}

// Apunts de caixa dels últims dies (només responsables).
async function cashHistory(reload) {
  const dia = (d) => new Date(Date.now() + d * 86400000).toLocaleDateString('sv-SE');
  const rows = await api(`/locals/${S.local}/apunts?des=${dia(-2)}&fins=${dia(1)}&limit=60`);
  const out = h('div');
  const files = rows.map((e) => {
    const corregible = e.tipus !== 'correccio' && !e.corregit;
    const btn = corregible ? h('button', { type: 'button' }, 'Corregir') : null;
    if (btn) btn.addEventListener('click', () => guard(btn, out, () => demanaCorreccio(`/caixa/apunts/${e.id}/correccio`, reload)));
    const estat = e.corregit ? h('span', { class: 'pill warn' }, 'corregit') : (e.tipus === 'correccio' ? h('span', { class: 'pill' }, 'correcció') : null);
    return h('tr', null, h('td', null, horaCa(e.ts)), h('td', null, e.tipus, ' ', estat),
      h('td', null, e.concepte || e.categoria || ''), h('td', { class: 'num' }, eur(e.import_cent)), h('td', null, btn));
  });
  return h('div', null, h('h2', null, 'Apunts recents'),
    historyTable([['Hora'], ['Tipus'], ['Concepte'], ['Import', true], ['']], files, 'Cap apunt en els últims dies.'), out);
}

// Moviments d'estoc dels últims dies (només responsables).
async function stockHistory(reload) {
  const dia = (d) => new Date(Date.now() + d * 86400000).toLocaleDateString('sv-SE');
  const rows = await api(`/locals/${S.local}/moviments?des=${dia(-2)}&fins=${dia(1)}&limit=60`);
  const out = h('div');
  const files = rows.map((m) => {
    const corregible = m.tipus !== 'correccio' && !m.corregit;
    const btn = corregible ? h('button', { type: 'button' }, 'Corregir') : null;
    if (btn) btn.addEventListener('click', () => guard(btn, out, () => demanaCorreccio(`/moviments/${m.id}/correccio`, reload)));
    const estat = m.corregit ? h('span', { class: 'pill warn' }, 'corregit') : (m.tipus === 'correccio' ? h('span', { class: 'pill' }, 'correcció') : null);
    return h('tr', null, h('td', null, horaCa(m.ts)), h('td', null, m.tipus, ' ', estat), h('td', null, m.producte),
      h('td', { class: 'num' }, gText(m.grams)), h('td', { class: 'num' }, m.import_cent == null ? '' : eur(m.import_cent)), h('td', null, btn));
  });
  return h('div', null, h('h2', null, 'Moviments recents'),
    historyTable([['Hora'], ['Tipus'], ['Producte'], ['Grams', true], ['Import', true], ['']], files, 'Cap moviment en els últims dies.'), out);
}
