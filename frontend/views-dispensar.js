'use strict';
// Pantalles: Dispensar (flux complet) i Socis (cerca, alta, estat).

// Quantitat com a nombre (admet coma decimal) i com a text per a la pantalla.
const numG = (txt) => { const v = Number(String(txt).trim().replace(',', '.')); return String(txt).trim() === '' ? NaN : v; };
const fmtQ = (v) => String(Math.round(v * 1000) / 1000).replace('.', ',');

const dataCa = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString(loc());

function quotaPill(q) {
  if (!q) return null;
  if (q.al_dia) return h('span', { class: 'pill ok' }, 'quota fins al ' + dataCa(q.valid_fins));
  return h('span', { class: 'pill warn' }, q.valid_fins ? 'quota caducada el ' + dataCa(q.valid_fins) : 'sense quota');
}

// Cobrament de la quota del soci (entra a la caixa oberta). Els imports i els mesos per defecte venen de la configuració del local.
function quotaForm(m, out, onDone) {
  const loc = S.me.locals.find((l) => l.id === S.local) || {};
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00', value: loc.quota_cent ? (loc.quota_cent / 100).toFixed(2).replace('.', ',') : '' });
  const mesos = h('input', { type: 'number', min: 1, max: 24, value: loc.quota_mesos || 1 });
  const met = h('select', null, ['efectiu', 'targeta', 'bizum'].map((x) => h('option', { value: x }, x)));
  const nota = isManager() ? h('input', { maxlength: 200, placeholder: "Només si l'import no és la tarifa del local" }) : null;
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cobrar quota');
  const res = h('div');
  const ref = novaRef();   // un cobrament de quota = una referència: un doble clic no cobra dos períodes
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, res, async () => {
      const r = await api(`/socis/${m.id}/quotes`, { method: 'POST', body: { client_ref: ref, import_cent: parseEur(imp.value), metode: met.value, mesos: Number(mesos.value), ...(nota && nota.value.trim() ? { nota: nota.value.trim() } : {}) } });
      m.quota = { al_dia: true, valid_fins: r.valid_fins };
      toast('Quota cobrada: vàlida fins al ' + dataCa(r.valid_fins));
      onDone(m);
    });
  } }, h('h3', null, 'Quota'),
  h('div', { class: 'row' }, field('Import (€)', imp), field('Mesos', mesos), field('Mètode', met)), nota ? field('Nota (opcional)', nota) : null,
  h('div', { class: 'actions' }, btn), res);
}

