'use strict';
// Estoc › Inventaris (control amb pesos reals; es guarda amb «Guardar» i no toca l'estoc), Resultats (gerència) i Historial amb dates.

const INV_TIPUS = { dispensari: 'Dispensari', magatzem: 'Magatzem', no_genetiques: 'No genètics' };

// Llegeix el pes estable de la bàscula (si està connectada) i el posa a l'input.
async function pesDeBascula(input, out) {
  try {
    if (typeof BASCULA === 'undefined' || !BASCULA || !BASCULA.connected) throw new Error('Connecta la bàscula (Dispensar › carret › Bàscula) o escriu el pes a mà');
    const r = await BASCULA.readStable();
    if (r.mg <= 0) throw new Error('La bàscula marca ' + r.raw);
    input.value = mgToG(r.mg);
    input.dispatchEvent(new Event('change'));
  } catch (e) { out.replaceChildren(msg('err', e.message)); }
}

function filaPesatge(sid, l, tipus) {
  const pes = h('input', { inputmode: 'decimal', value: l.pes_g ?? '', placeholder: '0', 'aria-label': 'Pes de ' + l.nom, class: 'inv-pes' });
  const res = h('span', { class: 'pill' }, l.comptat_g === null ? 'sense pesar' : '');
  const nota = h('textarea', { rows: 1, maxlength: 300, placeholder: 'Comentari de la diferència', 'aria-label': 'Comentari', class: 'inv-nota' });
  const out = h('span');
  nota.value = l.nota || '';
  nota.hidden = true;
  const pinta = (r) => {
    if (r.a_cegues || r.diferencia_g === undefined) {   // sense permís de resultats: no es veu l'estoc del sistema ni la diferència
      res.className = 'pill ok';
      res.textContent = '✓ pes desat';
      nota.hidden = false;
      return;
    }
    res.className = 'pill ' + (r.coincideix ? 'ok' : 'warn');
    res.textContent = r.coincideix ? '✓ coincideix amb el sistema' : `Diferència ${Number(r.diferencia_g) > 0 ? '+' : ''}${r.diferencia_g} (sistema: ${r.esperat_g})`;
    nota.hidden = r.coincideix;
  };
  if (l.comptat_g !== null) pinta(l.diferencia_g === undefined ? { a_cegues: true } : { coincideix: Number(l.diferencia_g) === 0, diferencia_g: l.diferencia_g, esperat_g: l.esperat_g });
  const comprova = async () => {
    if (pes.value.trim() === '') return;
    try {
      const r = await api(`/inventaris/${sid}/linies/${l.product_id}`, { method: 'PUT', body: { grams: parseGrams(pes.value), nota: nota.value.trim() || null } });
      out.replaceChildren();
      pinta(r);
    } catch (e) { out.replaceChildren(msg('err', e.message)); }
  };
  const bot = h('button', { type: 'button', class: 'small' }, 'Comprovar');
  bot.addEventListener('click', comprova);
  pes.addEventListener('change', comprova);
  nota.addEventListener('change', comprova);
  const pesar = h('button', { type: 'button', class: 'small', 'aria-label': 'Agafar el pes de la bàscula' }, '⚖');
  pesar.addEventListener('click', () => pesDeBascula(pes, out));
  return h('tr', null, h('td', null, l.nom, l.categoria ? h('div', { class: 'muted' }, l.categoria) : ''),
    h('td', null, tipus === 'dispensari' && Number(l.tara_g) ? `${pesText(l.tara_g)} g` : '—'),
    h('td', null, h('div', { class: 'actions' }, pes, pesar, bot)), h('td', null, res, nota, out));
}

