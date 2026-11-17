'use strict';
// Despeses i comptabilitat (només responsables): llistat amb filtre de dates i alta, tipus i categories de despesa,
// tipus de compte (suma/resta) i comptes comptables. Mai innerHTML.

const OPERACIO_TXT = { suma: 'Suma', resta: 'Resta' };

// Catàleg simple (nom + descripció + actiu): categories i tipus de despesa.
async function secCataleg(quin, nouTxt, creatTxt, plural) {
  const llista = await api(`/locals/${S.local}/gastos/${quin}`);
  const out = h('div');
  const nom = h('input', { maxlength: 60, required: true }), desc = h('input', { maxlength: 200 });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Afegir');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/gastos/${quin}`, { method: 'POST', body: { nom: nom.value.trim(), descripcio: desc.value.trim() || null } });
      toast(creatTxt);
      show('gastos');
    });
  } }, h('h3', null, nouTxt), h('div', { class: 'row' }, field('Nom', nom), field('Descripció', desc)), h('div', { class: 'actions' }, btn), out);
  const files = llista.map((r) => {
    const b = h('button', { type: 'button', class: 'small' }, r.actiu ? 'Desactivar' : 'Reactivar');
    b.addEventListener('click', () => guard(b, out, async () => {
      await api(`/gastos/${quin}/${r.id}`, { method: 'PUT', body: { actiu: !r.actiu } });
      show('gastos');
    }));
    return [r.nom, r.descripcio, h('span', { class: 'pill ' + (r.actiu ? 'ok' : 'warn') }, r.actiu ? 'actiu' : 'inactiu'), b];
  });
  return h('div', null, form, h('h3', null, plural), taula([['Nom'], ['Descripció'], ['Estat'], ['']], files, 'Encara no n\'hi ha cap.'));
}

async function secComptes() {
  const [tipus, comptes] = await Promise.all([api(`/locals/${S.local}/gastos/tipus-compte`), api(`/locals/${S.local}/gastos/comptes`)]);
  const out = h('div');
  // tipus de compte
  const tn = h('input', { maxlength: 60, required: true }), td = h('input', { maxlength: 200 });
  const top = h('select', null, Object.entries(OPERACIO_TXT).map(([k, v]) => h('option', { value: k }, v)));
  const tdesp = h('input', { type: 'checkbox' });
  const bt = h('button', { class: 'primary', type: 'submit' }, 'Afegir tipus de compte');
  const formTipus = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bt, out, async () => {
      await api(`/locals/${S.local}/gastos/tipus-compte`, { method: 'POST', body: { nom: tn.value.trim(), descripcio: td.value.trim() || null, operacio: top.value, es_despesa: tdesp.checked } });
      toast('Tipus de compte creat');
      show('gastos');
    });
  } }, h('h3', null, 'Nou tipus de compte'), h('div', { class: 'row' }, field('Nom', tn), field('Descripció', td), field('Operació', top)),
  h('label', null, tdesp, ' És de despesa'), h('div', { class: 'actions' }, bt));
  // comptes
  const num = h('input', { maxlength: 20, required: true }), cd = h('input', { maxlength: 200 });
  const ctip = h('select', null, tipus.map((t) => h('option', { value: t.id }, t.nom)));
  const bc = h('button', { class: 'primary', type: 'submit' }, 'Afegir compte');
  const formCompte = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bc, out, async () => {
      if (!tipus.length) throw new Error('Crea primer un tipus de compte');
      await api(`/locals/${S.local}/gastos/comptes`, { method: 'POST', body: { numero: num.value.trim(), descripcio: cd.value.trim() || null, tipus_id: Number(ctip.value) } });
      toast('Compte creat');
      show('gastos');
    });
  } }, h('h3', null, 'Nou compte comptable'), h('div', { class: 'row' }, field('Número', num), field('Descripció', cd), field('Tipus', ctip)), h('div', { class: 'actions' }, bc));
  return h('div', null, formTipus, taula([['Tipus de compte'], ['Descripció'], ['Operació'], ['De despesa']], tipus.map((t) => [t.nom, t.descripcio, OPERACIO_TXT[t.operacio], t.es_despesa ? 'sí' : 'no']), 'Cap tipus de compte.'),
    formCompte, taula([['Número'], ['Descripció'], ['Tipus'], ['Import', true]], comptes.map((c) => [c.numero, c.descripcio, c.tipus, eur(c.import_cent)]), 'Cap compte.'), out);
}

