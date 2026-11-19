'use strict';
// Pantalles: Estoc, Caixa, Fitxatge. (Informe és a views-informes.js.)

const preuText = (c) => (c / 100).toFixed(2).replace('.', ',');

// Miniatura d'un producte (o una inicial si encara no té foto).
// Unitat d'un producte («g» o «u») i aspecte (icona i color) de la seva categoria. El color és una classe CSS (la CSP no permet estils en línia).
const unitTxt = (p) => (p && p.unitat === 'u' ? 'u' : 'g');
const metaCat = { local: null, mapa: new Map() };
async function carregaMetaCat() {
  if (metaCat.local === S.local) return metaCat.mapa;
  try {
    const r = await api(`/locals/${S.local}/categories`);
    metaCat.mapa = new Map(r.categories.map((c) => [c.nom, c]));
    metaCat.local = S.local;
  } catch (_) { metaCat.mapa = new Map(); }
  return metaCat.mapa;
}
function catBadge(nom) {
  const m = metaCat.mapa.get(nom);
  if (!m || (!m.icona && !m.color)) return null;
  return h('span', { class: 'cat-badge' + (m.color ? ' cat-' + m.color : ''), title: nom }, m.icona || '●');
}

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
  const gen = h('input', { type: 'checkbox', checked: !!p.es_genetic });
  const reg = h('input', { type: 'checkbox', checked: !!p.regalable });
  const uni = h('select', { 'aria-label': 'Unitat' }, [['g', 'Grams'], ['u', 'Unitats']].map(([v, t]) => h('option', { value: v, selected: v === unitTxt(p) }, t)));
  const gra = h('input', { type: 'checkbox', checked: p.granel !== false });
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
    if (gen.checked !== !!p.es_genetic) body.es_genetic = gen.checked;
    if (reg.checked !== !!p.regalable) body.regalable = reg.checked;
    if (uni.value !== unitTxt(p)) body.unitat = uni.value;
    if (gra.checked !== (p.granel !== false)) body.granel = gra.checked;
    if (!Object.keys(body).length) throw new Error('No hi ha cap canvi');
    await api(`/productes/${p.id}`, { method: 'PATCH', body });
    toast('Producte actualitzat');
    show('estoc');
  }));
  const toggle = h('button', { type: 'button', class: p.actiu ? 'danger' : '' }, p.actiu ? 'Desactivar' : 'Reactivar');
  toggle.addEventListener('click', () => patch(toggle, { actiu: !p.actiu }, p.actiu ? 'Producte desactivat' : 'Producte reactivat'));
  return h('div', { class: 'card' },
    h('div', null, h('strong', null, p.nom), ' ', h('span', { class: 'pill ' + (p.actiu ? 'ok' : 'warn') }, p.actiu ? 'actiu' : 'inactiu'),
      ' ', h('span', { class: 'muted' }, 'Estoc: ' + p.estoc_g + ' ' + unitTxt(p))),
    imageRow(p, out),
    h('div', { class: 'row' }, field('Nom', nom), field('Categoria', cat), field('Preu per gram o unitat (€)', preu), field('Unitat de venda', uni)),
    h('label', null, gen, ' És genètic'), ' ', h('label', null, reg, ' Es pot regalar'), ' ', h('label', null, gra, ' Dispensació a granel (qualsevol quantitat)'),
    h('div', { class: 'actions' }, save, toggle), out);
}

// ---------- Estoc: existències, moviments, productes i historial (una tasca per subpantalla) ----------

