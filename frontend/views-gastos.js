'use strict';
// Despeses (Configuració › Gastos, només responsables): llistat amb filtre de dates i alta, despeses pendents de revisió
// (les que neixen d'una entrada d'estoc), tipus i categories de despesa. El pla de comptes ja no surt a la UI. Mai innerHTML.

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
      show('config');
    });
  } }, h('h3', null, nouTxt), h('div', { class: 'row' }, field('Nom', nom), field('Descripció', desc)), h('div', { class: 'actions' }, btn), out);
  const files = llista.map((r) => {
    const b = h('button', { type: 'button', class: 'small' }, r.actiu ? 'Desactivar' : 'Reactivar');
    b.addEventListener('click', () => guard(b, out, async () => {
      await api(`/gastos/${quin}/${r.id}`, { method: 'PUT', body: { actiu: !r.actiu } });
      show('config');
    }));
    return [r.nom, r.descripcio, h('span', { class: 'pill ' + (r.actiu ? 'ok' : 'warn') }, r.actiu ? 'actiu' : 'inactiu'), b];
  });
  return h('div', null, form, h('h3', null, plural), taula([['Nom'], ['Descripció'], ['Estat'], ['']], files, 'Encara no n\'hi ha cap.'));
}

// Doble control: cada entrada d'estoc amb preu de compra crea una despesa que la gerència confirma, corregeix o comenta.
async function secPendents() {
  const l = await api(`/locals/${S.local}/gastos/pendents`);
  const out = h('div');
  const accio = (e, b, cos, ok) => b.addEventListener('click', () => guard(b, out, async () => {
    const body = await cos();
    if (!body) return;
    await api(`/gastos/${e.id}/revisio`, { method: 'POST', body });
    toast(ok);
    show('config');
  }));
  const files = l.map((e) => {
    const ok = h('button', { type: 'button', class: 'small primary' }, 'Confirmar');
    const cor = h('button', { type: 'button', class: 'small' }, 'Corregir');
    const com = h('button', { type: 'button', class: 'small' }, 'Comentar');
    accio(e, ok, async () => ({ accio: 'confirma' }), 'Despesa confirmada');
    accio(e, cor, async () => {
      const imp = await demana('Import correcte (€)');
      if (!imp) return null;
      const motiu = await demana('Motiu de la correcció');
      if (!motiu) return null;
      return { accio: 'corregeix', import_cent: parseEur(imp), comentari: motiu };
    }, 'Despesa corregida');
    accio(e, com, async () => { const c = await demana('Comentari'); return c ? { accio: 'comenta', comentari: c } : null; }, 'Comentari desat');
    const notes = e.revisions.map((r) => h('div', { class: 'muted' }, r.usuari + ': ' + r.comentari));
    return [e.data, h('span', null, e.producte || e.comentaris, ...notes), e.quantitat != null ? e.quantitat + ' ' + (e.unitat === 'u' ? 'u' : 'g') : '', eur(e.import_cent), e.empleat, h('span', { class: 'actions fila-accions' }, ok, cor, com)];
  });
  return h('div', null, h('p', { class: 'muted' }, "Cada entrada d'estoc amb preu de compra crea aquesta despesa automàticament. Confirma-la si és correcta, corregeix-ne l'import o deixa-hi un comentari."),
    taula([['Data'], ['Entrada'], ['Quantitat', true], ['Import', true], ['Empleat'], ['']], files, 'Cap despesa pendent de revisar.'), out);
}

