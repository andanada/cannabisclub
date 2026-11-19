'use strict';
// Finestra de dispensació d'un soci: capçalera (nom, incidències, consum del mes, historial), categories, productes i carret.
// Es paga sempre del saldo del soci (la caixa és a recepció); un producte pot dispensar-se com a regal.

const mgNum = (txt) => { const v = Number(String(txt).trim().replace(',', '.')); return String(txt).trim() === '' ? NaN : v; };
const qText = (v) => String(Math.round(v * 1000) / 1000).replace('.', ',');

function historialConsumModal(m) {
  obreModal('Historial de consum · ' + m.nom, () => {
    const cos = h('div', null, h('p', { class: 'muted' }, 'Carregant…'));
    api(`/socis/${m.id}/resum-dispensar`).then((r) => cos.replaceChildren(
      taula([['Data'], ['Producte'], ['Quantitat', true], ['Import', true]], r.darreres.map((x) => [horaCa(x.ts), x.producte, qText(Number(x.quantitat)) + ' ' + x.unitat,
        x.regal ? h('span', { class: 'pill' }, 'regal') : eur(x.import_cent)]), 'Encara no ha retirat res.'))).catch((e) => cos.replaceChildren(msg('err', e.message)));
    return cos;
  });
}

// Fitxa completa del soci en una finestra (en prémer el nom).
function fitxaModal(m) {
  obreModal(m.nom, () => { const out = h('div'); return h('div', null, memberCard(m, out, () => {}), out); });
}

