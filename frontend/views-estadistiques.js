'use strict';
// Estadístiques per a responsables: socis, dispensari i bar, finances. Gràfics de barres en SVG (sense llibreries);
// el color va a CSS (classe .barra) perquè la CSP no permet estils en línia.

const SVG_NS = 'http://www.w3.org/2000/svg';

// Barra horitzontal proporcional (0-100 %) com a SVG.
function barraSvg(pct, classe = '') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'barra-svg');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '12');
  svg.setAttribute('role', 'presentation');
  const fons = document.createElementNS(SVG_NS, 'rect');
  fons.setAttribute('class', 'barra-fons');
  fons.setAttribute('width', '100%'); fons.setAttribute('height', '12'); fons.setAttribute('rx', '6');
  const r = document.createElementNS(SVG_NS, 'rect');
  r.setAttribute('class', 'barra ' + classe);
  r.setAttribute('width', Math.max(0, Math.min(100, pct)) + '%'); r.setAttribute('height', '12'); r.setAttribute('rx', '6');
  svg.append(fons, r);
  return svg;
}

// Llista de barres: files = [{text, valor(number|null), etiqueta(text)}]. Valor null = cel·la suprimida pel llindar d'anonimat.
function grafBarres(files, classe = '') {
  const max = Math.max(1, ...files.map((f) => Math.abs(f.valor || 0)));
  return h('div', { class: 'graf-barres' }, files.map((f) => h('div', { class: 'graf-fila' },
    h('span', { class: 'graf-text' }, f.text),
    f.valor === null ? h('span', { class: 'muted' }, '—') : barraSvg(Math.abs(f.valor) * 100 / max, f.valor < 0 ? 'negatiu' : classe),
    h('strong', { class: 'graf-valor' }, f.etiqueta))));
}

const pct = (v) => (v === null || v === undefined ? '—' : v.toLocaleString(loc(), { maximumFractionDigits: 1 }) + ' %');
const variacio = (v) => (v === null || v === undefined ? 'sense dades de comparació' : (v > 0 ? '+' : '') + v.toLocaleString(loc(), { maximumFractionDigits: 1 }) + ' %');
const mesText = (ym) => new Date(ym + '-01T12:00:00').toLocaleDateString(loc(), { month: 'short', year: '2-digit' });

async function statMembres() {
  const r = await api(`/locals/${S.local}/estadistiques/membres`);
  const k = r.edat.k_minim;
  const suprimit = (n) => (n === null ? '<' + k : String(n));
  return h('div', null,
    h('div', { class: 'row' }, kpi('Sense visites (' + r.comptadors.dies_inactivitat + ' dies)', String(r.comptadors.sense_visites)), kpi('Nous (30 dies)', String(r.comptadors.nous_30d)), kpi('Renovats (30 dies)', String(r.comptadors.renovats_30d))),
    h('div', { class: 'row' },
      h('div', { class: 'card' }, h('h3', null, 'Distribució per edat'), grafBarres(r.edat.franges.map((f) => ({ text: f.franja, valor: f.socis, etiqueta: suprimit(f.socis) })))),
      h('div', { class: 'card' }, h('h3', null, 'Distribució per gènere'), grafBarres(r.genere.franges.map((f) => ({ text: f.franja, valor: f.socis, etiqueta: suprimit(f.socis) }))))),
    h('p', { class: 'muted' }, r.edat.nota),
    h('div', { class: 'card' }, h('h3', null, 'Nous socis per mes'), grafBarres(r.nous_per_mes.map((m) => ({ text: mesText(m.mes), valor: m.socis, etiqueta: String(m.socis) })))),
    h('div', { class: 'row' },
      h('div', null, h('h3', null, 'Top 10 per grams (' + r.any + ')'), taula([['Soci'], ['Grams', true]], r.top_grams.map((t) => [t.soci, gText(t.grams)]), 'Sense dispensacions.')),
      h('div', null, h('h3', null, 'Top 10 per import (' + r.any + ')'), taula([['Soci'], ['Import', true]], r.top_import.map((t) => [t.soci, eur(t.import_cent)]), 'Sense dispensacions.'))));
}

