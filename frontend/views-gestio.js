'use strict';
// Pantalles: Estoc, Caixa, Fitxatge. (Informe és a views-informes.js.)

const preuText = (c) => (c / 100).toFixed(2).replace('.', ',');

// Miniatura d'un producte (o una inicial si encara no té foto).
function productThumb(p, size) {
  if (p.imatge) return h('img', { class: 'thumb', src: `data:${p.imatge.mime};base64,${p.imatge.image_base64}`, alt: '', width: size, height: size });
  return h('div', { class: 'thumb vacia', 'aria-hidden': 'true' }, (p.nom || '?').slice(0, 1).toUpperCase());
}

// Foto del producte: es redueix a una miniatura de 96 px abans d'enviar-la (el servidor només n'accepta fins a 30 KB).
function imageRow(p, out) {
  const file = h('input', { type: 'file', accept: 'image/*', hidden: true, 'aria-label': 'Foto del producte' });
  const add = h('button', { type: 'button', class: 'small' }, p.imatge ? 'Canviar foto' : 'Afegir foto');
  add.addEventListener('click', () => file.click());
  file.addEventListener('change', () => guard(add, out, async () => {
    if (!file.files[0]) return;
    const image_base64 = await photoToJpegBase64(file.files[0], 96, 28000);
    await api(`/productes/${p.id}/imatge`, { method: 'PUT', body: { image_base64 } });
    toast('Foto desada');
    show('estoc');
  }));
  const items = [productThumb(p, 56), add, file];
  if (p.imatge) {
    const del = h('button', { type: 'button', class: 'small danger' }, 'Treure foto');
    del.addEventListener('click', () => guard(del, out, async () => { await api(`/productes/${p.id}/imatge`, { method: 'DELETE' }); toast('Foto esborrada'); show('estoc'); }));
    items.push(del);
  }
  return h('div', { class: 'actions imgrow' }, ...items);
}

// Un producte editable (nom, categoria, preu) amb el botó per desactivar-lo o reactivar-lo.
function productCard(p) {
  const out = h('div');
  const nom = h('input', { value: p.nom }), cat = h('input', { value: p.categoria }), preu = h('input', { inputmode: 'decimal', value: preuText(p.preu_cent_per_g) });
  const patch = (btn, body, ok) => guard(btn, out, async () => {
    await api(`/productes/${p.id}`, { method: 'PATCH', body });
    toast(ok);
    show('estoc');
  });
  const save = h('button', { class: 'primary', type: 'button' }, 'Desar');
  save.addEventListener('click', () => guard(save, out, async () => {
    const body = {};
    if (nom.value.trim() !== p.nom) body.nom = nom.value.trim();
    if (cat.value.trim() !== p.categoria) body.categoria = cat.value.trim();
    const c = parseEur(preu.value);
    if (c !== p.preu_cent_per_g) body.preu_cent_per_g = c;
    if (!Object.keys(body).length) throw new Error('No hi ha cap canvi');
    await api(`/productes/${p.id}`, { method: 'PATCH', body });
    toast('Producte actualitzat');
    show('estoc');
  }));
  const toggle = h('button', { type: 'button', class: p.actiu ? 'danger' : '' }, p.actiu ? 'Desactivar' : 'Reactivar');
  toggle.addEventListener('click', () => patch(toggle, { actiu: !p.actiu }, p.actiu ? 'Producte desactivat' : 'Producte reactivat'));
  return h('div', { class: 'card' },
    h('div', null, h('strong', null, p.nom), ' ', h('span', { class: 'pill ' + (p.actiu ? 'ok' : 'warn') }, p.actiu ? 'actiu' : 'inactiu'),
      ' ', h('span', { class: 'muted' }, 'Estoc: ' + p.estoc_g + ' g')),
    imageRow(p, out),
    h('div', { class: 'row' }, field('Nom', nom), field('Categoria', cat), field('Preu per gram (€)', preu)),
    h('div', { class: 'actions' }, save, toggle), out);
}

// ---------- Estoc: existències, moviments, productes i historial (una tasca per subpantalla) ----------