// Monedero del soci: saldo, recàrrega (entra a la caixa oberta) i darrers moviments. Només si el local el té activat.
function walletPanel(m) {
  const lc = S.me.locals.find((l) => l.id === S.local) || {};
  if (!lc.moneder_actiu) return null;
  const box = h('div', { class: 'card' });
  const out = h('div');
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Import a recarregar' });
  const met = h('select', { 'aria-label': 'Mètode de pagament' }, ['efectiu', 'targeta', 'bizum'].map((x) => h('option', { value: x }, x)));
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Recarregar');
  const ref = { v: novaRef() };   // una recàrrega = una referència; es renova quan s'ha fet
  const pinta = async () => {
    const w = await api(`/socis/${m.id}/moneder`);
    m.saldo_cent = w.saldo_cent;
    const tipus = { recarrega: 'Recàrrega', pagament: 'Pagament', correccio: 'Correcció' };
    box.replaceChildren(h('h3', null, 'Monedero'),
      h('div', { class: 'big' }, eur(w.saldo_cent)),
      h('form', { onsubmit: (e) => {
        e.preventDefault();
        guard(btn, out, async () => {
          await api(`/socis/${m.id}/moneder/recarrega`, { method: 'POST', body: { client_ref: ref.v, import_cent: parseEur(imp.value), metode: met.value } });
          ref.v = novaRef();
          imp.value = '';
          toast('Monedero recarregat');
          await pinta();
        });
      } }, h('div', { class: 'row' }, field('Import (€)', imp), field('Mètode', met)), h('div', { class: 'actions' }, btn)),
      out,
      ...(w.historial.length ? [h('table', null, h('tbody', null, w.historial.slice(0, 5).map((x) => h('tr', null,
        h('td', null, new Date(x.ts).toLocaleString(loc())), h('td', null, tipus[x.tipus] || x.tipus), h('td', { class: 'num' }, eur(x.import_cent))))))] : []));
  };
  pinta().catch((e) => box.replaceChildren(msg('err', e.message)));
  return box;
}
function memberCard(m, out, onChange) {
  const pill = h('span', { class: 'pill ' + (m.estat === 'actiu' ? 'ok' : 'bad') }, m.estat);
  const card = h('div', { class: 'card' }, h('div', { class: 'member' }, memberPhoto(m), h('div', null,
    h('div', { class: 'big' }, m.nom), h('div', null, pill, ' ', quotaPill(m.quota), m.te_carnet ? h('span', { class: 'pill' }, 'carnet') : null,
      // El dispensador rep una fitxa reduïda (sense document, naixement ni telèfon): només es mostra el que arriba.
      m.document ? h('span', { class: 'muted' }, ' ' + m.document + (m.naixement ? ' · ' + m.naixement : '')) : null),
    m.telefon ? h('div', { class: 'muted' }, m.telefon) : null)));
  const bar = h('div', { class: 'actions' });
  const tools = (isManager() || S.me.pot_reemborsar) && onChange ? memberTools(m, out, onChange) : null;
  const entrada = h('button', { onclick: () => guard(entrada, out, async () => {
    await api(`/socis/${m.id}/entrada`, { method: 'POST' });
    out.replaceChildren(msg('ok', 'Entrada registrada'));
  }) }, 'Registrar entrada');
  bar.append(entrada);
  if (isManager()) {
    const sel = h('select', { 'aria-label': 'Nou estat' }, ['actiu', 'suspes', 'baixa'].map((e) => h('option', { value: e, selected: e === m.estat }, e)));
    const set = h('button', { onclick: () => guard(set, out, async () => {
      await api(`/socis/${m.id}/estat`, { method: 'POST', body: { estat: sel.value } });
      m.estat = sel.value;
      toast('Estat actualitzat');
      if (onChange) onChange(m);
    }) }, 'Canviar estat');
    bar.append(sel, set);
  }
  if (tools) bar.append(...tools.bar);
  card.append(bar);
  if (tools) card.append(tools.panel);
  return card;
}

// Cerca per document o per carnet. El lector de carnets «escriu» el codi i prem Intro: això envia el formulari.
function searchBox(onFound) {
  const out = h('div');
  const doc = h('input', { placeholder: 'DNI / NIE / passaport', autocapitalize: 'characters', autocomplete: 'off' });
  const carnet = h('input', { placeholder: 'Carnet', 'aria-label': 'Carnet', autocapitalize: 'characters', autocomplete: 'off' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cercar');
  let torn = 0;   // número de la cerca en curs: una resposta d'una cerca anterior es descarta
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    // El carnet acabat de passar mana sobre un document que hagi quedat escrit (si no, es buscaria el soci anterior).
    const q = triaCerca(doc.value, carnet.value);
    if (!q.per) { carnet.focus(); return; }
    const meva = ++torn;
    guard(btn, out, async () => {
      try {
        const m = q.per === 'carnet'
          ? await api(`/locals/${S.local}/socis/carnet`, { method: 'POST', body: { codi: normalizeScan(q.valor, await readerProfile()) } })
          : await api(`/locals/${S.local}/socis/cerca`, { method: 'POST', body: { document: q.valor } });
        if (meva !== torn) return;   // ha arribat tard: ja s'ha fet una altra cerca
        doc.value = '';   // trobat: el document no ha de quedar escrit per a la cerca següent
        await onFound(m, out);
      } finally {
        // El carnet sempre queda buit i amb el focus: la lectura següent no es barreja amb l'anterior.
        // (Si la cerca per document ha fallat, el document es conserva perquè es pugui corregir.)
        if (meva === torn) { carnet.value = ''; carnet.focus(); }
      }
    });
  } }, h('h3', null, h('span', { class: 'pas-num' }, '1'), ' Soci'), h('div', { class: 'row' }, field('Passa el carnet pel lector', carnet), field('o escriu el document', doc)), h('div', { class: 'actions' }, btn), out);
  if (window.matchMedia && window.matchMedia('(pointer: fine)').matches) setTimeout(() => { if (document.body.contains(carnet)) carnet.focus(); }, 0);
  return form;
}

