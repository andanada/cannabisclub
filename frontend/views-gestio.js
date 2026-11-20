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

// ---------- Estoc: existències, moviments, productes i historial (una tasca per subpantalla) ----------

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
  const met = h('select', null, metodesIngres());
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
    const tpv = (S.me.locals.find((l) => l.id === S.local) || {}).targeta_activa;   // targeta i Bizum només si el local els accepta
    return h('span', { class: 'actions fila-accions' }, e, ...(tpv ? [t, z] : []));
  };
  const avis = anteriors ? (cobrables ? 'Hi ha dispensacions sense cobrar de sessions anteriors. Cobra-les aquí: el cobrament entra a la caixa oberta.'
    : 'Hi ha dispensacions sense cobrar de sessions anteriors. Obre la caixa per poder cobrar-les.')
    : tancada ? 'Atenció: la caixa s’ha tancat amb dispensacions sense cobrar.' : 'Hi ha dispensacions sense cobrar. Cobra-les abans de tancar la caixa.';
  return h('div', { class: 'card' }, msg('err', avis),
    h('p', { class: 'muted' }, 'Total sense cobrar'), h('div', { class: 'big' }, eur(centTotal)),
    h('ul', null, llista.map((d) => h('li', null, 'Dispensació', ' #' + d.moviment + ' · ' + eur(d.import_cent) + ' · ', 'Soci', ' #' + d.soci_id, ' ', accions(d)))), out);
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

// Fitxar entrada, pauses i sortida: pestanya «Fitxar» d'Horaris (views-horaris.js).
async function secFitxar() {
  const out = h('div');
  const btns = [['entrada', 'Entrada'], ['pausa_inici', 'Inici de pausa'], ['pausa_fi', 'Fi de pausa'], ['sortida', 'Sortida']].map(([t, label]) => {
    const b = h('button', { class: t === 'entrada' ? 'primary' : '', onclick: () => guard(b, out, async () => {
      await api('/fitxatge', { method: 'POST', body: { local_id: S.local, tipus: t } });
      out.replaceChildren(msg('ok', label + ' registrada a les ' + new Date().toLocaleTimeString(loc(), { hour: '2-digit', minute: '2-digit' })));
    }) }, label);
    return b;
  });
  return h('div', { class: 'card' }, h('p', { class: 'lead' }, 'Registra la teva entrada, pauses i sortida.'), h('div', { class: 'actions' }, btns), out);
}