async function secDespeses() {
  const [cats, tips] = await Promise.all([api(`/locals/${S.local}/gastos/categories`), api(`/locals/${S.local}/gastos/tipus`)]);
  const avui = new Date().toLocaleDateString('sv-SE');
  const fa30 = new Date(Date.now() - 30 * 86400000).toLocaleDateString('sv-SE');
  const out = h('div'), res = h('div');
  const data = h('input', { type: 'date', value: avui, max: avui, required: true });
  const tipus = h('select', null, tips.filter((t) => t.actiu).map((t) => h('option', { value: t.id }, t.nom)));
  const cat = h('select', null, cats.filter((c) => c.actiu).map((c) => h('option', { value: c.id }, c.nom)));
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00', required: true });
  const caixa = h('select', null, h('option', { value: '' }, 'No (no surt de la caixa)'), ...metodesIngres().map((o) => h('option', { value: o.value }, 'Sí, de la caixa: ' + o.textContent)));
  const com = h('input', { maxlength: 300 });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar despesa');
  const ref = { v: novaRef() };
  const des = h('input', { type: 'date', value: fa30 }), fins = h('input', { type: 'date', value: avui });
  const carrega = async () => {
    const l = await api(`/locals/${S.local}/gastos?des=${des.value}&fins=${fins.value}`);
    const total = l.reduce((s, x) => s + (x.anulacio || x.anulada ? 0 : x.import_cent), 0);
    res.replaceChildren(h('div', { class: 'row' }, kpi('Despeses vigents', eur(total)), kpi('Apunts', String(l.length))),
      taula([['Data'], ['Empleat'], ['Tipus'], ['Categoria'], ['Import', true], ['Comentaris'], ['Revisió'], ['']], l.map((x) => {
        const an = h('button', { type: 'button', class: 'small danger' }, 'Anul·lar');
        an.addEventListener('click', () => guard(an, out, async () => {
          const motiu = await demana("Motiu de l'anul·lació");
          const nota = (motiu || '').trim();
          if (!motiu) return;
          if (nota.length < 3) throw new Error("Escriu el motiu de l'anul·lació (mínim 3 caràcters)");
          await api(`/gastos/${x.id}/anulacio`, { method: 'POST', body: { nota } });
          toast('Despesa anul·lada');
          await carrega();
        }));
        return [x.data, x.empleat, x.tipus, x.categoria, eur(x.anulacio ? -x.import_cent : x.import_cent),
          x.anulacio ? 'anul·lació: ' + x.comentaris : (x.comentaris + (x.caixa ? ' (de caixa)' : '')),
          x.estat ? h('span', { class: 'pill ' + (x.estat === 'pendent' ? 'warn' : 'ok') }, x.estat) : '',
          x.anulacio || x.anulada ? h('span', { class: 'muted' }, x.anulada ? 'anul·lada' : '') : an];
      }), 'Cap despesa en aquest període.'));
  };
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      if (!tipus.value || !cat.value) throw new Error('Crea abans un tipus i una categoria de despesa');
      await api('/gastos', { method: 'POST', body: { client_ref: ref.v, local_id: S.local, data: data.value, type_id: Number(tipus.value), category_id: Number(cat.value),
        account_id: null, import_cent: parseEur(imp.value), metode: caixa.value || null, comentaris: com.value.trim() || null } });
      ref.v = novaRef();
      imp.value = ''; com.value = '';
      toast('Despesa registrada');
      await carrega();
    });
  } }, h('h3', null, 'Nova despesa'),
  h('div', { class: 'row' }, field('Data', data), field('Tipus', tipus), field('Categoria', cat)),
  h('div', { class: 'row' }, field('Import (€)', imp), field('Surt de la caixa?', caixa)),
  field('Comentaris', com), h('div', { class: 'actions' }, btn));
  const filtre = h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); guard(fb, out, carrega); } },
    h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, ...[]));
  const fb = h('button', { class: 'primary', type: 'submit' }, 'Filtrar');
  filtre.querySelector('.actions').append(fb);
  await carrega();
  return h('div', null, form, filtre, res, out);
}

// Es munta dins Configuració › Gastos.
const gastosSection = async () => sections('gastos', [
  ['despeses', 'Despeses', secDespeses], ['pendents', 'Pendents de revisió', secPendents],
  ['categories', 'Categories', () => secCataleg('categories', 'Nova categoria', 'Categoria creada', 'Categories')],
  ['tipus', 'Tipus de despesa', () => secCataleg('tipus', 'Nou tipus de despesa', 'Tipus de despesa creat', 'Tipus de despesa')],
]);