async function secDespeses() {
  const [cats, tips, comptes] = await Promise.all([api(`/locals/${S.local}/gastos/categories`), api(`/locals/${S.local}/gastos/tipus`), api(`/locals/${S.local}/gastos/comptes`)]);
  const avui = new Date().toLocaleDateString('sv-SE');
  const fa30 = new Date(Date.now() - 30 * 86400000).toLocaleDateString('sv-SE');
  const out = h('div'), res = h('div');
  const data = h('input', { type: 'date', value: avui, max: avui, required: true });
  const tipus = h('select', null, tips.filter((t) => t.actiu).map((t) => h('option', { value: t.id }, t.nom)));
  const cat = h('select', null, cats.filter((c) => c.actiu).map((c) => h('option', { value: c.id }, c.nom)));
  const compte = h('select', null, h('option', { value: '' }, '—'), ...comptes.map((c) => h('option', { value: c.id }, c.numero + (c.descripcio ? ' · ' + c.descripcio : ''))));
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00', required: true });
  const caixa = h('select', null, h('option', { value: '' }, 'No (no surt de la caixa)'), ...['efectiu', 'targeta', 'bizum'].map((m) => h('option', { value: m }, 'Sí, de la caixa: ' + m)));
  const com = h('input', { maxlength: 300 });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar despesa');
  const ref = { v: novaRef() };
  const des = h('input', { type: 'date', value: fa30 }), fins = h('input', { type: 'date', value: avui });
  const carrega = async () => {
    const l = await api(`/locals/${S.local}/gastos?des=${des.value}&fins=${fins.value}`);
    const total = l.reduce((s, x) => s + (x.anulacio ? -x.import_cent : (x.anulada ? 0 : x.import_cent)), 0);
    res.replaceChildren(h('div', { class: 'row' }, kpi('Despeses vigents', eur(total)), kpi('Apunts', String(l.length))),
      taula([['Data'], ['Empleat'], ['Tipus'], ['Categoria'], ['Compte'], ['Import', true], ['Comentaris'], ['']], l.map((x) => {
        const an = h('button', { type: 'button', class: 'small danger' }, 'Anul·lar');
        an.addEventListener('click', () => guard(an, out, async () => {
          const nota = com.value.trim();
          if (nota.length < 3) throw new Error('Escriu el motiu a «Comentaris» per poder anul·lar');
          await api(`/gastos/${x.id}/anulacio`, { method: 'POST', body: { nota } });
          toast('Despesa anul·lada');
          await carrega();
        }));
        return [x.data, x.empleat, x.tipus, x.categoria, x.compte, eur(x.anulacio ? -x.import_cent : x.import_cent),
          x.anulacio ? 'anul·lació: ' + x.comentaris : (x.comentaris + (x.caixa ? ' (de caixa)' : '')),
          x.anulacio || x.anulada ? h('span', { class: 'muted' }, x.anulada ? 'anul·lada' : '') : an];
      }), 'Cap despesa en aquest període.'));
  };
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      if (!tipus.value || !cat.value) throw new Error('Crea abans un tipus i una categoria de despesa');
      await api('/gastos', { method: 'POST', body: { client_ref: ref.v, local_id: S.local, data: data.value, type_id: Number(tipus.value), category_id: Number(cat.value),
        account_id: compte.value ? Number(compte.value) : null, import_cent: parseEur(imp.value), metode: caixa.value || null, comentaris: com.value.trim() || null } });
      ref.v = novaRef();
      imp.value = ''; com.value = '';
      toast('Despesa registrada');
      await carrega();
    });
  } }, h('h3', null, 'Nova despesa'),
  h('div', { class: 'row' }, field('Data', data), field('Tipus', tipus), field('Categoria', cat)),
  h('div', { class: 'row' }, field('Compte comptable', compte), field('Import (€)', imp), field('Surt de la caixa?', caixa)),
  field('Comentaris', com), h('div', { class: 'actions' }, btn));
  const filtre = h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); guard(fb, out, carrega); } },
    h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, ...[]));
  const fb = h('button', { class: 'primary', type: 'submit' }, 'Filtrar');
  filtre.querySelector('.actions').append(fb);
  await carrega();
  return h('div', null, form, filtre, res, out);
}

VIEWS.gastos = async () => h('div', null, pageHead('Despeses', 'Despeses del local i comptabilitat bàsica.'), sections('gastos', [
  ['despeses', 'Despeses', secDespeses], ['categories', 'Categories', () => secCataleg('categories', 'Nova categoria', 'Categoria creada', 'Categories')],
  ['tipus', 'Tipus de despesa', () => secCataleg('tipus', 'Nou tipus de despesa', 'Tipus de despesa creat', 'Tipus de despesa')], ['comptabilitat', 'Comptabilitat', secComptes],
]));
