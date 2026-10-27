'use strict';
// Pantalles: Estoc, Caixa, Fitxatge, Informe.

VIEWS.estoc = async () => {
  const prods = await api(`/locals/${S.local}/estoc`);
  const box = h('div', null, h('h2', null, 'Estoc'));
  box.append(h('div', { class: 'card' }, h('table', null,
    h('thead', null, h('tr', null, h('th', null, 'Producte'), h('th', null, 'Categoria'), h('th', { class: 'num' }, 'Preu/g'), h('th', { class: 'num' }, 'Estoc'))),
    h('tbody', null, prods.length ? prods.map((p) => h('tr', null, h('td', null, p.nom), h('td', { class: 'muted' }, p.categoria),
      h('td', { class: 'num' }, eur(p.preu_cent_per_g)), h('td', { class: 'num' }, p.estoc_g + ' g')))
      : h('tr', null, h('td', { colspan: 4, class: 'muted' }, 'Encara no hi ha productes.'))))));
  if (!isManager()) return box;

  const out = h('div');
  const accio = h('select', null, [['entrada', 'Entrada d\'estoc'], ['merma', 'Merma'], ['ajust', 'Ajust d\'inventari (quantitat real)']]
    .map(([v, t]) => h('option', { value: v }, t)));
  const prod = h('select', null, prods.map((p) => h('option', { value: p.id }, p.nom)));
  const g = h('input', { inputmode: 'decimal', placeholder: '0,000' });
  const nota = h('input', { placeholder: 'Motiu / albarà' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      if (!prod.value) throw new Error('Crea primer un producte');
      const a = accio.value;
      const body = a === 'ajust' ? { product_id: Number(prod.value), grams_reals: parseGrams(g.value), nota: nota.value.trim() }
        : { product_id: Number(prod.value), grams: parseGrams(g.value), nota: nota.value.trim() || null };
      await api('/moviments/' + a, { method: 'POST', body });
      toast('Moviment registrat');
      show('estoc');
    });
  } }, h('h2', null, 'Moviment d\'estoc'),
  h('div', { class: 'row' }, field('Operació', accio), field('Producte', prod)),
  h('div', { class: 'row' }, field('Quantitat (g)', g), field('Nota', nota)),
  h('div', { class: 'actions' }, btn), out));

  const out2 = h('div');
  const n = h('input'), c = h('input'), p = h('input', { inputmode: 'decimal', placeholder: '8,00' });
  const b2 = h('button', { type: 'submit' }, 'Crear producte');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(b2, out2, async () => {
      await api('/productes', { method: 'POST', body: { local_id: S.local, nom: n.value.trim(), categoria: c.value.trim(), preu_cent_per_g: parseEur(p.value) } });
      toast('Producte creat');
      show('estoc');
    });
  } }, h('h2', null, 'Nou producte'),
  h('div', { class: 'row' }, field('Nom', n), field('Categoria', c), field('Preu per gram (€)', p)),
  h('div', { class: 'actions' }, b2), out2));
  return box;
};

VIEWS.caixa = async () => {
  const st = await api(`/locals/${S.local}/caixa`);
  const box = h('div', null, h('h2', null, 'Caixa'));
  const out = h('div');
  if (!st.oberta) {
    box.append(h('div', { class: 'card' }, h('span', { class: 'pill warn' }, 'Tancada')));
    if (!isManager()) return box;
    const ini = h('input', { inputmode: 'decimal', placeholder: '0,00' });
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Obrir caixa');
    box.append(h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => { await api('/caixa/obrir', { method: 'POST', body: { local_id: S.local, opening_cent: parseEur(ini.value) } }); show('caixa'); });
    } }, field('Efectiu inicial al calaix (€)', ini), h('div', { class: 'actions' }, btn), out));
    return box;
  }
  box.append(h('div', { class: 'card' }, h('span', { class: 'pill ok' }, 'Oberta'),
    h('p', null, 'Obertura: ', h('strong', null, eur(st.obertura_cent))),
    st.esperat_cent != null ? h('p', null, 'Efectiu esperat ara: ', h('strong', null, eur(st.esperat_cent))) : null));
  if (!isManager()) return box;

  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00' });
  const met = h('select', null, ['efectiu', 'targeta'].map((m) => h('option', { value: m }, m)));
  const cat = h('input', { placeholder: 'neteja, compres, nòmines…' });
  const con = h('input');
  const b1 = h('button', { type: 'submit' }, 'Registrar despesa');
  const out1 = h('div');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(b1, out1, async () => {
      await api('/despeses', { method: 'POST', body: { local_id: S.local, cent: parseEur(imp.value), metode: met.value, categoria: cat.value.trim(), concepte: con.value.trim() } });
      toast('Despesa registrada');
      show('caixa');
    });
  } }, h('h2', null, 'Despesa'),
  h('div', { class: 'row' }, field('Import (€)', imp), field('Mètode', met), field('Categoria', cat)),
  field('Concepte', con), h('div', { class: 'actions' }, b1), out1));

  const comptat = h('input', { inputmode: 'decimal', placeholder: '0,00' });
  const b2 = h('button', { class: 'danger', type: 'submit' }, 'Tancar caixa');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(b2, out, async () => {
      const r = await api('/caixa/tancar', { method: 'POST', body: { local_id: S.local, counted_cent: parseEur(comptat.value) } });
      const d = r.diferencia_cent;
      box.replaceChildren(h('h2', null, 'Caixa tancada'), h('div', { class: 'card' },
        h('p', null, 'Esperat: ', h('strong', null, eur(r.esperat_cent))), h('p', null, 'Comptat: ', h('strong', null, eur(r.comptat_cent))),
        h('p', null, 'Diferència: ', h('span', { class: 'pill ' + (d === 0 ? 'ok' : 'bad') }, (d > 0 ? '+' : '') + eur(d)))));
    });
  } }, h('h2', null, 'Tancament'), field('Efectiu comptat al calaix (€)', comptat), h('div', { class: 'actions' }, b2), out));
  return box;
};

