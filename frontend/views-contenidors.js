'use strict';
// Contenidors i tipus de contenidor (subpantalles d'Estoc).
// Un tipus defineix la tara; cada contenidor té un codi, el producte que conté i l'últim pes brut (el net surt de restar la tara).

async function containerTypesSection() {
  const llista = await api(`/locals/${S.local}/tipus-contenidor`);
  const nom = h('input', { placeholder: 'Pot, bossa, caixa…' });
  const tara = h('input', { inputmode: 'decimal', placeholder: '12,5' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear tipus');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/tipus-contenidor`, { method: 'POST', body: { nom: nom.value.trim(), tara_g: parseGrams(tara.value) } });
      toast('Tipus creat');
      show('estoc');
    });
  } }, h('h3', null, 'Nou tipus de contenidor'), h('div', { class: 'row' }, field('Nom', nom), field('Tara (g)', tara)), h('div', { class: 'actions' }, btn), out);
  const card = (t) => {
    const o = h('div');
    const toggle = h('button', { type: 'button', class: 'small ' + (t.actiu ? 'danger' : '') }, t.actiu ? 'Desactivar' : 'Reactivar');
    toggle.addEventListener('click', () => guard(toggle, o, async () => {
      await api(`/tipus-contenidor/${t.id}`, { method: 'PUT', body: { actiu: !t.actiu } });
      show('estoc');
    }));
    return h('div', { class: 'card' }, h('div', null, h('strong', null, t.nom), ' ', h('span', { class: 'pill ' + (t.actiu ? 'ok' : 'warn') }, t.actiu ? 'actiu' : 'inactiu')),
      h('p', { class: 'muted' }, `Tara: ${t.tara_g} g`), h('div', { class: 'actions' }, toggle), o);
  };
  return h('div', null, form, h('h3', null, 'Tipus existents'),
    ...(llista.length ? llista.map(card) : [h('div', { class: 'card empty' }, 'Encara no hi ha cap tipus de contenidor.')]));
}

function containerRow(c, reload) {
  const brut = h('input', { inputmode: 'decimal', value: c.brut_g ?? '', placeholder: '0,0', 'aria-label': 'Pes brut: ' + c.codi });
  const out = h('span', { class: 'muted' });
  const desa = async () => {
    try {
      const v = brut.value.trim();
      await api(`/contenidors/${c.id}`, { method: 'PUT', body: { brut_g: v === '' ? null : parseGrams(v) } });
      reload();
    } catch (e) { out.textContent = e.message; }
  };
  brut.addEventListener('change', desa);
  brut.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); desa(); } });
  const buida = h('button', { type: 'button', class: 'small' }, 'Buidar');
  buida.addEventListener('click', async () => {
    try { await api(`/contenidors/${c.id}`, { method: 'PUT', body: { brut_g: null, product_id: null } }); reload(); } catch (e) { out.textContent = e.message; }
  });
  return h('tr', null, h('td', null, h('strong', null, c.codi)), h('td', null, c.tipus + ' (' + c.tara_g + ' g)'), h('td', null, c.producte || '—'),
    h('td', null, brut), h('td', null, c.net_g === null ? '—' : c.net_g + ' g'), h('td', null, buida, ' ', out));
}

async function containersSection() {
  const [llista, tipus, prods] = await Promise.all([api(`/locals/${S.local}/contenidors`), api(`/locals/${S.local}/tipus-contenidor`), api(`/locals/${S.local}/productes`)]);
  const reload = () => show('estoc');
  const codi = h('input', { placeholder: 'C-001' });
  const tp = h('select', null, tipus.filter((t) => t.actiu).map((t) => h('option', { value: t.id }, `${t.nom} (${t.tara_g} g)`)));
  const pr = h('select', null, h('option', { value: '' }, '— cap —'), ...prods.filter((p) => p.actiu).map((p) => h('option', { value: p.id }, p.nom)));
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear contenidor');
  const form = tipus.some((t) => t.actiu)
    ? h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        await api(`/locals/${S.local}/contenidors`, { method: 'POST', body: { codi: codi.value.trim(), type_id: Number(tp.value), product_id: pr.value ? Number(pr.value) : null } });
        toast('Contenidor creat');
        reload();
      });
    } }, h('h3', null, 'Nou contenidor'), h('div', { class: 'row' }, field('Codi', codi), field('Tipus', tp), field('Producte (opcional)', pr)), h('div', { class: 'actions' }, btn), out)
    : h('div', { class: 'card empty' }, "Primer crea un tipus de contenidor a la subpantalla «Tipus de contenidor».");
  const taula = h('table', null, h('thead', null, h('tr', null, ['Codi', 'Tipus', 'Producte', 'Pes brut (g)', 'Net', ''].map((t) => h('th', null, t)))),
    h('tbody', null, llista.map((c) => containerRow(c, reload))));
  return h('div', null, form, h('h3', null, 'Contenidors'),
    llista.length ? h('div', { class: 'card table-wrap' }, taula) : h('div', { class: 'card empty' }, 'Encara no hi ha cap contenidor.'));
}
