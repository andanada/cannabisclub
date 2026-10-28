'use strict';
// Regles de dispensació (subpantalla d'Estoc): límit de gramatge per soci i període.
// Es comproven en dispensar; només l'administrador les crea i les edita.

const PERIODES_REGLA = [['dia', 'Per dia'], ['setmana', 'Per setmana'], ['mes', 'Per mes']];
const periodeText = (v) => (PERIODES_REGLA.find(([k]) => k === v) || [v, v])[1];

const reglaAmbit = (r, prods) => {
  if (r.ambit === 'tot') return 'Tots els productes';
  if (r.ambit === 'categoria') return 'Categoria: ' + r.categoria;
  const p = prods.find((x) => x.id === r.product_id);
  return 'Producte: ' + (p ? p.nom : '#' + r.product_id);
};

function reglaCard(r, prods, esAdmin, reload) {
  const out = h('div');
  const actions = h('div', { class: 'actions' });
  if (esAdmin) {
    const toggle = h('button', { type: 'button', class: 'small ' + (r.actiu ? 'danger' : '') }, r.actiu ? 'Desactivar' : 'Reactivar');
    toggle.addEventListener('click', () => guard(toggle, out, async () => {
      await api(`/regles/${r.id}`, { method: 'PUT', body: { actiu: !r.actiu } });
      toast(r.actiu ? 'Regla desactivada' : 'Regla reactivada');
      reload();
    }));
    actions.append(toggle);
  }
  return h('div', { class: 'card' },
    h('div', null, h('strong', null, r.nom), ' ', h('span', { class: 'pill ' + (r.actiu ? 'ok' : 'warn') }, r.actiu ? 'activa' : 'inactiva')),
    h('p', { class: 'muted' }, `Màxim ${r.max_g} g per soci · ${periodeText(r.periode)} · ${reglaAmbit(r, prods)}`),
    actions, out);
}

function reglaForm(prods, reload) {
  const nom = h('input');
  const max = h('input', { inputmode: 'decimal', placeholder: '5' });
  const periode = h('select', null, PERIODES_REGLA.map(([v, t]) => h('option', { value: v }, t)));
  const ambit = h('select', null, [['tot', 'Tots els productes'], ['categoria', 'Una categoria'], ['producte', 'Un producte']].map(([v, t]) => h('option', { value: v }, t)));
  const categoria = h('input', { placeholder: 'flor, resina…' });
  const producte = h('select', null, prods.filter((p) => p.actiu).map((p) => h('option', { value: p.id }, p.nom)));
  const catField = field('Categoria', categoria), prodField = field('Producte', producte);
  const mostra = () => { catField.hidden = ambit.value !== 'categoria'; prodField.hidden = ambit.value !== 'producte'; };
  ambit.addEventListener('change', mostra);
  mostra();
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear regla');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const g = parseGrams(max.value);
      const body = { nom: nom.value.trim(), ambit: ambit.value, periode: periode.value, max_g: g };
      if (ambit.value === 'categoria') body.categoria = categoria.value.trim();
      if (ambit.value === 'producte') body.product_id = Number(producte.value);
      await api(`/locals/${S.local}/regles`, { method: 'POST', body });
      toast('Regla creada');
      reload();
    });
  } }, h('h3', null, 'Nova regla'), h('div', { class: 'row' }, field('Nom', nom), field('Màxim per soci (g)', max), field('Període', periode)),
  h('div', { class: 'row' }, field("S'aplica a", ambit), catField, prodField),
  h('div', { class: 'actions' }, btn), out);
}

async function rulesSection() {
  const [llista, prods] = await Promise.all([api(`/locals/${S.local}/regles`), api(`/locals/${S.local}/productes`)]);
  const esAdmin = S.me.role === 'admin';
  const reload = () => show('estoc');
  return h('div', null,
    h('p', { class: 'lead' }, 'Les regles limiten el gramatge que un soci pot rebre en un període. Si una dispensació en supera alguna, no es permet. Les correccions alliberen gramatge.'),
    ...(esAdmin ? [reglaForm(prods, reload)] : [h('p', { class: 'muted' }, 'Només un administrador pot crear o canviar regles.')]),
    h('h3', null, 'Regles existents'),
    ...(llista.length ? llista.map((r) => reglaCard(r, prods, esAdmin, reload)) : [h('div', { class: 'card empty' }, 'Encara no hi ha cap regla.')]));
}