async function stockTable() {
  const prods = await api(`/locals/${S.local}/estoc`);
  return h('div', { class: 'card table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Producte'), h('th', null, 'Categoria'), h('th', { class: 'num' }, 'Preu/g'), h('th', { class: 'num' }, 'Estoc'))),
    h('tbody', null, prods.length ? prods.map((p) => h('tr', null, h('td', null, productThumb(p, 36)), h('td', null, p.nom), h('td', { class: 'muted' }, p.categoria),
      h('td', { class: 'num' }, eur(p.preu_cent_per_g)), h('td', { class: 'num' }, p.estoc_g + ' g')))
      : h('tr', null, h('td', { colspan: 5, class: 'empty' }, 'Encara no hi ha productes.')))));
}

async function stockMoveForm() {
  const prods = await api(`/locals/${S.local}/estoc`);
  const out = h('div');
  const accio = h('select', null, [['entrada', "Entrada d'estoc"], ['merma', 'Merma'], ['ajust', "Ajust d'inventari (quantitat real)"]].map(([v, t]) => h('option', { value: v }, t)));
  const prod = h('select', null, prods.map((p) => h('option', { value: p.id }, p.nom)));
  const g = h('input', { inputmode: 'decimal', placeholder: '0,000' });
  const nota = h('input', { placeholder: 'Motiu o albarà' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar moviment');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      if (!prod.value) throw new Error('Crea primer un producte a la subpantalla «Productes»');
      const a = accio.value;
      const body = a === 'ajust' ? { product_id: Number(prod.value), grams_reals: parseGrams(g.value), nota: nota.value.trim() }
        : { product_id: Number(prod.value), grams: parseGrams(g.value), nota: nota.value.trim() || null };
      await api('/moviments/' + a, { method: 'POST', body });
      toast('Moviment registrat');
      show('estoc');
    });
  } }, h('h3', null, "Nou moviment d'estoc"), h('div', { class: 'row' }, field('Operació', accio), field('Producte', prod)),
  h('div', { class: 'row' }, field('Quantitat (g)', g), field('Nota', nota)), h('div', { class: 'actions' }, btn), out);
}

async function productsSection() {
  const tots = await api(`/locals/${S.local}/productes`);
  const out2 = h('div');
  const n = h('input'), c = h('input'), p = h('input', { inputmode: 'decimal', placeholder: '8,00' });
  const b2 = h('button', { class: 'primary', type: 'submit' }, 'Crear producte');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(b2, out2, async () => {
      await api('/productes', { method: 'POST', body: { local_id: S.local, nom: n.value.trim(), categoria: c.value.trim(), preu_cent_per_g: parseEur(p.value) } });
      toast('Producte creat');
      show('estoc');
    });
  } }, h('h3', null, 'Nou producte'), h('div', { class: 'row' }, field('Nom', n), field('Categoria', c), field('Preu per gram (€)', p)), h('div', { class: 'actions' }, b2), out2);
  return h('div', null, nou, h('h3', null, 'Productes existents'),
    h('p', { class: 'muted' }, "El canvi de preu només afecta les dispensacions noves. Per desactivar un producte, l'estoc ha de ser zero."),
    ...(tots.length ? tots.map(productCard) : [h('div', { class: 'card empty' }, 'Encara no hi ha productes.')]));
}

VIEWS.estoc = async () => {
  const items = [['existencies', 'Existències', stockTable], ['moviment', 'Moviments', stockMoveForm], ['productes', 'Productes', productsSection],
    ['historial', 'Historial', () => stockHistory(() => show('estoc'))]];
  return h('div', null, pageHead('Estoc', 'Existències, entrades i mermes, catàleg de productes i historial amb correccions.'), sections('estoc', items));
};

// ---------- Caixa: estat, despesa, apunts i tancament ----------

