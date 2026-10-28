'use strict';
// Inventari (subpantalla d'Estoc): recompte guiat producte a producte.
// En tancar, l'estoc s'ajusta a la quantitat comptada (un moviment d'ajust per producte amb diferència).

const diffText = (d) => (d === null ? '' : (Number(d) > 0 ? '+' : '') + d + ' g');
const diffClass = (d) => (d === null ? '' : Number(d) === 0 ? 'ok' : 'warn');

function countRow(sid, l, refresh) {
  const input = h('input', { inputmode: 'decimal', value: l.comptat_g ?? '', placeholder: l.esperat_g, 'aria-label': 'Comptat: ' + l.nom });
  const badge = h('span', { class: 'pill ' + diffClass(l.diferencia_g) }, l.diferencia_g === null ? 'sense comptar' : diffText(l.diferencia_g));
  const out = h('span', { class: 'muted' });
  const desa = async () => {
    if (input.value.trim() === '' || input.value.trim() === (l.comptat_g ?? '')) return;
    try {
      const g = parseGrams(input.value);
      await api(`/inventaris/${sid}/linies/${l.product_id}`, { method: 'PUT', body: { grams: g } });
      refresh();
    } catch (e) { out.textContent = e.message; }
  };
  input.addEventListener('change', desa);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); desa(); } });
  return h('tr', null, h('td', null, l.nom, l.categoria ? h('div', { class: 'muted' }, l.categoria) : ''), h('td', null, l.esperat_g + ' g'),
    h('td', null, input), h('td', null, badge, ' ', out));
}

async function openInventory(sid) {
  const root = h('div');
  const pinta = async () => {
    const d = await api(`/inventaris/${sid}`);
    const out = h('div');
    const tanca = h('button', { class: 'primary', type: 'button' }, 'Tancar i ajustar estoc');
    tanca.addEventListener('click', () => guard(tanca, out, async () => {
      const faltenCount = d.total - d.comptats;
      if (!window.confirm(`S'ajustarà l'estoc dels ${d.comptats} productes comptats.` + (faltenCount ? ` ${faltenCount} productes sense comptar no es toquen.` : ''))) return;
      const r = await api(`/inventaris/${sid}/tancar`, { method: 'POST' });
      toast(`Inventari tancat: ${r.ajustos} ajustos`);
      show('estoc');
    }));
    const cancela = h('button', { type: 'button', class: 'danger' }, 'Cancel·lar inventari');
    cancela.addEventListener('click', () => guard(cancela, out, async () => {
      await api(`/inventaris/${sid}/cancelar`, { method: 'POST' });
      toast('Inventari cancel·lat');
      show('estoc');
    }));
    const taula = h('table', null, h('thead', null, h('tr', null, ['Producte', 'Esperat', 'Comptat (g)', 'Diferència'].map((t) => h('th', null, t)))),
      h('tbody', null, d.linies.map((l) => countRow(sid, l, pinta))));
    root.replaceChildren(h('div', { class: 'card' }, h('h3', null, d.nom), h('p', { class: 'muted' }, `${d.comptats} de ${d.total} productes comptats`),
      h('div', { class: 'actions' }, tanca, cancela), out), h('div', { class: 'card table-wrap' }, taula));
  };
  await pinta();
  return root;
}

async function inventorySection() {
  const llista = await api(`/locals/${S.local}/inventaris`);
  const obert = llista.find((x) => x.estat === 'obert');
  if (obert) return openInventory(obert.id);
  const nom = h('input', { placeholder: 'Inventari de ' + new Date().toLocaleDateString() });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Començar inventari');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/inventaris`, { method: 'POST', body: { nom: nom.value.trim() || null } });
      show('estoc');
    });
  } }, h('h3', null, 'Nou inventari'), h('p', { class: 'muted' }, "Compta cada producte i, en tancar, l'estoc s'ajusta a la quantitat comptada. Els productes que no comptis no es toquen."),
  field('Nom (opcional)', nom), h('div', { class: 'actions' }, btn), out);
  const estats = { 'tancat': 'ok', 'cancel·lat': 'warn' };
  return h('div', null, form, h('h3', null, 'Inventaris anteriors'),
    ...(llista.length ? llista.map((x) => h('div', { class: 'card' }, h('strong', null, x.nom), ' ', h('span', { class: 'pill ' + (estats[x.estat] || '') }, x.estat),
      h('p', { class: 'muted' }, `${x.comptats} productes comptats · ${new Date(x.ts_obert).toLocaleString()}`)))
      : [h('div', { class: 'card empty' }, "Encara no s'ha fet cap inventari.")]));
}