VIEWS.fitxatge = async () => {
  const out = h('div');
  const btns = [['entrada', 'Entrada'], ['pausa_inici', 'Inici de pausa'], ['pausa_fi', 'Fi de pausa'], ['sortida', 'Sortida']].map(([t, label]) => {
    const b = h('button', { class: t === 'entrada' ? 'primary' : '', onclick: () => guard(b, out, async () => {
      await api('/fitxatge', { method: 'POST', body: { local_id: S.local, tipus: t } });
      out.replaceChildren(msg('ok', label + ' registrada a les ' + new Date().toLocaleTimeString('ca-ES', { hour: '2-digit', minute: '2-digit' })));
    }) }, label);
    return b;
  });
  return h('div', null, h('h2', null, 'Fitxatge'), h('div', { class: 'card' }, h('div', { class: 'actions' }, btns), out));
};

VIEWS.informe = async () => {
  const avui = new Date().toLocaleDateString('sv-SE');
  const des = h('input', { type: 'date', value: avui }), fins = h('input', { type: 'date', value: avui });
  const out = h('div'), res = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Veure informe');
  const csv = h('button', { type: 'button' }, 'Descarregar CSV');
  const q = () => `des=${des.value}&fins=${fins.value}`;
  csv.addEventListener('click', () => guard(csv, out, async () => {
    const r = await api(`/locals/${S.local}/apunts.csv?${q()}`, { raw: true });
    if (!r.ok) throw new Error('No s\'ha pogut exportar');
    const url = URL.createObjectURL(await r.blob());
    const a = h('a', { href: url, download: `apunts-${des.value}_${fins.value}.csv` });
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }));
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api(`/locals/${S.local}/informe?${q()}`);
      const cats = Object.entries(r.despeses_per_categoria);
      res.replaceChildren(h('div', { class: 'card' },
        h('div', { class: 'row' },
          h('div', null, h('div', { class: 'muted' }, 'Ingressos'), h('div', { class: 'big' }, eur(r.ingressos_cent))),
          h('div', null, h('div', { class: 'muted' }, 'Despeses'), h('div', { class: 'big' }, eur(r.despeses_cent))),
          h('div', null, h('div', { class: 'muted' }, 'Resultat'), h('div', { class: 'big' }, eur(r.resultat_cent))),
          h('div', null, h('div', { class: 'muted' }, 'Dispensat'), h('div', { class: 'big' }, grams(r.dispensat_mg)))),
        cats.length ? h('div', null, h('h3', null, 'Despeses per categoria'), h('table', null, h('tbody', null,
          cats.map(([k, v]) => h('tr', null, h('td', null, k), h('td', { class: 'num' }, eur(v)))))) ) : null,
        h('h3', null, 'Per dia'), h('table', null, h('tbody', null, Object.entries(r.per_dia).map(([d, v]) =>
          h('tr', null, h('td', null, d), h('td', { class: 'num' }, eur(v.ingressos_cent)), h('td', { class: 'num' }, eur(v.despeses_cent === 0 ? 0 : -v.despeses_cent))))))));
    });
  } }, h('h2', null, 'Informe'), h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)),
  h('div', { class: 'actions' }, btn, csv), out);
  return h('div', null, form, res);
};
