'use strict';
// Pantalla d'Informes: caixa, vendes, estoc valorat, assistència i hores del personal (amb exportació a CSV).

const taula = (cols, rows, buit) => h('table', null,
  h('thead', null, h('tr', null, cols.map(([t, num]) => h('th', { class: num ? 'num' : '' }, t)))),
  h('tbody', null, rows.length ? rows.map((r) => h('tr', null, r.map((v, i) => h('td', { class: cols[i][1] ? 'num' : '' }, v))))
    : h('tr', null, h('td', { colspan: cols.length, class: 'muted' }, buit || 'Sense dades en aquest període.'))));

const kpi = (etiqueta, valor) => h('div', null, h('div', { class: 'muted' }, etiqueta), h('div', { class: 'big' }, valor));
const gText = (g) => Number(g).toLocaleString(loc(), { maximumFractionDigits: 3 }) + ' g';

const INFORMES = {
  caixa: { titol: 'Caixa: ingressos i despeses', rang: true, json: (q) => `/locals/${S.local}/informe?${q}`, csv: (q) => `/locals/${S.local}/apunts.csv?${q}`, fitxer: 'apunts',
    pinta: (r) => {
      const cats = Object.entries(r.despeses_per_categoria);
      return [h('div', { class: 'row' }, kpi('Ingressos', eur(r.ingressos_cent)), kpi('Despeses', eur(r.despeses_cent)), kpi('Resultat', eur(r.resultat_cent)), kpi('Dispensat', grams(r.dispensat_mg))),
        cats.length ? h('div', null, h('h3', null, 'Despeses per categoria'), taula([['Categoria'], ['Import', true]], cats.map(([k, v]) => [k, eur(v)]))) : null,
        h('h3', null, 'Per dia'), taula([['Dia'], ['Ingressos', true], ['Despeses', true]], Object.entries(r.per_dia).map(([d, v]) => [d, eur(v.ingressos_cent), eur(v.despeses_cent === 0 ? 0 : -v.despeses_cent)]))];
    } },
  vendes: { titol: 'Vendes per producte', rang: true, json: (q) => `/locals/${S.local}/informe/vendes?${q}`, csv: (q) => `/locals/${S.local}/informe/vendes.csv?${q}`, fitxer: 'vendes',
    pinta: (r) => [h('div', { class: 'row' }, kpi('Vendes', eur(r.total.import_cent)), kpi('Dispensat', gText(r.total.grams)), kpi('Dispensacions', String(r.total.dispensacions)), r.total.descomptes_cent ? kpi('Descomptes', eur(r.total.descomptes_cent)) : null),
      h('h3', null, 'Per producte'), taula([['Producte'], ['Categoria'], ['Grams', true], ['Import', true], ['Disp.', true]], r.productes.map((p) => [p.nom, p.categoria, gText(p.grams), eur(p.import_cent), p.dispensacions])),
      r.categories.length ? h('div', null, h('h3', null, 'Per categoria'), taula([['Categoria'], ['Grams', true], ['Import', true]], r.categories.map((c) => [c.categoria, gText(c.grams), eur(c.import_cent)]))) : null] },
  dispensacions: { titol: 'Dispensacions', rang: true, json: (q) => `/locals/${S.local}/informe/vendes?${q}`, csv: (q) => `/locals/${S.local}/informe/vendes.csv?${q}`, fitxer: 'dispensacions',
    pinta: (r, ctx) => {
      const dia = (d) => new Date(d + 'T12:00:00').toLocaleDateString(loc(), { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
      const cerca = h('input', { type: 'search', placeholder: 'Buscar…', 'aria-label': 'Buscar producte' });
      const comptador = h('div', { class: 'muted' });
      const cos = h('tbody');
      const pintaFiles = () => {
        const t = cerca.value.trim().toLowerCase();
        const files = r.productes.filter((p) => !t || p.nom.toLowerCase().includes(t) || (p.categoria || '').toLowerCase().includes(t));
        cos.replaceChildren(...(files.length ? files.map((p) => h('tr', null, h('td', null, h('span', { class: 'prod-cell' }, productThumb(p, 32), h('strong', null, p.nom))),
          h('td', { class: 'muted' }, p.categoria), h('td', null, h('input', { type: 'checkbox', checked: p.es_genetic, disabled: true, 'aria-label': 'És genètic' })),
          h('td', { class: 'num' }, gText(p.grams)), h('td', { class: 'num' }, eur(p.import_cent)), h('td', { class: 'num' }, p.dispensacions)))
          : [h('tr', null, h('td', { colspan: 6, class: 'muted' }, 'Sense dades en aquest període.'))]));
        comptador.textContent = 'Quantitat: ' + files.length;
      };
      cerca.addEventListener('input', pintaFiles);
      pintaFiles();
      return [h('p', null, h('strong', null, (ctx && !ctx.tots ? ctx.empleat : 'TOTS ELS EMPLEATS').toUpperCase()), ` DES DE ${dia(r.des)} FINS A ${dia(r.fins)}`),
        h('div', { class: 'row' }, kpi('Dispensat', gText(r.total.grams)), kpi('Import', eur(r.total.import_cent)), kpi('Dispensacions', String(r.total.dispensacions))),
        h('div', { class: 'searchbar' }, cerca),
        h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, h('tr', null, ['Producte', 'Categoria', 'És genètic', 'Grams', 'Import', 'Disp.'].map((t, i) => h('th', { class: i > 2 ? 'num' : '' }, t)))), cos)),
        comptador];
    } },
  estoc: { titol: 'Estoc valorat', rang: false, json: () => `/locals/${S.local}/informe/estoc`, csv: () => `/locals/${S.local}/informe/estoc.csv`, fitxer: 'estoc',
    pinta: (r) => [h('div', { class: 'row' }, kpi('Valor de l\'estoc', eur(r.total_cent)), kpi('Estoc total', gText(r.total_g))),
      taula([['Producte'], ['Categoria'], ['Estoc', true], ['Preu/g', true], ['Valor', true]], r.productes.map((p) => [p.nom, p.categoria, gText(p.estoc_g), eur(p.preu_cent_per_g), eur(p.valor_cent)]), 'Encara no hi ha productes.')] },
  assistencia: { titol: 'Assistència de socis', rang: true, json: (q) => `/locals/${S.local}/informe/assistencia?${q}`, csv: (q) => `/locals/${S.local}/informe/assistencia.csv?${q}`, fitxer: 'assistencia',
    pinta: (r) => [h('div', { class: 'row' }, kpi('Entrades', String(r.total_entrades)), kpi('Socis diferents', String(r.socis_diferents))),
      taula([['Dia'], ['Entrades', true], ['Socis', true]], r.per_dia.map((d) => [d.dia, d.entrades, d.socis]))] },
  hores: { titol: 'Hores del personal', rang: true, json: (q) => `/locals/${S.local}/informe/hores?${q}`, csv: (q) => `/locals/${S.local}/informe/hores.csv?${q}`, fitxer: 'hores',
    pinta: (r) => [h('div', { class: 'row' }, kpi('Hores totals', r.total_hores.toLocaleString(loc()) + ' h')),
      taula([['Persona'], ['Hores', true], ['Torns', true], ['Torn obert']], r.persones.map((p) => [p.usuari, p.hores.toLocaleString(loc()), p.torns, p.torn_obert ? 'sí (sense sortida)' : 'no']))] },
};