async function statDispensari() {
  const r = await api(`/locals/${S.local}/estadistiques/dispensari`);
  const fila = (nom, p) => [nom, eur(p.avui), eur(p.ahir), eur(p.setmana)];
  const mesos = (p) => grafBarres(p.mesos.map((m) => ({ text: mesText(m.mes), valor: m.import_cent, etiqueta: eur(m.import_cent) })));
  return h('div', null,
    h('div', { class: 'row' }, kpi('Genètics sobre el total', pct(r.percentatge_genetics)),
      kpi('Preu mitjà genètics', r.preu_mitja_genetics_cent_per_g === null ? '—' : eur(r.preu_mitja_genetics_cent_per_g) + '/g'),
      kpi('Preu mitjà no genètics', r.preu_mitja_no_genetics_cent === null ? '—' : eur(r.preu_mitja_no_genetics_cent))),
    taula([['Ingressos'], ['Avui', true], ['Ahir', true], ['Últims 7 dies', true]], [fila('Dispensari', r.dispensari), fila('Bar', r.bar)]),
    h('div', { class: 'row' },
      h('div', { class: 'card' }, h('h3', null, 'Dispensari: darrers mesos'), mesos(r.dispensari)),
      h('div', { class: 'card' }, h('h3', null, 'Bar: darrers mesos'), mesos(r.bar))),
    h('div', { class: 'row' },
      h('div', null, h('h3', null, 'Top 10 genètics (grams)'), taula([['Producte'], ['Grams', true]], r.top_genetics_grams.map((t) => [t.producte, gText(t.grams)]), 'Sense dades.')),
      h('div', null, h('h3', null, 'Top 10 genètics (import)'), taula([['Producte'], ['Import', true]], r.top_genetics_import.map((t) => [t.producte, eur(t.import_cent)]), 'Sense dades.')),
      h('div', null, h('h3', null, 'Top 10 no genètics (import)'), taula([['Producte'], ['Import', true]], r.top_no_genetics_import.map((t) => [t.producte, eur(t.import_cent)]), 'Sense dades.'))));
}

async function statFinances() {
  const any = Number(sessionStorage.getItem('stat-any')) || new Date().getFullYear();
  const r = await api(`/locals/${S.local}/estadistiques/finances?any=${any}`);
  const anys = h('select', { 'aria-label': 'Any' }, [0, 1, 2, 3].map((d) => new Date().getFullYear() - d).map((y) => h('option', { value: y, selected: y === r.any }, String(y))));
  anys.addEventListener('change', () => { sessionStorage.setItem('stat-any', anys.value); show('estadistiques'); });
  const i = r.ingressos;
  return h('div', null, h('div', { class: 'card' }, field('Any', anys)),
    h('div', { class: 'row' }, kpi('Ingressos avui', eur(i.avui)), kpi('Ahir', eur(i.ahir)), kpi('Variació amb ahir', variacio(i.variacio_dia_pct)),
      kpi('Últims 7 dies', eur(i.setmana)), kpi('Variació amb la setmana anterior', variacio(i.variacio_setmana_pct))),
    h('div', { class: 'row' }, kpi('Grams dispensats (' + r.any + ')', gText(r.grams_any)), kpi('Mitjana diària', gText(r.mitjana_diaria_g))),
    h('div', { class: 'card' }, h('h3', null, 'Benefici mensual (vendes − despeses)'),
      grafBarres(r.mesos.map((m) => ({ text: mesText(m.mes), valor: m.benefici_cent, etiqueta: eur(m.benefici_cent) })))),
    taula([['Mes'], ['Vendes', true], ['Despeses', true], ['Benefici', true], ['Grams', true], ['Mitjana diària', true]],
      r.mesos.map((m) => [mesText(m.mes), eur(m.vendes_cent), eur(m.despeses_cent), eur(m.benefici_cent), gText(m.grams), gText(m.mitjana_diaria_g)])));
}

VIEWS.estadistiques = async () => h('div', null, pageHead('Estadístiques', 'Socis, dispensari i bar, i finances del local.'), sections('estadistiques', [
  ['membres', 'Socis', statMembres], ['dispensari', 'Dispensari i bar', statDispensari], ['finances', 'Finances', statFinances],
]));
