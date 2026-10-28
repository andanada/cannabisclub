'use strict';
// Descomptes (subpantalla d'Estoc): crear-los, veure'ls i activar-los o desactivar-los.
// Es trien en dispensar; el descompte aplicat queda registrat a la dispensació.

const valorText = (d) => (d.tipus === 'percent' ? `${d.valor} %` : `${eur(d.valor)} per gram`);
const ambitText = (d, prods) => {
  if (d.ambit === 'tot') return 'Tots els productes';
  if (d.ambit === 'categoria') return 'Categoria: ' + d.categoria;
  const p = prods.find((x) => x.id === d.product_id);
  return 'Producte: ' + (p ? p.nom : '#' + d.product_id);
};

function discountCard(d, prods, reload) {
  const out = h('div');
  const toggle = h('button', { type: 'button', class: 'small ' + (d.actiu ? 'danger' : '') }, d.actiu ? 'Desactivar' : 'Reactivar');
  toggle.addEventListener('click', () => guard(toggle, out, async () => {
    await api(`/descomptes/${d.id}`, { method: 'PUT', body: { actiu: !d.actiu } });
    toast(d.actiu ? 'Descompte desactivat' : 'Descompte reactivat');
    reload();
  }));
  const vigencia = d.inici || d.fi ? `${d.inici || '…'} → ${d.fi || '…'}` : 'Sense data límit';
  return h('div', { class: 'card' },
    h('div', null, h('strong', null, d.nom), ' ', h('span', { class: 'pill ' + (d.actiu ? 'ok' : 'warn') }, d.actiu ? 'actiu' : 'inactiu')),
    h('p', { class: 'muted' }, valorText(d), ' · ', ambitText(d, prods), ' · ', vigencia),
    h('div', { class: 'actions' }, toggle), out);
}

async function discountsSection() {
  const [llista, prods] = await Promise.all([api(`/locals/${S.local}/descomptes?tots=1`), api(`/locals/${S.local}/productes`)]);
  const reload = () => show('estoc');
  const nom = h('input');
  const tipus = h('select', null, [['percent', 'Percentatge (%)'], ['import_g', 'Import per gram (€)']].map(([v, t]) => h('option', { value: v }, t)));
  const valor = h('input', { inputmode: 'decimal', placeholder: '10' });
  const ambit = h('select', null, [['tot', 'Tots els productes'], ['categoria', 'Una categoria'], ['producte', 'Un producte']].map(([v, t]) => h('option', { value: v }, t)));
  const categoria = h('input', { placeholder: 'flor, resina…' });
  const producte = h('select', null, prods.filter((p) => p.actiu).map((p) => h('option', { value: p.id }, p.nom)));
  const inici = h('input', { type: 'date' }), fi = h('input', { type: 'date' });
  const catField = field('Categoria', categoria), prodField = field('Producte', producte);
  const mostra = () => { catField.hidden = ambit.value !== 'categoria'; prodField.hidden = ambit.value !== 'producte'; };
  ambit.addEventListener('change', mostra);
  mostra();
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear descompte');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const v = tipus.value === 'percent' ? parseInt(valor.value.trim(), 10) : parseEur(valor.value);
      if (!Number.isInteger(v)) throw new Error('El valor no és vàlid');
      const body = { nom: nom.value.trim(), tipus: tipus.value, valor: v, ambit: ambit.value, inici: inici.value || null, fi: fi.value || null };
      if (ambit.value === 'categoria') body.categoria = categoria.value.trim();
      if (ambit.value === 'producte') body.product_id = Number(producte.value);
      await api(`/locals/${S.local}/descomptes`, { method: 'POST', body });
      toast('Descompte creat');
      reload();
    });
  } }, h('h3', null, 'Nou descompte'), h('div', { class: 'row' }, field('Nom', nom), field('Tipus', tipus), field('Valor', valor)),
  h('div', { class: 'row' }, field('S\'aplica a', ambit), catField, prodField),
  h('div', { class: 'row' }, field('Vigent des de (opcional)', inici), field('Vigent fins a (opcional)', fi)),
  h('div', { class: 'actions' }, btn), out);
  return h('div', null, h('p', { class: 'lead' }, "Els descomptes es trien en dispensar. No es poden acumular i l'import descomptat queda registrat."), form,
    h('h3', null, 'Descomptes existents'), ...(llista.length ? llista.map((d) => discountCard(d, prods, reload)) : [h('div', { class: 'card empty' }, 'Encara no hi ha cap descompte.')]));
}