async function cashState() {
  const st = await api(`/locals/${S.local}/caixa`);
  const out = h('div');
  if (!st.oberta) {
    const card = h('div', { class: 'card' }, h('span', { class: 'pill warn' }, 'Caixa tancada'), h('p', { class: 'muted' }, 'Cal obrir la caixa per dispensar, cobrar quotes o registrar despeses.'));
    if (!isManager()) return card;
    const ini = h('input', { inputmode: 'decimal', placeholder: '0,00' });
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Obrir caixa');
    return h('div', null, card, h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => { await api('/caixa/obrir', { method: 'POST', body: { local_id: S.local, opening_cent: parseEur(ini.value) } }); show('caixa'); });
    } }, h('h3', null, 'Obrir caixa'), field('Efectiu inicial al calaix (€)', ini), h('div', { class: 'actions' }, btn), out));
  }
  return h('div', { class: 'card' }, h('span', { class: 'pill ok' }, 'Caixa oberta'),
    h('div', { class: 'stats' }, h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Obertura'), h('div', { class: 'big' }, eur(st.obertura_cent))),
      st.esperat_cent != null ? h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Efectiu esperat ara'), h('div', { class: 'big' }, eur(st.esperat_cent))) : null));
}

async function expenseForm() {
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00' });
  const met = h('select', null, ['efectiu', 'targeta'].map((m) => h('option', { value: m }, m)));
  const cat = h('input', { placeholder: 'neteja, compres, nòmines…' });
  const con = h('input');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar despesa');
  const out = h('div');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api('/despeses', { method: 'POST', body: { local_id: S.local, cent: parseEur(imp.value), metode: met.value, categoria: cat.value.trim(), concepte: con.value.trim() } });
      toast('Despesa registrada');
      show('caixa');
    });
  } }, h('h3', null, 'Nova despesa'), h('div', { class: 'row' }, field('Import (€)', imp), field('Mètode', met), field('Categoria', cat)),
  field('Concepte', con), h('div', { class: 'actions' }, btn), out);
}

async function closeForm() {
  const st = await api(`/locals/${S.local}/caixa`);
  if (!st.oberta) return h('div', { class: 'card empty' }, 'No hi ha cap caixa oberta per tancar.');
  const comptat = h('input', { inputmode: 'decimal', placeholder: '0,00' });
  const btn = h('button', { class: 'danger', type: 'submit' }, 'Tancar caixa');
  const out = h('div');
  const box = h('div');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api('/caixa/tancar', { method: 'POST', body: { local_id: S.local, counted_cent: parseEur(comptat.value) } });
      const d = r.diferencia_cent;
      box.replaceChildren(h('div', { class: 'card' }, h('h3', null, 'Caixa tancada'), h('div', { class: 'stats' },
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Esperat'), h('div', { class: 'big' }, eur(r.esperat_cent))),
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Comptat'), h('div', { class: 'big' }, eur(r.comptat_cent))),
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Diferència'), h('span', { class: 'pill ' + (d === 0 ? 'ok' : 'bad') }, (d > 0 ? '+' : '') + eur(d))))));
    });
  } }, h('h3', null, 'Tancament de caixa'), h('p', { class: 'muted' }, "Compta l'efectiu del calaix i escriu-lo: el programa calcula la diferència."),
  field('Efectiu comptat al calaix (€)', comptat), h('div', { class: 'actions' }, btn), out));
  return box;
}

VIEWS.caixa = async () => {
  const items = [['estat', 'Estat', cashState]];
  if (isManager()) items.push(['despesa', 'Despesa', expenseForm], ['apunts', 'Apunts', () => cashHistory(() => show('caixa'))], ['tancament', 'Tancament', closeForm]);
  return h('div', null, pageHead('Caixa', 'Obertura i tancament, despeses i apunts del dia.'), sections('caixa', items));
};

VIEWS.fitxatge = async () => {
  const out = h('div');
  const btns = [['entrada', 'Entrada'], ['pausa_inici', 'Inici de pausa'], ['pausa_fi', 'Fi de pausa'], ['sortida', 'Sortida']].map(([t, label]) => {
    const b = h('button', { class: t === 'entrada' ? 'primary' : '', onclick: () => guard(b, out, async () => {
      await api('/fitxatge', { method: 'POST', body: { local_id: S.local, tipus: t } });
      out.replaceChildren(msg('ok', label + ' registrada a les ' + new Date().toLocaleTimeString(loc(), { hour: '2-digit', minute: '2-digit' })));
    }) }, label);
    return b;
  });
  return h('div', null, pageHead('Fitxatge', 'Registra la teva entrada, pauses i sortida.'), h('div', { class: 'card' }, h('div', { class: 'actions' }, btns), out));
};