async function pantallaPesatge(sid, tornar) {
  const d = await api(`/inventaris/${sid}`);
  const out = h('div');
  const guarda = h('button', { class: 'primary', type: 'button' }, 'Guardar');
  guarda.addEventListener('click', () => guard(guarda, out, async () => {
    const r = await api(`/inventaris/${sid}/guardar`, { method: 'POST' });
    toast('Inventari guardat');
    tornar(r);
  }));
  const cancela = h('button', { type: 'button', class: 'danger' }, 'Cancel·lar inventari');
  cancela.addEventListener('click', () => guard(cancela, out, async () => {
    if (!await confirma('Es perdrà el que has pesat. Cancel·lar l\'inventari?', { perill: true, boto: 'Cancel·lar inventari' })) return;
    await api(`/inventaris/${sid}/cancelar`, { method: 'POST' });
    toast('Inventari cancel·lat');
    tornar(null);
  }));
  return h('div', null, h('div', { class: 'card' }, h('h3', null, d.nom), h('p', { class: 'muted' }, INV_TIPUS[d.tipus], ' · ', d.control === 'producte' ? "control d'un sol producte" : 'inventari complet', ` · ${d.comptats} de ${d.total} pesats`),
    h('p', { class: 'muted' }, d.tipus === 'dispensari' ? 'Escriu el pes del pot sencer: el programa en resta la tara.' : 'Escriu el pes o agafa\'l de la bàscula.'), te('resultats_inventari') ? null : h('p', { class: 'muted' }, 'Inventari a cegues: el programa no ensenya el que hi hauria de ser; la gerència veu les diferències als resultats.'),
    h('div', { class: 'actions' }, guarda, cancela), out),
  h('div', { class: 'card table-wrap' }, h('table', null, h('thead', null, h('tr', null, ['Producte', 'Tara', 'Pes', 'Comprovació'].map((t) => h('th', null, t)))),
    h('tbody', null, d.linies.map((l) => filaPesatge(sid, l, d.tipus))))));
}

function resumGuardat(r, tornar) {
  return h('div', { class: 'card' }, h('h3', null, 'Inventari guardat'),
    h('div', { class: 'row' }, kpi('Productes pesats', String(r.comptats)), kpi('Amb diferència', String(r.diferencies)), kpi('Sense pesar', String(r.pendents))),
    r.alertes.length ? msg('err', 'Hi ha diferències molt grans: ' + r.alertes.map((a) => a.producte).join(', ')) : null,
    h('div', { class: 'actions' }, h('button', { class: 'primary', type: 'button', onclick: tornar }, 'Entesos')));
}

async function inventariSection() {
  const arrel = h('div');
  const carrega = async (resum) => {
    const llista = await api(`/locals/${S.local}/inventaris`);
    const obert = llista.find((x) => x.estat === 'obert');
    if (obert) { arrel.replaceChildren(await pantallaPesatge(obert.id, (r) => (r ? arrel.replaceChildren(resumGuardat(r, () => carrega())) : carrega()))); return; }
    const productes = (await api(`/locals/${S.local}/productes`)).filter((p) => p.actiu);
    const out = h('div');
    const tipus = h('select', { 'aria-label': 'Inventari' }, Object.entries(INV_TIPUS).map(([v, t]) => h('option', { value: v }, t)));
    const control = h('select', { 'aria-label': 'Tipus de control' }, [['complet', 'Inventari complet (final de torn o de dia)'], ['producte', 'Control d\'un sol producte']].map(([v, t]) => h('option', { value: v }, t)));
    const prod = h('select', { 'aria-label': 'Producte' });
    const prodField = field('Producte', prod);
    const repinta = () => {
      prod.replaceChildren(...productes.filter((p) => !!p.es_genetic === (tipus.value !== 'no_genetiques')).map((p) => h('option', { value: p.id }, p.nom)));
      prodField.hidden = control.value !== 'producte';
    };
    tipus.addEventListener('change', repinta); control.addEventListener('change', repinta); repinta();
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Començar inventari');
    arrel.replaceChildren(...(resum ? [resum] : []), h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        await api(`/locals/${S.local}/inventaris`, { method: 'POST', body: { tipus: tipus.value, control: control.value, product_id: control.value === 'producte' ? Number(prod.value) : null } });
        await carrega();
      });
    } }, h('h3', null, 'Nou inventari'), h('div', { class: 'row' }, field('Quin inventari?', tipus), field('Tipus de control', control)), prodField,
    h('p', { class: 'muted' }, 'S\'obre amb la llista dels productes actius d\'aquest lloc. Els resultats es guarden amb el botó «Guardar»; l\'estoc no es toca.'),
    h('div', { class: 'actions' }, btn), out));
  };
  await carrega();
  return arrel;
}