async function stockTable() {
  const prods = await api(`/locals/${S.local}/estoc`);
  await carregaMetaCat();
  return h('div', { class: 'card table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Producte'), h('th', null, 'Categoria'), h('th', { class: 'num' }, 'Preu'), h('th', { class: 'num' }, 'Estoc'))),
    h('tbody', null, prods.length ? prods.map((p) => h('tr', null, h('td', null, productThumb(p, 36)), h('td', null, p.nom), h('td', { class: 'muted' }, catBadge(p.categoria), ' ', p.categoria),
      h('td', { class: 'num' }, eur(p.preu_cent_per_g) + '/' + unitTxt(p)), h('td', { class: 'num' }, p.estoc_g + ' ' + unitTxt(p))))
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
  // Elecció explícita (sense valor per defecte): un producte nou no genètic queda fora dels límits per soci sense que ningú ho hagi decidit.
  const regNou = h('input', { type: 'checkbox' });
  const uniNou = h('select', { 'aria-label': 'Unitat' }, [['g', 'Grams'], ['u', 'Unitats']].map(([v, t]) => h('option', { value: v }, t)));
  const graNou = h('input', { type: 'checkbox', checked: true });
  const genNou = h('select', null, h('option', { value: '' }, 'Tria…'), h('option', { value: 'si' }, 'Sí: compta per als límits per soci'), h('option', { value: 'no' }, 'No: no compta per als límits'));
  const b2 = h('button', { class: 'primary', type: 'submit' }, 'Crear producte');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(b2, out2, async () => {
      if (!genNou.value) throw new Error('Indica si el producte és genètic (flor, hash, extractes, clons…): decideix si compta per als límits per soci');
      await api('/productes', { method: 'POST', body: { local_id: S.local, nom: n.value.trim(), categoria: c.value.trim(), preu_cent_per_g: parseEur(p.value), es_genetic: genNou.value === 'si', regalable: regNou.checked, unitat: uniNou.value, granel: graNou.checked } });
      toast('Producte creat');
      show('estoc');
    });
  } }, h('h3', null, 'Nou producte'), h('div', { class: 'row' }, field('Nom', n), field('Categoria', c), field('Preu per gram (€)', p)), field('És genètic?', genNou), field('Unitat de venda', uniNou), h('label', null, regNou, ' Es pot regalar'), ' ', h('label', null, graNou, ' Dispensació a granel (qualsevol quantitat)'), h('div', { class: 'actions' }, b2), out2);
  // Els límits per soci només compten productes marcats com a genètics: sense cap, els límits no s'apliquen a res.
  const lloc = (S.me.locals || []).find((l) => l.id === S.local) || {};
  const amLimits = lloc.limit_diari_mg != null || lloc.limit_mensual_mg != null;
  const avisGenetic = amLimits && tots.length && !tots.some((p) => p.es_genetic)
    ? msg('err', 'Aquest local té límits de dispensació, però cap producte està marcat com a genètic: els límits no s’estan aplicant. Revisa els productes (flor, hash, extractes, clons, llavors) i marca’ls com a genètics.') : null;
  return h('div', null, avisGenetic, nou, h('h3', null, 'Productes existents'),
    h('p', { class: 'muted' }, "El canvi de preu només afecta les dispensacions noves. Per desactivar un producte, l'estoc ha de ser zero."),
    ...(tots.length ? tots.map(productCard) : [h('div', { class: 'card empty' }, 'Encara no hi ha productes.')]));
}

// Un dispensador amb el privilegi «pot editar descomptes» hi arriba des d'un menú propi (no té el d'Estoc).
VIEWS.descomptes = async () => h('div', null, pageHead('Descomptes', 'Descomptes vigents i alta de nous.'), await discountsSection());

// Aspecte de les categories de producte (icona i color): es veu a la pantalla de dispensar i a les existències.
async function secCategories() {
  const r = await api(`/locals/${S.local}/categories`);
  metaCat.local = null;   // es tornarà a carregar amb els canvis
  const out = h('div');
  const files = r.categories.map((c) => {
    const ic = h('select', { 'aria-label': 'Icona' }, h('option', { value: '' }, '—'), ...r.icones.map((i) => h('option', { value: i, selected: i === c.icona }, i)));
    const co = h('select', { 'aria-label': 'Color' }, h('option', { value: '' }, '—'), ...r.colors.map((k) => h('option', { value: k, selected: k === c.color }, k)));
    const b = h('button', { type: 'button', class: 'small primary' }, 'Desar');
    b.addEventListener('click', () => guard(b, out, async () => { await api(`/locals/${S.local}/categories`, { method: 'PUT', body: { nom: c.nom, icona: ic.value, color: co.value } }); toast('Categoria desada'); }));
    return [h('span', { class: 'cat-badge' + (c.color ? ' cat-' + c.color : '') }, c.icona || '●'), c.nom, String(c.productes), ic, co, b];
  });
  return h('div', null, h('p', { class: 'muted' }, 'Les categories surten dels productes (camp «Categoria»). Aquí els hi poses icona i color.'),
    taula([[''], ['Categoria'], ['Productes', true], ['Icona'], ['Color'], ['']], files, 'Encara no hi ha categories: escriu-ne una en un producte.'), out);
}