// Ficha del soci + cobrament de quota, dins d'un contenidor propi (es refà quan canvia alguna dada).
function memberPanel() {
  const found = h('div');
  const show1 = (m, out) => found.replaceChildren(memberCard(m, out, (mm) => show1(mm, out)), quotaForm(m, out, (mm) => show1(mm, out)));
  return { found, show: show1 };
}

VIEWS.socis = async () => {
  const items = [['cercar', 'Cercar', async () => {
    const panel = memberPanel();
    return h('div', null, searchBox(panel.show), panel.found);
  }]];
  if (isManager()) {
    items.push(['llista', 'Llista', async () => {
      const panel = memberPanel();
      return h('div', null, memberList((m, out) => { panel.show(m, out); panel.found.scrollIntoView(); }), panel.found);
    }]);
    items.push(['alta', 'Alta de soci', async () => altaWizard()]);
  }
  return h('div', null, pageHead('Socis', 'Cerca un soci, consulta la llista o registra un soci nou.'), sections('socis', items));
};

function altaForm() {
  const out = h('div');
  const f = { nom: h('input', { autocomplete: 'off' }), doc: h('input', { autocapitalize: 'characters', autocomplete: 'off' }),
    naix: h('input', { type: 'date' }), tel: h('input', { inputmode: 'tel' }), mail: h('input', { type: 'email' }) };
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Donar d\'alta');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api('/socis', { method: 'POST', body: { local_id: S.local, nom: f.nom.value.trim(), document: f.doc.value.trim(),
        naixement: f.naix.value, telefon: f.tel.value.trim() || null, email: f.mail.value.trim() || null } });
      Object.values(f).forEach((i) => { i.value = ''; });
      out.replaceChildren(msg('ok', 'Soci creat (núm. ' + r.id + '). Falta la signatura:'), signaturePad(r.id, out));
    });
  } },
  h('h3', null, 'Dades del soci'),
  h('div', { class: 'row' }, field('Nom i cognoms', f.nom), field('Document', f.doc), field('Data de naixement', f.naix)),
  h('div', { class: 'row' }, field('Telèfon (opcional)', f.tel), field('Correu (opcional)', f.mail)),
  h('div', { class: 'actions' }, btn), out);
}

