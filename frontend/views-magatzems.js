'use strict';
// Magatzems (subpantalla d'Estoc): el principal és on es dispensa; la resta guarden estoc que es mou amb traspassos.

function warehouseCard(w, reload) {
  const out = h('div');
  const actions = h('div', { class: 'actions' });
  if (!w.principal) {
    const nom = h('input', { value: w.nom, 'aria-label': 'Nom del magatzem' });
    const desa = h('button', { type: 'button', class: 'small' }, 'Canviar nom');
    desa.addEventListener('click', () => guard(desa, out, async () => {
      await api(`/magatzems/${w.id}`, { method: 'PUT', body: { nom: nom.value.trim() } });
      toast('Magatzem actualitzat');
      reload();
    }));
    const toggle = h('button', { type: 'button', class: 'small ' + (w.actiu ? 'danger' : '') }, w.actiu ? 'Desactivar' : 'Reactivar');
    toggle.addEventListener('click', () => guard(toggle, out, async () => {
      await api(`/magatzems/${w.id}`, { method: 'PUT', body: { actiu: !w.actiu } });
      reload();
    }));
    actions.append(nom, desa, toggle);
  }
  return h('div', { class: 'card' }, h('div', null, h('strong', null, w.nom), ' ',
    h('span', { class: 'pill ' + (w.actiu ? 'ok' : 'warn') }, w.principal ? 'on es dispensa' : (w.actiu ? 'actiu' : 'inactiu'))), actions, out);
}

function transferForm(files, magatzems, reload) {
  const actius = magatzems.filter((m) => m.actiu);
  const opt = (m) => h('option', { value: m.id ?? '' }, m.nom);
  const prod = h('select', null, files.map((f) => h('option', { value: f.product_id }, f.nom)));
  const de = h('select', null, actius.map(opt));
  const a = h('select', null, actius.map(opt));
  if (actius.length > 1) a.selectedIndex = 1;
  const g = h('input', { inputmode: 'decimal', placeholder: '0,000' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Traspassar');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api('/moviments/traspas', { method: 'POST', body: { product_id: Number(prod.value), de: de.value === '' ? null : Number(de.value), a: a.value === '' ? null : Number(a.value), grams: parseGrams(g.value) } });
      toast('Traspàs fet');
      reload();
    });
  } }, h('h3', null, 'Traspàs entre magatzems'),
  h('div', { class: 'row' }, field('Producte', prod), field('Origen', de), field('Destí', a), field('Grams', g)), h('div', { class: 'actions' }, btn), out);
}

async function warehousesSection() {
  const [magatzems, files] = await Promise.all([api(`/locals/${S.local}/magatzems`), api(`/locals/${S.local}/magatzems/estoc`)]);
  const reload = () => show('estoc');
  const nom = h('input', { placeholder: 'Safata, armari, càmera…' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear magatzem');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/magatzems`, { method: 'POST', body: { nom: nom.value.trim() } });
      toast('Magatzem creat');
      reload();
    });
  } }, h('h3', null, 'Nou magatzem'), field('Nom', nom), h('div', { class: 'actions' }, btn), out);
  const actius = magatzems.filter((m) => m.actiu);
  const cap = h('tr', null, h('th', null, 'Producte'), ...actius.map((m) => h('th', null, m.nom)));
  const cos = files.map((f) => h('tr', null, h('td', null, f.nom), ...actius.map((m) => {
    const e = f.estocs.find((x) => x.magatzem_id === m.id);
    return h('td', null, (e ? e.g : '0') + ' g');
  })));
  return h('div', null,
    h('p', { class: 'lead' }, "L'estoc del magatzem principal és el que es pot dispensar. La resta s'hi mou amb traspassos."),
    ...(actius.length > 1 && files.length ? [transferForm(files, magatzems, reload)] : []),
    h('div', { class: 'card table-wrap' }, h('table', null, h('thead', null, cap), h('tbody', null, cos))),
    form, h('h3', null, 'Magatzems'), ...magatzems.map((w) => warehouseCard(w, reload)));
}
