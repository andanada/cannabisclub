'use strict';
// Estadístiques: Rendibilitat per producte, Resum mensual (imprimible i exportable) i taula dia a dia de Finances.

const qCant = (q) => {
  const parts = [];
  if (Number(q.g) !== 0) parts.push(gText(q.g));
  if (Number(q.ud) !== 0) parts.push(Number(q.ud).toLocaleString(loc(), { maximumFractionDigits: 3 }) + ' ud.');
  return parts.length ? parts.join(' + ') : '0';
};
const eurS = (c) => (c > 0 ? '+' : '') + eur(c);
const nomCat = (c) => c || 'Sense categoria';
const scroll = (t) => h('div', { class: 'taula-scroll' }, t);
const avuiISO = () => new Date().toLocaleDateString('sv-SE');
const primerMes = () => avuiISO().slice(0, 8) + '01';

function descarregaCsv(btn, out, url, nom) {
  guard(btn, out, async () => {
    const r = await api(url, { raw: true });
    if (!r.ok) throw new Error("No s'ha pogut exportar");
    descarrega(await r.blob(), nom);
  });
}

// ---- Rendibilitat per producte ----
const COLS_REND = [['Producte'], ['Entrat', true], ['Pagat', true], ['Dispensat', true], ['Ingressat', true], ['Regals', true], ['Estoc', true], ['Valor potencial', true], ['Benefici', true]];
const filaRend = (nom, x) => [nom, qCant(x.entrat), eur(x.pagat_cent) + (x.pagat_estimat ? ' *' : ''), qCant(x.dispensat), eur(x.ingressat_cent),
  qCant(x.regal) + (x.regal_cost_cent ? ' (' + eur(x.regal_cost_cent) + ')' : ''), qCant(x.estoc), eur(x.valor_potencial_cent), eurS(x.benefici_cent)];

async function statRendibilitat() {
  const des = h('input', { type: 'date', id: 'rend-des', value: sessionStorage.getItem('rend-des') || primerMes() });
  const fins = h('input', { type: 'date', id: 'rend-fins', value: sessionStorage.getItem('rend-fins') || avuiISO() });
  const out = h('div'), res = h('div');
  const q = () => `des=${des.value}&fins=${fins.value}`;
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure');
  const csv = h('button', { type: 'button' }, 'Descarregar CSV');
  csv.addEventListener('click', () => descarregaCsv(csv, out, `/locals/${S.local}/estadistiques/rendibilitat.csv?${q()}`, `rendibilitat-${des.value}_${fins.value}.csv`));
  const carrega = () => guard(btn, out, async () => {
    sessionStorage.setItem('rend-des', des.value); sessionStorage.setItem('rend-fins', fins.value);
    const r = await api(`/locals/${S.local}/estadistiques/rendibilitat?${q()}`);
    const t = r.total;
    res.replaceChildren(
      h('div', { class: 'row' }, kpi('Total gastat', eur(t.pagat_cent)), kpi('Total guanyat', eur(t.ingressat_cent)), kpi('Benefici o pèrdua', eurS(t.benefici_cent)),
        kpi('Valor potencial de l’estoc', eur(t.valor_potencial_cent))),
      h('h3', null, 'Totals'), scroll(taula(COLS_REND, [filaRend('Genètiques', r.genetics), filaRend('No genètiques', r.no_genetics), filaRend('Total', r.total)])),
      h('h3', null, 'Per categoria'), scroll(taula(COLS_REND, r.per_categoria.map((c) => filaRend(nomCat(c.categoria), c)), 'Sense dades.')),
      h('h3', null, 'Per producte'), scroll(taula(COLS_REND, r.productes.map((p) => filaRend(p.nom, p)), 'Sense dades.')),
      h('p', { class: 'muted' }, '* Alguna entrada no té preu pagat: s’ha estimat amb el preu d’entrada del producte. El benefici és ingressat menys pagat; els regals compten com a cost sense ingrés. L’estoc i el seu valor són els d’avui.'));
  });
  const form = h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); carrega(); } },
    h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, btn, csv));
  carrega();
  return h('div', null, form, out, res);
}

// ---- Resum mensual ----
const mesActual = () => avuiISO().slice(0, 7);

function blocGrups(titol, b, camp) {
  const cols = [['Concepte'], ['Quantitat', true], [camp, true]];
  const f = (nom, x) => [nom, qCant(x.mg), eur(x.cent)];
  return h('div', { class: 'card' }, h('h3', null, titol), scroll(taula(cols, [f('Genètiques', b.genetics), f('No genètiques', b.no_genetics),
    ...b.per_categoria.map((c) => f(nomCat(c.categoria), c)), f('Total', b.total)])));
}