VIEWS.estoc = async () => {
  const items = [['existencies', 'Existències', stockTable], ['moviment', 'Moviments', stockMoveForm], ['productes', 'Productes', productsSection], ['categories', 'Categories', secCategories], ['descomptes', 'Descomptes', discountsSection], ['linies', 'Línies de preu', priceLinesSection], ['magatzems', 'Magatzems', warehousesSection], ['contenidors', 'Contenidors', containersSection], ['tipus-contenidor', 'Tipus de contenidor', containerTypesSection], ['regles', 'Regles', rulesSection], ['inventari', 'Inventari', inventorySection],
    ['historial', 'Historial', () => stockHistory(() => show('estoc'))]];
  return h('div', null, pageHead('Estoc', 'Existències, entrades i mermes, catàleg de productes i historial amb correccions.'), sections('estoc', items));
};

// ---------- Caixa: estat, despesa, apunts i tancament ----------

async function cashState() {
  const st = await api(`/locals/${S.local}/caixa`);
  const out = h('div');
  if (st.ambigua) return h('div', { class: 'card' }, h('span', { class: 'pill warn' }, 'Cap caixa teva'), h('p', { class: 'muted' }, st.motiu));
  const deutes = senseCobrar(st.sense_cobrar_anteriors, st.sense_cobrar_anteriors_cent, false, true, st.oberta);   // sessions anteriors: no poden quedar invisibles
  if (!st.oberta) {
    const card = h('div', { class: 'card' }, h('span', { class: 'pill warn' }, 'Caixa tancada'), h('p', { class: 'muted' }, 'Cal obrir la caixa per dispensar, cobrar quotes o registrar despeses.'));
    if (!potRecepcio()) return card;
    const ini = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Efectiu inicial' });
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Obrir caixa');
    return h('div', null, card, deutes, h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        await api('/caixa/obrir', { method: 'POST', body: { local_id: S.local, opening_cent: parseEur(ini.value) } });
        show('caixa');
      });
    } }, h('h3', null, 'Obrir caixa'), field('Efectiu inicial al calaix (€)', ini), h('div', { class: 'actions' }, btn), out));
  }
  return h('div', null, h('div', { class: 'card' }, h('span', { class: 'pill ok' }, 'Caixa oberta'),
    h('div', { class: 'stats' }, h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Obertura'), h('div', { class: 'big' }, eur(st.obertura_cent))),
      st.esperat_cent != null ? h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Efectiu esperat ara'), h('div', { class: 'big' }, eur(st.esperat_cent))) : null)), deutes);
}

async function expenseForm() {
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00' });
  const met = h('select', null, ['efectiu', 'targeta', 'bizum'].map((m) => h('option', { value: m }, m)));
  const cat = h('input', { placeholder: 'neteja, compres, nòmines…' });
  const con = h('input');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar despesa');
  const out = h('div');
  const ref = novaRef();   // una despesa = una referència: enviar-la dues vegades no la duplica
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api('/despeses', { method: 'POST', body: { client_ref: ref, local_id: S.local, cent: parseEur(imp.value), metode: met.value, categoria: cat.value.trim(), concepte: con.value.trim() } });
      toast('Despesa registrada');
      show('caixa');
    });
  } }, h('h3', null, 'Nova despesa'), h('div', { class: 'row' }, field('Import (€)', imp), field('Mètode', met), field('Categoria', cat)),
  field('Concepte', con), h('div', { class: 'actions' }, btn), out);
}

