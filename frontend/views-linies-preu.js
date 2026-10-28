'use strict';
// Línies de preu (subpantalla d'Estoc): llistes de preus per gram alternatives (p. ex. «VIP») que s'assignen als socis.
// Un producte sense preu a la línia es cobra al preu base.

let liniaPreuOberta = null;

function priceRow(lid, r, refresh) {
  const input = h('input', { inputmode: 'decimal', value: r.preu_cent === null ? '' : (r.preu_cent / 100).toFixed(2).replace('.', ','), placeholder: (r.base_cent / 100).toFixed(2).replace('.', ',') });
  const out = h('span', { class: 'muted' });
  const desa = async () => {
    try {
      if (input.value.trim() === '') {
        if (r.preu_cent !== null) await api(`/linies-preu/${lid}/preus/${r.product_id}`, { method: 'DELETE' });
      } else {
        await api(`/linies-preu/${lid}/preus/${r.product_id}`, { method: 'PUT', body: { preu_cent_per_g: parseEur(input.value) } });
      }
      refresh();
    } catch (e) { out.textContent = e.message; }
  };
  input.addEventListener('change', desa);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); desa(); } });
  const pill = r.preu_cent === null ? h('span', { class: 'pill' }, 'preu base') : h('span', { class: 'pill ok' }, 'propi');
  return h('tr', null, h('td', null, r.nom), h('td', null, eur(r.base_cent) + '/g'), h('td', null, input), h('td', null, pill, ' ', out));
}

async function priceLineDetail(lid) {
  const root = h('div');
  const pinta = async () => {
    const d = await api(`/linies-preu/${lid}`);
    const out = h('div');
    const enrere = h('button', { type: 'button' }, '← Línies de preu');
    enrere.addEventListener('click', () => { liniaPreuOberta = null; show('estoc'); });
    const toggle = h('button', { type: 'button', class: 'small ' + (d.actiu ? 'danger' : '') }, d.actiu ? 'Desactivar' : 'Reactivar');
    toggle.addEventListener('click', () => guard(toggle, out, async () => {
      await api(`/linies-preu/${lid}`, { method: 'PUT', body: { actiu: !d.actiu } });
      toast(d.actiu ? 'Línia desactivada' : 'Línia reactivada');
      pinta();
    }));
    const taula = h('table', null, h('thead', null, h('tr', null, ['Producte', 'Preu base', 'Preu de la línia (€/g)', ''].map((t) => h('th', null, t)))),
      h('tbody', null, d.preus.map((r) => priceRow(lid, r, pinta))));
    root.replaceChildren(h('div', { class: 'card' }, h('h3', null, d.nom, ' ', h('span', { class: 'pill ' + (d.actiu ? 'ok' : 'warn') }, d.actiu ? 'activa' : 'inactiva')),
      h('p', { class: 'muted' }, 'Escriu el preu per gram que pagarà un soci d\'aquesta línia. Deixa-ho buit per cobrar el preu base.'),
      h('div', { class: 'actions' }, enrere, toggle), out), h('div', { class: 'card table-wrap' }, taula));
  };
  await pinta();
  return root;
}

async function priceLinesSection() {
  if (liniaPreuOberta) return priceLineDetail(liniaPreuOberta);
  const llista = await api(`/locals/${S.local}/linies-preu`);
  const nom = h('input', { placeholder: 'VIP, Estudiants…' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear línia');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api(`/locals/${S.local}/linies-preu`, { method: 'POST', body: { nom: nom.value.trim() } });
      liniaPreuOberta = r.id;
      show('estoc');
    });
  } }, h('h3', null, 'Nova línia de preu'), h('p', { class: 'muted' }, 'Una línia és una llista de preus per gram diferent de la base. Després l\'assignes als socis des de la seva fitxa.'),
  field('Nom', nom), h('div', { class: 'actions' }, btn), out);
  const card = (l) => {
    const obre = h('button', { type: 'button', class: 'small' }, 'Editar preus');
    obre.addEventListener('click', () => { liniaPreuOberta = l.id; show('estoc'); });
    return h('div', { class: 'card' }, h('div', null, h('strong', null, l.nom), ' ', h('span', { class: 'pill ' + (l.actiu ? 'ok' : 'warn') }, l.actiu ? 'activa' : 'inactiva')),
      h('p', { class: 'muted' }, `${l.productes} productes amb preu propi · ${l.socis} socis`), h('div', { class: 'actions' }, obre));
  };
  return h('div', null, form, h('h3', null, 'Línies existents'),
    ...(llista.length ? llista.map(card) : [h('div', { class: 'card empty' }, 'Encara no hi ha cap línia de preu.')]));
}

// A la fitxa del soci: triar-li la línia de preu.
async function memberPriceLine(m, out, reload) {
  const [actual, llista] = await Promise.all([api(`/socis/${m.id}/linia-preu`), api(`/locals/${S.local}/linies-preu`)]);
  const sel = h('select', null, h('option', { value: '' }, 'Preu base (cap línia)'),
    ...llista.filter((l) => l.actiu || l.id === actual.price_line_id).map((l) => h('option', { value: l.id, selected: l.id === actual.price_line_id }, l.nom)));
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Desar');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/socis/${m.id}/linia-preu`, { method: 'PUT', body: { price_line_id: sel.value ? Number(sel.value) : null } });
      toast('Línia de preu desada');
      reload();
    });
  } }, field('Línia de preu', sel), h('div', { class: 'actions' }, btn));
}