function descarrega(blob, nom) {
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: nom });
  document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

VIEWS.informe = async () => {
  const avui = new Date().toLocaleDateString('sv-SE');
  const tipus = h('select', null, Object.entries(INFORMES).map(([k, v]) => h('option', { value: k }, v.titol)));
  const des = h('input', { type: 'date', value: avui }), fins = h('input', { type: 'date', value: avui });
  const out = h('div'), res = h('div');
  const personal = await api(`/locals/${S.local}/personal`);
  const emp = h('select', null, [h('option', { value: '' }, 'Tots els empleats'), ...personal.map((u) => h('option', { value: u.id }, u.username))]);
  const rangBox = h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins), field('Empleat', emp));
  const triat = sessionStorage.getItem('s:informe');
  if (INFORMES[triat]) tipus.value = triat;
  rangBox.hidden = !INFORMES[tipus.value].rang;
  tipus.addEventListener('change', () => { rangBox.hidden = !INFORMES[tipus.value].rang; res.replaceChildren(); sessionStorage.setItem('s:informe', tipus.value); marcaMenu(); });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure informe');
  const csv = h('button', { type: 'button' }, 'Descarregar CSV');
  const q = () => `des=${des.value}&fins=${fins.value}${emp.value ? '&usuari=' + emp.value : ''}`;
  csv.addEventListener('click', () => guard(csv, out, async () => {
    const inf = INFORMES[tipus.value];
    const r = await api(inf.csv(q()), { raw: true });
    if (!r.ok) throw new Error('No s\'ha pogut exportar');
    descarrega(await r.blob(), `${inf.fitxer}-${des.value}_${fins.value}.csv`);
  }));
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const inf = INFORMES[tipus.value];
      const r = await api(inf.json(q()));
      res.replaceChildren(h('div', { class: 'card' }, h('h3', null, inf.titol), ...inf.pinta(r, { empleat: emp.options[emp.selectedIndex].text, tots: !emp.value }).filter(Boolean)));
    });
  } }, h('h3', null, "Tria l'informe"), field('Informe', tipus), rangBox, h('div', { class: 'actions' }, btn, csv), out);
  // Si s'hi arriba des del menú lateral (Vendes, Dispensacions…), l'informe es mostra de seguida.
  if (INFORMES[triat]) setTimeout(() => form.requestSubmit(), 0);
  return h('div', null, pageHead('Informes', 'Caixa, vendes, dispensacions, estoc valorat, assistència i hores, amb exportació a CSV.'), form, res);
};