VIEWS.dispensar = async () => {
  const caixa = await api(`/locals/${S.local}/caixa`);
  const box = h('div', null, pageHead('Dispensar', 'Identifica el soci, tria el producte i la quantitat, i cobra-ho.'));
  if (!caixa.oberta) {
    box.append(msg('err', 'No hi ha cap caixa oberta en aquest local. Un encarregat l\'ha d\'obrir abans de dispensar.'));
    return box;
  }
  const step = h('div');
  const loc = S.me.locals.find((l) => l.id === S.local) || {};
  // Si el local exigeix la quota al dia, es cobra aquí mateix abans de poder dispensar.
  let tornSoci = 0;
  const showMember = async (m, out) => {
    const meu = ++tornSoci;
    // Els preus són els del soci: la seva línia de preu, si en té
    const productes = m.estat === 'actiu' ? await api(`/locals/${S.local}/estoc?soci=${m.id}`) : [];
    await carregaMetaCat();
    if (meu !== tornSoci) return;   // mentre es carregaven els preus s'ha obert un altre soci
    const bloquejat = loc.quota_obligatoria && !(m.quota && m.quota.al_dia);
    if (loc.moneder_actiu && m.estat !== 'baixa') { try { m.saldo_cent = (await api(`/socis/${m.id}/moneder`)).saldo_cent; } catch (_) { /* sense saldo */ } }
    if (meu !== tornSoci) return;
    search.hidden = true;   // trobat: la cerca es torna a mostrar amb «Canviar de soci»
    const canvia = h('button', { type: 'button', class: 'small' }, 'Canviar de soci');
    canvia.addEventListener('click', () => show('dispensar'));
    const barra = h('div', { class: 'card dis-soci' }, memberPhoto(m), h('div', { class: 'dis-soci-dades' }, h('div', { class: 'big' }, m.nom),
      h('div', null, h('span', { class: 'pill ' + (m.estat === 'actiu' ? 'ok' : 'bad') }, m.estat), ' ', quotaPill(m.quota),
        loc.moneder_actiu && m.saldo_cent != null ? h('span', { class: 'pill' }, 'Monedero ' + eur(m.saldo_cent)) : null)), canvia);
    step.replaceChildren(...[
      barra,
      alertesSoci(m.alertes),
      m.estat !== 'actiu' ? msg('err', 'El soci no està actiu: no es pot dispensar.') : null,
      m.estat === 'actiu' && bloquejat ? msg('err', 'La quota del soci no està al dia: cal cobrar-la abans de dispensar.') : null,
      m.estat !== 'baixa' && bloquejat ? quotaForm(m, out, (mm) => showMember(mm, out)) : null,
      m.estat === 'actiu' && !bloquejat ? productStep(m, productes) : null,
      h('details', { class: 'card dis-eines' }, h('summary', null, 'Fitxa i eines del soci (monedero, observacions, devolucions)'),
        memberCard(m, out, (mm) => showMember(mm, out)), m.estat !== 'baixa' ? walletPanel(m) : null,
        observacioForm(m, () => showMember(m, out))),
    ].filter(Boolean));
  };
  const search = searchBox(showMember);

  // Producte → quantitat → cobrament, tot visible a la mateixa pantalla: botons grans, quantitats ràpides, total en directe i els
  // mètodes de cobrament sempre a la vista (s'activen quan hi ha producte i una quantitat vàlida).
  function productStep(m, productes) {
    let chosen = null;
    const out = h('div');
    const ref = novaRef();   // una dispensació = una referència: repetir l'enviament no dispensa dues vegades
    const decimals = loc.decimals_dispensacio ?? 3;
    const sense = () => h('option', { value: '' }, 'Sense descompte');
    const descSel = h('select', { 'aria-label': 'Descompte' }, sense());
    const descField = field('Descompte', descSel);
    descField.hidden = true;   // només surt si el producte triat té algun descompte vigent
    const totalEl = h('div', { class: 'dis-total' }, eur(0));
    const totalNota = h('div', { class: 'muted' });
    const avis = h('div', { role: 'status' });
    const unitat = () => (chosen ? unitTxt(chosen) : 'g');
    const estoc = () => (chosen ? numG(chosen.estoc_g) : 0);

    const g = h('input', { class: 'dis-q', inputmode: 'decimal', placeholder: '0', 'aria-label': 'Quantitat', autocomplete: 'off' });
    const pes = h('input', { inputmode: 'decimal', placeholder: 'Pes de la bàscula (opcional)', 'aria-label': 'Pes de la bàscula' });
    const qty = () => numG(g.value);

    // Descomptes vigents que es poden aplicar al producte triat (cada un amb el seu import o percentatge).
    const carregaDescomptes = async (p) => {
      const l = await api(`/locals/${S.local}/descomptes?producte=${p.id}`);
      if (chosen !== p) return;   // resposta d'un producte que ja no és el triat
      descSel.replaceChildren(sense(), ...l.map((d) => h('option', { value: d.id }, `${d.nom} (${d.tipus === 'percent' ? d.valor + ' %' : eur(d.valor) + '/g'})`)));
      descField.hidden = !l.length;
      refresca();
    };
    // Lots amb existències del producte triat. Sense lots, el camp s'amaga i la dispensació surt pel FIFO com sempre.
    const lotSel = h('select', { 'aria-label': 'Lot' });
    const lotField = field('Lot', lotSel);
    lotField.hidden = true;
    const carregaLots = async (p) => {
      lotSel.replaceChildren();
      lotField.hidden = true;
      const l = await api(`/productes/${p.id}/lots-dispensables`);
      if (chosen !== p || !l.length) return;
      lotSel.replaceChildren(h('option', { value: '' }, 'Automàtic (lot més antic)'),
        ...l.map((b) => h('option', { value: b.id }, `${b.codi} · ${mgToG(b.existencies_mg)} g`)));
      lotField.hidden = false;
    };

    // ---- Botons de cobrament (sempre visibles) ----
    const btnEfectiu = h('button', { class: 'pagar efectiu', type: 'button' }, 'Efectiu');
    const btnTargeta = h('button', { class: 'pagar targeta', type: 'button' }, 'Targeta');
    const btnBizum = h('button', { class: 'pagar bizum', type: 'button' }, 'Bizum');
    const btnMoneder = h('button', { class: 'pagar moneder', type: 'button' }, 'Monedero');
    btnMoneder.hidden = !loc.moneder_actiu;
    const btnRegal = h('button', { type: 'button' }, 'Dispensar com a regal');
    const btnApart = h('button', { type: 'submit' }, 'Dispensar i cobrar després');
    btnRegal.hidden = true;   // només per als productes marcats com a regalables
    const pagaments = [btnEfectiu, btnTargeta, btnBizum, btnMoneder];

    // Estat dels botons i total en directe.
    const refresca = () => {
      const q = qty();
      const valida = !!chosen && Number.isFinite(q) && q > 0 && q <= estoc() + 1e-9;
      const total = chosen && Number.isFinite(q) && q > 0 ? Math.round(q * chosen.preu_cent_per_g) : 0;
      totalEl.textContent = eur(total);
      totalNota.textContent = chosen && total > 0 && (descSel.value || m.descompte_pct > 0) ? 'Els descomptes s\'apliquen en cobrar.' : '';
      avis.replaceChildren(...[
        !chosen ? msg('info', 'Tria un producte per començar.') : null,
        chosen && Number.isFinite(q) && q > estoc() + 1e-9 ? msg('err', `No hi ha prou estoc: en queden ${chosen.estoc_g} ${unitat()}.`) : null,
        chosen && Number.isFinite(q) && q > 0 && decimals < 3 && unitat() === 'g' && chosen.granel !== false && Math.abs(q * 10 ** decimals - Math.round(q * 10 ** decimals)) > 1e-9
          ? msg('err', `Aquest club només admet ${decimals} decimal${decimals === 1 ? '' : 's'} en els grams.`) : null,
      ].filter(Boolean));
      [...pagaments, btnRegal, btnApart].forEach((b) => { b.disabled = !valida; });
      if (m.saldo_cent != null && loc.moneder_actiu) btnMoneder.textContent = 'Monedero · ' + eur(m.saldo_cent);
    };

    // ---- Quantitat: botons ràpids i ajust fi ----
    const rapids = h('div', { class: 'dis-rapids', role: 'group', 'aria-label': 'Quantitats ràpides' });
    const pintaRapids = () => {
      const valors = (chosen && chosen.unitat === 'u' ? [1, 2, 3, 5] : [0.5, 1, 2, 3.5, 5, 10]).filter((v) => decimals >= 1 || Number.isInteger(v) || (chosen && chosen.unitat === 'u'));
      rapids.replaceChildren(...valors.map((v) => {
        const b = h('button', { type: 'button', class: 'rapid' }, fmtQ(v) + ' ' + unitat());
        b.addEventListener('click', () => { g.value = fmtQ(v); refresca(); });
        return b;
      }));
    };
    const pas = () => (chosen && chosen.unitat === 'u') || decimals === 0 ? 1 : 0.5;
    const ajusta = (signe) => {
      const base = Number.isFinite(qty()) ? qty() : 0;
      g.value = fmtQ(Math.max(0, Math.round((base + signe * pas()) * 1000) / 1000));
      refresca();
    };
    const menys = h('button', { type: 'button', class: 'dis-pas', 'aria-label': 'Menys' }, '−');
    const mes = h('button', { type: 'button', class: 'dis-pas', 'aria-label': 'Més' }, '+');
    menys.addEventListener('click', () => ajusta(-1));
    mes.addEventListener('click', () => ajusta(1));
    g.addEventListener('input', refresca);
    const unitEtiqueta = h('span', { class: 'dis-unit' }, 'g');

    // ---- Llista de productes (taules grans, amb filtre quan n'hi ha molts) ----
    let filtreText = '', filtreCat = '';
    const list = h('div', { class: 'products' });
    const triar = (p) => {
      chosen = p;
      btnRegal.hidden = !p.regalable;
      unitEtiqueta.textContent = unitTxt(p);
      g.value = '';
      descSel.replaceChildren(sense());   // el descompte del producte anterior no val per a aquest
      descField.hidden = true;
      carregaDescomptes(p).catch(() => { if (chosen === p) descSel.replaceChildren(sense()); });
      carregaLots(p).catch(() => { lotSel.replaceChildren(); lotField.hidden = true; });
      pintaRapids();
      pintaLlista();
      refresca();
      g.focus();
    };
    const pintaLlista = () => {
      const t = filtreText.trim().toLowerCase();
      const visibles = productes.filter((p) => (!t || p.nom.toLowerCase().includes(t)) && (!filtreCat || p.categoria === filtreCat));
      list.replaceChildren(...(visibles.length ? visibles.map((p) => {
        const sensEstoc = !(numG(p.estoc_g) > 0);
        const b = h('button', { type: 'button', class: 'prod' + (sensEstoc ? ' sense-estoc' : ''), 'aria-pressed': String(chosen === p), disabled: sensEstoc },
          productThumb(p, 44), h('strong', null, catBadge(p.categoria), ' ', p.nom),
          h('span', { class: 'prod-preu' }, eur(p.preu_cent_per_g) + '/' + unitTxt(p)),
          h('span', { class: 'muted' }, sensEstoc ? 'Sense estoc' : p.estoc_g + ' ' + unitTxt(p) + ' en estoc'));
        b.addEventListener('click', () => triar(p));
        return b;
      }) : [h('p', { class: 'muted' }, 'Cap producte amb aquest filtre.')]));
    };
    const categories = [...new Set(productes.map((p) => p.categoria).filter(Boolean))];
    const filtre = productes.length > 6 ? h('div', { class: 'dis-filtre' },
      (() => { const i = h('input', { type: 'search', placeholder: 'Cercar producte…', 'aria-label': 'Cercar producte', autocomplete: 'off' }); i.addEventListener('input', () => { filtreText = i.value; pintaLlista(); }); return i; })(),
      categories.length > 1 ? h('div', { class: 'dis-cats' }, ['', ...categories].map((c) => {
        const b = h('button', { type: 'button', class: 'small', 'aria-pressed': String(c === '') }, c || 'Tots');
        b.addEventListener('click', () => { filtreCat = c; [...b.parentNode.children].forEach((x) => x.setAttribute('aria-pressed', String(x === b))); pintaLlista(); });
        return b;
      })) : null) : null;
    pintaLlista();

    const scale = scalePanel(g, pes);
    // La bàscula, el descompte, el lot i les accions poc habituals queden plegats: el camí normal és triar, quantitat i cobrar.
    const mesOpcions = h('details', { class: 'dis-mes' }, h('summary', null, 'Més opcions (bàscula, descompte, lot, regal)'),
      scale, h('div', { class: 'row' }, field('Pes de la bàscula (g)', pes), descField, lotField),
      h('div', { class: 'actions' }, btnRegal, btnApart));
    if (Bascula.supported() && BASCULA && BASCULA.connected) mesOpcions.open = true;

    // Amb mètode, la dispensació i el cobrament es fan en una sola operació al servidor (o es fa tot o res).
    // Els botons fan la mateixa dispensació: es bloquegen junts (un Intro o un segon clic no la repeteix).
    const envia = (btn, metode) => guardTots([btnEfectiu, btnTargeta, btnBizum, btnMoneder, btnRegal, btnApart], out, async () => {
      if (!chosen) throw new Error('Tria un producte');
      const body = { client_ref: ref, member_id: m.id, product_id: chosen.id,
        grams: parseGrams(g.value), pes_bascula_g: pes.value.trim() ? parseGrams(pes.value) : null,
        discount_id: descSel.value ? Number(descSel.value) : null };
      if (lotSel.value) body.batch_id = Number(lotSel.value);
      if (metode === 'regal') { body.regal = true; body.discount_id = null; } else if (metode) body.metode = metode;
      const r = await api('/dispensacions', { method: 'POST', body });
      if (r.regal) {
        step.replaceChildren(resultatDispensacio(m, chosen, parseGrams(g.value), null, 'regal'));
      } else if (r.cobrat) {
        step.replaceChildren(resultatDispensacio(m, chosen, parseGrams(g.value), r, metode));
      } else {
        step.replaceChildren(chargeStep(m, r));
      }
    });
    btnEfectiu.onclick = () => envia(btnEfectiu, 'efectiu');
    btnTargeta.onclick = () => envia(btnTargeta, 'targeta');
    btnBizum.onclick = () => envia(btnBizum, 'bizum');
    btnMoneder.onclick = () => envia(btnMoneder, 'monedero');
    btnRegal.onclick = () => envia(btnRegal, 'regal');

    refresca();
    return h('form', { class: 'dispensa', onsubmit: (e) => { e.preventDefault(); if (!btnApart.disabled) envia(btnApart, null); } },
      h('section', { class: 'card dis-pas1' }, h('h3', null, h('span', { class: 'pas-num' }, '2'), ' Producte'), filtre, list),
      h('section', { class: 'card dis-pas2' }, h('h3', null, h('span', { class: 'pas-num' }, '3'), ' Quantitat'),
        h('div', { class: 'dis-qrow' }, menys, h('div', { class: 'dis-qbox' }, g, unitEtiqueta), mes), rapids),
      mesOpcions,
      h('section', { class: 'card dis-cobra', 'aria-label': 'Cobrament' }, avis,
        h('div', { class: 'dis-cobra-fila' },
          h('div', { class: 'dis-totalbox' }, h('span', { class: 'pas-num' }, '4'), h('span', { class: 'muted' }, 'Total'), totalEl, totalNota),
          h('div', { class: 'dis-pagaments' }, ...pagaments)), out));
  }

  // Pantalla de final: confirma què s'ha fet i deixa a un clic la dispensació següent.
  function resultatDispensacio(m, p, quantitat, r, metode) {
    const nova = h('button', { class: 'primary gran', type: 'button' }, 'Nova dispensació');
    nova.addEventListener('click', () => show('dispensar'));
    const etiqueta = { efectiu: 'efectiu', targeta: 'targeta', bizum: 'Bizum', monedero: 'monedero', regal: 'regal' }[metode] || metode;
    return h('div', { class: 'card dis-fet', role: 'status' }, h('div', { class: 'dis-check', 'aria-hidden': 'true' }, '✓'),
      h('h2', null, r ? `Cobrat ${eur(r.import_cent)}` : 'Regal dispensat'),
      h('p', null, `${fmtQ(quantitat)} ${unitTxt(p)} de ${p.nom} a ${m.nom} · ${etiqueta}`),
      r && r.descompte_cent > 0 ? h('p', { class: 'muted' }, 'Descompte aplicat: -' + eur(r.descompte_cent)) : null,
      h('div', { class: 'actions' }, nova));
  }

  function chargeStep(m, r) {
    const out = h('div');
    const pay = (metode) => {
      const b = { efectiu: cash, targeta: card, bizum: bizum, monedero: moneder }[metode];
      return guard(b, out, async () => {
        await api('/cobraments', { method: 'POST', body: { movement_id: r.id, metode } });
        step.replaceChildren(msg('ok', `Cobrat ${eur(r.import_cent)} (${metode}) a ${m.nom}`),
          h('div', { class: 'actions' }, h('button', { class: 'primary', onclick: () => show('dispensar') }, 'Nova dispensació')));
      });
    };
    const cash = h('button', { class: 'primary', onclick: () => pay('efectiu') }, 'Cobrar en efectiu');
    const card = h('button', { onclick: () => pay('targeta') }, 'Cobrar amb targeta');
    const bizum = h('button', { onclick: () => pay('bizum') }, 'Cobrar amb Bizum');
    const moneder = h('button', { onclick: () => pay('monedero') }, 'Cobrar amb el monedero');
    moneder.hidden = !loc.moneder_actiu;
    return h('div', { class: 'card' }, h('h2', null, 'Dispensació registrada'),
      h('div', { class: 'big' }, eur(r.import_cent)), r.descompte_cent > 0 ? h('p', { class: 'muted' }, 'Descompte aplicat: -' + eur(r.descompte_cent)) : null, h('p', { class: 'muted' }, 'Falta cobrar-la.'),
      h('div', { class: 'actions' }, cash, card, bizum, moneder), out);
  }

  box.append(search, step);
  return box;
};