// Avís de dispensacions sense cobrar (abans i després de tancar la caixa).
function senseCobrar(llista, centTotal, tancada, anteriors, cobrables) {
  if (!llista || !llista.length) return null;
  const out = h('div');
  // Deutes de sessions anteriors: es poden cobrar aquí mateix (amb la caixa oberta; el cobrament entra a la sessió actual).
  const cobra = (d, metode, b) => guard(b, out, async () => {
    await api('/cobraments', { method: 'POST', body: { movement_id: d.moviment, metode } });
    toast('Cobrat ' + eur(d.import_cent) + ' (' + metode + ')');
    show('caixa');
  });
  const accions = (d) => {
    if (!anteriors || !cobrables) return null;
    const e = h('button', { class: 'small' }, 'Efectiu');
    const t = h('button', { class: 'small' }, 'Targeta');
    const z = h('button', { class: 'small' }, 'Bizum');
    e.addEventListener('click', () => cobra(d, 'efectiu', e));
    t.addEventListener('click', () => cobra(d, 'targeta', t));
    z.addEventListener('click', () => cobra(d, 'bizum', z));
    return h('span', { class: 'actions fila-accions' }, e, t, z);
  };
  const avis = anteriors ? (cobrables ? 'Hi ha dispensacions sense cobrar de sessions anteriors. Cobra-les aquí: el cobrament entra a la caixa oberta.'
    : 'Hi ha dispensacions sense cobrar de sessions anteriors. Obre la caixa per poder cobrar-les.')
    : tancada ? 'Atenció: la caixa s’ha tancat amb dispensacions sense cobrar.' : 'Hi ha dispensacions sense cobrar. Cobra-les abans de tancar la caixa.';
  return h('div', { class: 'card' }, msg('err', avis),
    h('p', { class: 'muted' }, 'Total sense cobrar'), h('div', { class: 'big' }, eur(centTotal)),
    h('ul', null, llista.map((d) => h('li', null, 'Dispensació', ' #' + d.moviment + ' · ' + eur(d.import_cent) + ' · ', 'Soci', ' #' + d.soci_id, ' ', accions(d)))), out);
}

async function closeForm() {
  const st = await api(`/locals/${S.local}/caixa`);
  if (!st.oberta) return h('div', { class: 'card empty' }, 'No hi ha cap caixa oberta per tancar.');
  const comptat = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Efectiu comptat' });
  const btn = h('button', { class: 'danger', type: 'submit' }, 'Tancar caixa');
  const out = h('div');
  const box = h('div');
  const avisAbans = senseCobrar(st.sense_cobrar, st.sense_cobrar_cent, false);
  if (avisAbans) box.append(avisAbans);
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api('/caixa/tancar', { method: 'POST', body: { local_id: S.local, counted_cent: parseEur(comptat.value) } });
      const d = r.diferencia_cent;
      box.replaceChildren(h('div', { class: 'card' }, h('h3', null, 'Caixa tancada'), h('div', { class: 'stats' },
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Esperat'), h('div', { class: 'big' }, eur(r.esperat_cent))),
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Comptat'), h('div', { class: 'big' }, eur(r.comptat_cent))),
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Diferència'), h('span', { class: 'pill ' + (d === 0 ? 'ok' : 'bad') }, (d > 0 ? '+' : '') + eur(d))))), senseCobrar(r.sense_cobrar, r.sense_cobrar_cent, true));
    });
  } }, h('h3', null, 'Tancament de caixa'), h('p', { class: 'muted' }, "Compta l'efectiu del calaix i escriu-lo: el programa calcula la diferència. Les donacions dels socis ja hi són sumades."),
  field('Efectiu comptat al calaix (€)', comptat), h('div', { class: 'actions' }, btn), out));
  return box;
}