function pintaResum(r) {
  const i = r.ingressos, d = r.despeses;
  const metodes = (b) => [['Efectiu', b.efectiu_cent], ['Targeta', b.targeta_cent], ['Bizum', b.bizum_cent], ['Total', b.total_cent]];
  const llista = (items) => items.map((x) => [x.categoria + (x.pendent_cent ? ' (pendent de revisió)' : ''), eur(x.import_cent)]);
  return h('div', { class: 'print-area resum-mensual' },
    h('h3', { class: 'nomes-imprimir' }, 'Resum mensual ' + r.mes),
    h('div', { class: 'row' }, kpi('Diners entrats', eur(i.total_cent)), kpi('Despeses', eur(d.total_cent)), kpi('Total net', eurS(r.total_net_cent))),
    blocGrups('1. Entrades d’estoc', r.entrades, 'Pagat'),
    r.entrades.estimat ? h('p', { class: 'muted' }, 'Alguna entrada no té preu pagat: l’import és una estimació.') : null,
    blocGrups('2. Dispensat (crèdits consumits)', r.dispensat, 'Crèdits'),
    h('div', { class: 'card' }, h('h3', null, 'Regals'), scroll(taula([['Categoria'], ['Quantitat', true]],
      [...r.regals.per_categoria.map((c) => [nomCat(c.categoria), qCant(c.mg)]), ['Total', qCant(r.regals.total.mg)]], 'Sense regals.'))),
    h('div', { class: 'card' }, h('h3', null, '3. Diners entrats'),
      h('h4', null, 'Donacions'), scroll(taula([['Mètode'], ['Import', true]], metodes(i.donacions).map(([k, v]) => [k, eur(v)]))),
      h('h4', null, 'Quotes'), scroll(taula([['Mètode'], ['Import', true]], metodes(i.quotes).map(([k, v]) => [k, eur(v)]))),
      h('h4', null, 'Efectiu retirat en tancar les caixes'), scroll(taula([['Tipus'], ['Import', true]], [['Bitllets', eur(i.billets_cent)], ['Monedes', eur(i.monedes_cent)]]))),
    h('div', { class: 'card' }, h('h3', null, '4. Despeses'),
      h('h4', null, 'De caixa del dia'), scroll(taula([['Categoria'], ['Import', true]], [...llista(d.caixa), ['Total', eur(d.caixa_cent)]], 'Sense despeses.')),
      h('h4', null, 'De final de mes'), scroll(taula([['Categoria'], ['Import', true]], [...llista(d.final_mes), ['Total', eur(d.final_mes_cent)]], 'Sense despeses.')),
      d.pendent_cent ? h('p', { class: 'muted' }, eur(d.pendent_cent) + ' en compres d’estoc pendents de revisió.') : null),
    h('div', { class: 'card' }, h('h3', null, '5. Crèdit no dispensat'),
      h('div', { class: 'row' }, kpi('A final de mes', eur(r.credit.final_cent)), kpi('Diferència amb el mes anterior', eurS(r.credit.diferencia_cent)))),
    h('div', { class: 'card' }, h('h3', null, '6. Total net'), h('p', { class: 'big' }, eurS(r.total_net_cent)),
      h('p', { class: 'muted' }, 'Diners entrats menys despeses.')));
}

async function statResum() {
  const mes = h('input', { type: 'month', id: 'resum-mes', value: sessionStorage.getItem('resum-mes') || mesActual() });
  const out = h('div'), res = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure');
  const csv = h('button', { type: 'button' }, 'Descarregar CSV');
  const imprimeix = h('button', { type: 'button' }, 'Imprimir');
  imprimeix.addEventListener('click', () => window.print());
  csv.addEventListener('click', () => descarregaCsv(csv, out, `/locals/${S.local}/estadistiques/resum-mensual.csv?mes=${mes.value}`, `resum-mensual-${mes.value}.csv`));
  const carrega = () => guard(btn, out, async () => {
    if (!mes.value) throw new Error('Tria un mes');
    sessionStorage.setItem('resum-mes', mes.value);
    res.replaceChildren(pintaResum(await api(`/locals/${S.local}/estadistiques/resum-mensual?mes=${mes.value}`)));
  });
  const form = h('form', { class: 'card no-print', onsubmit: (e) => { e.preventDefault(); carrega(); } },
    h('div', { class: 'row' }, field('Mes', mes)), h('div', { class: 'actions' }, btn, csv, imprimeix));
  carrega();
  return h('div', null, form, out, res);
}

// ---- Finances: dia a dia ----
async function blocDiaADia() {
  const des = h('input', { type: 'date', id: 'dies-des', value: primerMes() });
  const fins = h('input', { type: 'date', id: 'dies-fins', value: avuiISO() });
  const out = h('div'), res = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure dia a dia');
  const carrega = () => guard(btn, out, async () => {
    const r = await api(`/locals/${S.local}/estadistiques/finances-dies?des=${des.value}&fins=${fins.value}`);
    const f = (nom, x) => [nom, eur(x.mati_cent), eur(x.tarda_cent), eur(x.billets_cent), eur(x.monedes_cent), eur(x.targeta_cent), eur(x.bizum_cent), eur(x.total_cent), eur(x.despeses_caixa_cent)];
    res.replaceChildren(
      h('div', { class: 'row' }, kpi('Vendes del període', eur(r.vendes_cent)), kpi('Despeses del període', eur(r.despeses_cent)), kpi('Benefici', eurS(r.vendes_cent - r.despeses_cent))),
      scroll(taula([['Dia'], ['Matí', true], ['Tarda', true], ['Bitllets', true], ['Monedes', true], ['Targeta', true], ['Bizum', true], ['Total del dia', true], ['Despeses de caixa', true]],
        [...r.dies.map((x) => f(new Date(x.dia + 'T12:00:00').toLocaleDateString(loc(), { weekday: 'short', day: 'numeric', month: 'short' }), x)), f('Total', r.totals)])),
      h('p', { class: 'muted' }, 'Matí i tarda segons l’hora de cada cobrament i el torn de tarda dels horaris. Bitllets i monedes són l’efectiu retirat en tancar cada caixa.'));
  });
  const form = h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); carrega(); } },
    h('h3', null, 'Dia a dia'), h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, btn));
  carrega();
  return h('div', null, form, out, res);
}