async function pantallaDispensar(m, tornar) {
  const loc = S.me.locals.find((l) => l.id === S.local) || {};
  const [productes, resum, caixa] = await Promise.all([api(`/locals/${S.local}/estoc?soci=${m.id}`), api(`/socis/${m.id}/resum-dispensar`), api(`/locals/${S.local}/caixa`).catch(() => ({ oberta: true })), carregaMetaCat()]);
  const decimals = loc.decimals_dispensacio ?? 3;
  const pct = m.estat === 'actiu' ? (m.descompte_pct || 0) : 0;
  const carret = new Map();   // product_id -> {p, q (text), regal}
  const out = h('div');
  const arrel = h('div', { class: 'dispensa-nou' });

  // ---- capçalera ----
  const nomBtn = h('button', { type: 'button', class: 'nom-soci', 'aria-label': 'Obrir la fitxa de ' + m.nom }, m.nom);
  nomBtn.addEventListener('click', () => fitxaModal(m));
  const histBtn = h('button', { type: 'button', class: 'small' }, 'Historial de consum');
  histBtn.addEventListener('click', () => historialConsumModal(m));
  const canvia = h('button', { type: 'button', class: 'small' }, 'Canviar de soci');
  canvia.addEventListener('click', tornar);
  const cap = h('div', { class: 'card dis-soci' }, fotoSoci(m.id, m.nom, 84),
    h('div', { class: 'dis-soci-dades' }, nomBtn,
      h('div', null, h('span', { class: 'pill ' + (m.estat === 'actiu' ? 'ok' : 'bad') }, m.estat), ' ', quotaPill(m.quota), ' ',
        m.tipus && m.tipus !== 'Ordinari' ? h('span', { class: 'pill' }, `${m.tipus}${pct ? ' · ' + pct + ' %' : ''}`) : null),
      h('div', { class: 'dis-soci-xifres' }, kpi('Consumit aquest mes', gText(resum.mes_g)), kpi('Saldo', eur(resum.saldo_cent)))),
    h('div', { class: 'dis-soci-accions' }, histBtn, canvia));
  const bloc = !caixa.oberta && !caixa.ambigua ? msg('err', "La caixa de recepció està tancada: demana a recepció que l'obri per poder dispensar (el pagament entra a la caixa).")
    : m.estat !== 'actiu' ? msg('err', m.estat === 'expulsat' ? 'Soci expulsat: no es pot dispensar.' : 'El soci no està actiu: no es pot dispensar.')
    : (loc.quota_obligatoria && !(m.quota && m.quota.al_dia) ? msg('err', 'La quota del soci no està al dia: cal cobrar-la a recepció abans de dispensar.') : null);

  // ---- productes ----
  let cat = '';
  const cats = [...new Set(productes.map((p) => p.categoria).filter(Boolean))].sort();
  const graella = h('div', { class: 'products' });
  const chips = h('div', { class: 'dis-cats', role: 'group', 'aria-label': 'Categories' });
  const pintaGraella = () => graella.replaceChildren(...productes.filter((p) => !cat || p.categoria === cat).map((p) => {
    const sensEstoc = !(mgNum(p.estoc_g) > 0);
    const b = h('button', { type: 'button', class: 'prod' + (sensEstoc ? ' sense-estoc' : ''), disabled: sensEstoc || !!bloc, 'aria-pressed': String(carret.has(p.id)) },
      productThumb(p, 44), h('strong', null, catBadge(p.categoria), ' ', p.nom), h('span', { class: 'prod-preu' }, eur(p.preu_cent_per_g) + '/' + unitTxt(p)),
      h('span', { class: 'muted' }, sensEstoc ? 'Sense estoc' : p.estoc_g + ' ' + unitTxt(p)));
    b.addEventListener('click', () => { if (!carret.has(p.id)) carret.set(p.id, { p, q: '1', regal: false }); pintaCarret(); pintaGraella(); });
    return b;
  }));
  [''].concat(cats).forEach((c) => {
    const b = h('button', { type: 'button', class: 'small', 'aria-pressed': String(c === cat) }, c || 'Tots');
    b.addEventListener('click', () => { cat = c; [...chips.children].forEach((x) => x.setAttribute('aria-pressed', String(x === b))); pintaGraella(); });
    chips.append(b);
  });

  // ---- carret ----
  const liniesBox = h('div', { class: 'carret-linies' });
  const totalsBox = h('div', { class: 'carret-totals' });
  const btnDispensar = h('button', { class: 'primary gran', type: 'button' }, 'Dispensar');
  const calcula = () => {
    let subtotal = 0, descompte = 0, error = null;
    for (const l of carret.values()) {
      const q = mgNum(l.q);
      if (!Number.isFinite(q) || q <= 0) { error = error || `Quantitat no vàlida a «${l.p.nom}»`; continue; }
      if (q > mgNum(l.p.estoc_g) + 1e-9) error = error || `No hi ha prou estoc de «${l.p.nom}» (en queden ${l.p.estoc_g} ${unitTxt(l.p)})`;
      const d = l.p.unitat === 'u' || l.p.granel === false ? 0 : decimals;
      if (Math.abs(q * 10 ** d - Math.round(q * 10 ** d)) > 1e-9) error = error || `«${l.p.nom}» només admet ${d ? d + ' decimals' : 'quantitats senceres'}`;
      const import0 = l.regal ? 0 : Math.round(q * l.p.preu_cent_per_g);
      subtotal += import0;
      if (!l.regal && !l.p.sense_descomptes && pct) descompte += Math.round(import0 * pct / 100);
    }
    return { subtotal, descompte, total: subtotal - descompte, error };
  };
  function pintaCarret() {
    liniesBox.replaceChildren(...(carret.size ? [...carret.values()].map((l) => {
      const q = h('input', { class: 'carret-q', inputmode: 'decimal', value: l.q, 'aria-label': 'Quantitat de ' + l.p.nom });
      q.addEventListener('input', () => { l.q = q.value; pintaTotals(); });
      const pas = l.p.unitat === 'u' || decimals === 0 ? 1 : 0.5;
      const ajusta = (s) => { const v = Math.max(0, (Number.isFinite(mgNum(l.q)) ? mgNum(l.q) : 0) + s * pas); l.q = qText(v); q.value = l.q; pintaTotals(); };
      const menys = h('button', { type: 'button', class: 'small', 'aria-label': 'Menys' }, '−');
      const mes = h('button', { type: 'button', class: 'small', 'aria-label': 'Més' }, '+');
      menys.addEventListener('click', () => ajusta(-1)); mes.addEventListener('click', () => ajusta(1));
      const pesar = h('button', { type: 'button', class: 'small', 'aria-label': 'Agafar el pes de la bàscula' }, '⚖');
      pesar.addEventListener('click', () => pesDeBascula(q, out));
      q.addEventListener('change', () => { l.q = q.value; pintaTotals(); });
      const regal = l.p.regalable ? h('label', { class: 'check' }, (() => { const c = h('input', { type: 'checkbox', checked: l.regal }); c.addEventListener('change', () => { l.regal = c.checked; pintaTotals(); }); return c; })(), ' Regal') : null;
      const lleva = h('button', { type: 'button', class: 'small danger', 'aria-label': 'Treure ' + l.p.nom }, '✕');
      lleva.addEventListener('click', () => { carret.delete(l.p.id); pintaCarret(); pintaGraella(); });
      return h('div', { class: 'carret-linia' }, h('div', { class: 'carret-nom' }, h('strong', null, l.p.nom), h('span', { class: 'muted' }, eur(l.p.preu_cent_per_g) + '/' + unitTxt(l.p))),
        h('div', { class: 'carret-ctrl' }, menys, q, h('span', { class: 'muted' }, unitTxt(l.p)), mes, pesar), regal, lleva);
    }) : [h('p', { class: 'muted' }, 'El carret és buit. Toca un producte per afegir-lo.')]));
    pintaTotals();
  }
  function pintaTotals() {
    const t = calcula();
    const falta = t.total - resum.saldo_cent;
    totalsBox.replaceChildren(...[
      h('div', { class: 'carret-fila' }, h('span', null, 'Subtotal'), h('span', null, eur(t.subtotal))),
      pct ? h('div', { class: 'carret-fila desc' }, h('span', null, `Descompte de membre (${pct} %)`), h('span', null, '−' + eur(t.descompte))) : null,
      h('div', { class: 'carret-fila total' }, h('span', null, 'Total'), h('span', null, eur(t.total))),
      h('div', { class: 'carret-fila' }, h('span', { class: 'muted' }, 'Saldo del soci'), h('span', { class: 'muted' }, eur(resum.saldo_cent))),
      t.error ? msg('err', t.error) : (falta > 0 && carret.size ? msg('err', `Saldo insuficient: falten ${eur(falta)}. El soci ha de fer una donació a recepció.`) : null)].filter(Boolean));
    btnDispensar.disabled = !carret.size || !!t.error || falta > 0 || !!bloc;
  }
  let ref = novaRef();
  const guardRepinta = (fn) => guard(btnDispensar, out, fn).then(() => { if (btnDispensar.isConnected) pintaTotals(); });
  btnDispensar.addEventListener('click', () => guardRepinta(async () => {
    const t = calcula();
    if (t.error) throw new Error(t.error);
    const linies = [...carret.values()].map((l) => ({ product_id: l.p.id, grams: parseGrams(l.q), regal: l.regal }));
    const r = await api('/dispensacions/carret', { method: 'POST', body: { client_ref: ref, member_id: m.id, linies } });
    ref = novaRef();
    const nova = h('button', { class: 'primary gran', type: 'button' }, 'Nova dispensació');
    nova.addEventListener('click', tornar);
    arrel.replaceChildren(h('div', { class: 'card dis-fet', role: 'status' }, h('div', { class: 'dis-check', 'aria-hidden': 'true' }, '✓'),
      h('h2', null, `Dispensat a ${m.nom}`), h('p', { class: 'dis-total' }, eur(r.total_cent)),
      taula([['Producte'], ['Quantitat', true], ['Import', true]], r.linies.map((x) => [x.producte, qText(Number(x.quantitat)) + ' ' + x.unitat, x.regal ? h('span', { class: 'pill' }, 'regal') : eur(x.import_cent)]), ''),
      r.descompte_cent ? h('p', { class: 'muted' }, 'Descompte aplicat: −' + eur(r.descompte_cent)) : null,
      h('p', { class: 'muted' }, 'Saldo que li queda: ' + eur(r.saldo_cent)), h('div', { class: 'actions' }, nova)));
  }));

  arrel.append(...[cap, alertesSoci(m.alertes), bloc,
    h('div', { class: 'dis-cos' },
      h('section', { class: 'card dis-prods' }, h('h3', null, 'Productes'), cats.length ? chips : null, graella),
      h('section', { class: 'card dis-carret' }, h('h3', null, 'Carret'), liniesBox,
        h('details', { class: 'dis-mes' }, h('summary', null, 'Bàscula'), scalePanel(h('input'), h('input'))), totalsBox, h('div', { class: 'actions' }, btnDispensar), out))].filter(Boolean));
  pintaGraella();
  pintaCarret();
  return arrel;
}