// Caixes registradores (Dispensari, Entrada…): cada una pot tenir el seu magatzem, del qual descompta l'estoc.
async function secCaixes() {
  const [info, mags] = await Promise.all([api(`/locals/${S.local}/caixes`), api(`/locals/${S.local}/magatzems`)]);
  const out = h('div');
  const nom = h('input', { maxlength: 60, required: true });
  const mag = h('select', null, h('option', { value: '' }, 'Magatzem principal'), ...mags.filter((m) => m.actiu !== false).map((m) => h('option', { value: m.id }, m.nom)));
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear caixa');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/caixes`, { method: 'POST', body: { nom: nom.value.trim(), warehouse_id: mag.value ? Number(mag.value) : null } });
      toast('Caixa creada');
      show('caixa');
    });
  } }, h('h3', null, 'Nova caixa registradora'), h('div', { class: 'row' }, field('Nom', nom), field('Magatzem', mag)), h('div', { class: 'actions' }, btn), out);
  const files = info.caixes.map((c) => {
    const b = h('button', { type: 'button', class: 'small' }, c.actiu ? 'Desactivar' : 'Reactivar');
    b.addEventListener('click', () => guard(b, out, async () => { await api(`/caixes/${c.id}`, { method: 'PUT', body: { actiu: !c.actiu } }); show('caixa'); }));
    return [c.nom, c.magatzem || 'Principal', c.oberta ? h('span', { class: 'pill ok' }, 'oberta · ' + c.empleat) : h('span', { class: 'pill' }, c.actiu ? 'tancada' : 'inactiva'), b];
  });
  return h('div', null, form, taula([['Caixa'], ['Magatzem'], ['Estat'], ['']], files, 'Només hi ha la caixa del local: crea una caixa per tenir-ne més d\'una.'));
}

// Resum de sessions: una fila per torn amb l'empleat, la caixa, els imports anterior i de control, els totals per mètode i la diferència.
async function secResum() {
  const avui = new Date().toLocaleDateString('sv-SE');
  const fa7 = new Date(Date.now() - 7 * 86400000).toLocaleDateString('sv-SE');
  const des = h('input', { type: 'date', value: fa7 }), fins = h('input', { type: 'date', value: avui });
  const res = h('div'), out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure');
  const carrega = async () => {
    const l = await api(`/locals/${S.local}/caixa/sessions?des=${des.value}&fins=${fins.value}`);
    const tot = (k) => l.reduce((s, x) => s + (x[k] || 0), 0);
    const hora = (iso) => (iso ? new Date(iso).toLocaleString(loc()) : 'oberta');
    res.replaceChildren(h('div', { class: 'row' }, kpi('Total', eur(tot('total_cent'))), kpi('Efectiu', eur(tot('efectiu_cent'))), kpi('Targeta', eur(tot('targeta_cent'))),
      kpi('Bizum', eur(tot('bizum_cent'))), kpi('Monedero', eur(tot('monedero_cent'))), kpi('Despeses', eur(tot('despeses_cent')))),
      taula([['Empleat'], ['Caixa'], ['Obertura'], ['Tancament'], ['Import anterior', true], ['Obertura €', true], ['Efectiu', true], ['Targeta', true], ['Bizum', true], ['Monedero', true], ['Total', true], ['Diferència', true]],
        l.map((x) => [x.empleat, x.caixa || 'Caixa del local', hora(x.obertura), hora(x.tancament), x.import_anterior_cent == null ? '—' : eur(x.import_anterior_cent), eur(x.obertura_cent),
          eur(x.efectiu_cent), eur(x.targeta_cent), eur(x.bizum_cent), eur(x.monedero_cent), eur(x.total_cent), x.diferencia_cent == null ? '—' : eur(x.diferencia_cent)]), 'Cap sessió de caixa en aquest període.'));
  };
  const form = h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); guard(btn, out, carrega); } },
    h('h3', null, 'Resum de sessions de caixa'), h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, btn), out);
  await carrega();
  return h('div', null, form, res);
}

VIEWS.caixa = async () => {
  const items = [['estat', 'Estat', cashState]];
  if (potRecepcio()) items.push(['despesa', 'Despesa', expenseForm], ['apunts', 'Apunts', () => cashHistory(() => show('caixa'))], ['tancament', 'Tancament', closeForm], ['resum', 'Resum de sessions', secResum]);
  return h('div', null, pageHead('Caixa', 'Caixa única de recepció: donacions dels socis, despeses, apunts i tancament.'), sections('caixa', items));
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
  return h('div', null, pageHead('Horaris', 'Registra la teva entrada, pauses i sortida.'), h('div', { class: 'card' }, h('div', { class: 'actions' }, btns), out));
};