// Signatura de l'alta amb el perfil de la tauleta del local (mida, traç, traços mínims).
function signaturePad(memberId, out, onDone, textSha256) {
  const holder = h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Preparant la tauleta de signatura…'));
  defaultProfile('signatura').then((cfg) => {
    const res = h('div');
    const pad = signatureCanvas(Object.assign({}, DEFAULTS.signatura, cfg || {}), (s) => guard(pad.saveButton, res, async () => {
      if (!s.valid) throw new Error(`El soci ha de signar abans de desar (calen almenys ${s.min} traços).`);
      await api(`/socis/${memberId}/signatura`, { method: 'POST', body: { png_base64: s.png, ...(textSha256 ? { text_sha256: textSha256 } : {}) } });
      if (onDone) { await onDone(); return; }
      out.replaceChildren(msg('ok', "Soci donat d'alta i signatura desada (núm. " + memberId + ')'));
    }), 'Desar signatura');
    holder.replaceChildren(h('p', { class: 'muted' }, 'Signa dins del quadre:'), pad, res);
  });
  return holder;
}


// Bàscula OHAUS: es connecta un cop (el navegador demana permís) i es manté entre dispensacions.
let BASCULA = null;
const mgToG = (mg) => String(mg / 1000).replace('.', ',');

function scalePanel(gInput, pesInput) {
  if (!Bascula.supported()) {
    return h('p', { class: 'muted' }, 'Bàscula: aquest navegador o connexió no admet ports sèrie (cal Chrome o Edge i HTTPS o localhost). Pots escriure el pes a mà.');
  }
  const out = h('div');
  const state = h('span', { class: 'pill' });
  const paint = () => {
    const ok = BASCULA && BASCULA.connected;
    state.textContent = ok ? 'bàscula connectada' : 'bàscula desconnectada';
    state.className = 'pill ' + (ok ? 'ok' : 'warn');
  };
  paint();
  const connect = h('button', { type: 'button' }, 'Connectar bàscula');
  connect.addEventListener('click', () => guard(connect, out, async () => {
    if (BASCULA && BASCULA.connected) await BASCULA.disconnect();
    const cfg = await defaultProfile('bascula');
    BASCULA = new Bascula(cfg ? profileToOptions(cfg) : loadProfile());
    await BASCULA.connect();
    paint();
  }));
  const weigh = h('button', { class: 'primary', type: 'button' }, 'Pesar');
  weigh.addEventListener('click', () => guard(weigh, out, async () => {
    if (!BASCULA || !BASCULA.connected) throw new Error('Connecta primer la bàscula');
    const r = await BASCULA.readStable();
    if (r.mg <= 0) throw new Error('La bàscula marca ' + r.raw + ': posa el producte al plat');
    pesInput.value = mgToG(r.mg);
    gInput.value = mgToG(r.mg);
    out.replaceChildren(msg('ok', 'Pes estable: ' + r.raw));
  }));
  const tare = h('button', { type: 'button' }, 'Tara');
  tare.addEventListener('click', () => guard(tare, out, async () => {
    if (!BASCULA || !BASCULA.connected) throw new Error('Connecta primer la bàscula');
    await BASCULA.tare();
    toast('Tara enviada');
  }));
  return h('div', { class: 'card' }, h('div', null, state), h('div', { class: 'actions' }, connect, weigh, tare), out);
}