// Resultats dels inventaris guardats (només accés complet), amb avisos de diferència gran i opció d'ajustar l'estoc.
async function resultatsSection() {
  const r = await api(`/locals/${S.local}/inventaris/resultats`);
  const out = h('div');
  return h('div', null, out, ...(r.length ? r.map((i) => {
    const ajusta = i.ajustat ? h('span', { class: 'pill ok' }, 'estoc ajustat') : h('button', { type: 'button', class: 'small' }, 'Ajustar estoc al comptat');
    if (!i.ajustat) ajusta.addEventListener('click', () => guard(ajusta, out, async () => {
      if (!await confirma('L\'estoc quedarà com s\'ha comptat. Ajustar?', { boto: 'Ajustar' })) return;
      const x = await api(`/inventaris/${i.id}/ajustar`, { method: 'POST' });
      toast(`${x.ajustos} ajustos fets`);
      show('estoc');
    }));
    return h('div', { class: 'card' }, h('h3', null, i.nom, ' ', i.alertes ? h('span', { class: 'pill bad' }, `${i.alertes} avís(os)`) : h('span', { class: 'pill ok' }, 'sense avisos')),
      h('p', { class: 'muted' }, `${INV_TIPUS[i.tipus]} · ${horaCa(i.ts)} · ${i.usuari}`),
      taula([['Producte'], ['Sistema', true], ['Comptat', true], ['Diferència', true], ['Comentari']], i.linies.map((l) => [l.producte, l.esperat_g, l.comptat_g,
        h('span', { class: 'pill ' + (l.alerta ? 'bad' : Number(l.diferencia_g) === 0 ? 'ok' : 'warn') }, (Number(l.diferencia_g) > 0 ? '+' : '') + l.diferencia_g), l.nota || '']), 'Cap línia.'),
      h('div', { class: 'actions' }, ajusta));
  }) : [h('div', { class: 'card empty' }, 'Encara no hi ha cap inventari guardat.')]));
}

// Historial de moviments: del més recent al més antic, amb selecció de dates.
async function historialSection() {
  const avui = new Date().toLocaleDateString('sv-SE');
  const fa7 = new Date(Date.now() - 7 * 86400000).toLocaleDateString('sv-SE');
  const des = h('input', { type: 'date', value: fa7, 'aria-label': 'Des de' }), fins = h('input', { type: 'date', value: avui, 'aria-label': 'Fins a' });
  const res = h('div'), out = h('div');
  const carrega = async () => {
    const rows = await api(`/locals/${S.local}/moviments?des=${des.value}&fins=${fins.value}&limit=500`);
    res.replaceChildren(taula([['Data'], ['Tipus'], ['Producte'], ['Quantitat', true], ['Import', true], ['Qui'], ['Nota'], ['']], rows.map((m) => {
      const corregible = te('corregir_estoc') && m.tipus !== 'correccio' && !m.corregit;
      const b = corregible ? h('button', { type: 'button', class: 'small' }, 'Corregir') : null;
      if (b) b.addEventListener('click', () => guard(b, out, () => demanaCorreccio(`/moviments/${m.id}/correccio`, carrega)));
      return [horaCa(m.ts), h('span', null, m.tipus, ' ', m.corregit ? h('span', { class: 'pill warn' }, 'corregit') : null), m.producte, gText(m.grams), m.import_cent == null ? '' : eur(m.import_cent), m.usuari || '', m.nota || '', b];
    }), 'Cap moviment en aquest període.'));
  };
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure');
  const form = h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); guard(btn, out, carrega); } }, h('h3', null, 'Historial de moviments'),
    h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, btn), out);
  await carrega();
  return h('div', null, form, h('div', { class: 'card table-wrap' }, res));
}

VIEWS.estoc = async () => {
  const items = [['productes', 'Productes', productesSection], ['existencies', 'Existències i moviments', existenciesSection], ['inventari', 'Inventaris', inventariSection]];
  if (te('resultats_inventari')) items.push(['resultats', 'Resultats d\'inventaris', resultatsSection]);
  if (te('historial')) items.push(['historial', 'Historial', historialSection]);
  return h('div', null, pageHead('Estoc', 'Productes, existències, inventaris i historial.'), sections('estoc', items));
};

// Eines avançades que ja no són al menú d'Estoc (Configuració › Estoc avançat).
VIEWS['estoc-avancat'] = async () => h('div', null, pageHead('Estoc avançat', 'Categories, descomptes, línies de preu, magatzems, contenidors i regles.'),
  sections('estoc-avancat', [['categories', 'Categories', secCategories], ['descomptes', 'Descomptes', discountsSection], ['linies', 'Línies de preu', priceLinesSection],
    ['magatzems', 'Magatzems', warehousesSection], ['contenidors', 'Contenidors', containersSection], ['tipus-contenidor', 'Tipus de contenidor', containerTypesSection], ['regles', 'Regles', rulesSection]]));
