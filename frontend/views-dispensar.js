'use strict';
// Pantalles: Dispensar (flux complet) i Socis (cerca, alta, estat).

const dataCa = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('ca-ES');

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
  const met = h('select', null, ['efectiu', 'targeta'].map((x) => h('option', { value: x }, x)));
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cobrar quota');
  const res = h('div');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, res, async () => {
      const r = await api(`/socis/${m.id}/quotes`, { method: 'POST', body: { import_cent: parseEur(imp.value), metode: met.value, mesos: Number(mesos.value) } });
      m.quota = { al_dia: true, valid_fins: r.valid_fins };
      toast('Quota cobrada: vàlida fins al ' + dataCa(r.valid_fins));
      onDone(m);
    });
  } }, h('h3', null, 'Quota'),
  h('div', { class: 'row' }, field('Import (€)', imp), field('Mesos', mesos), field('Mètode', met)),
  h('div', { class: 'actions' }, btn), res);
}

function memberCard(m, out, onChange) {
  const pill = h('span', { class: 'pill ' + (m.estat === 'actiu' ? 'ok' : 'bad') }, m.estat);
  const card = h('div', { class: 'card' }, h('div', { class: 'member' }, memberPhoto(m), h('div', null,
    h('div', { class: 'big' }, m.nom), h('div', null, pill, ' ', quotaPill(m.quota), m.te_carnet ? h('span', { class: 'pill' }, 'carnet') : null,
      ' ', h('span', { class: 'muted' }, m.document + ' · ' + m.naixement)),
    m.telefon ? h('div', { class: 'muted' }, m.telefon) : null)));
  const bar = h('div', { class: 'actions' });
  const tools = isManager() && onChange ? memberTools(m, out, onChange) : null;
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
  const carnet = h('input', { placeholder: 'Passa el carnet pel lector', autocapitalize: 'characters', autocomplete: 'off' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cercar');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    const perCarnet = !doc.value.trim() && carnet.value.trim();
    guard(btn, out, async () => {
      const m = perCarnet
        ? await api(`/locals/${S.local}/socis/carnet?codi=${encodeURIComponent(carnet.value.trim())}`)
        : await api(`/locals/${S.local}/socis/cerca?document=${encodeURIComponent(doc.value.trim())}`);
      carnet.value = '';
      onFound(m, out);
    });
  } }, h('div', { class: 'row' }, field('Document del soci', doc), field('o carnet', carnet)), h('div', { class: 'actions' }, btn), out);
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
    items.push(['alta', 'Alta de soci', async () => altaForm()]);
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
  const box = h('div', null, h('h2', null, 'Dispensar'));
  if (!caixa.oberta) {
    box.append(msg('err', 'No hi ha cap caixa oberta en aquest local. Un encarregat l\'ha d\'obrir abans de dispensar.'));
    return box;
  }
  const step = h('div');
  const productes = await api(`/locals/${S.local}/estoc`);
  const loc = S.me.locals.find((l) => l.id === S.local) || {};
  // Si el local exigeix la quota al dia, es cobra aquí mateix abans de poder dispensar.
  const showMember = (m, out) => {
    const bloquejat = loc.quota_obligatoria && !(m.quota && m.quota.al_dia);
    step.replaceChildren(...[
      memberCard(m, out, (mm) => showMember(mm, out)),
      m.estat !== 'actiu' ? msg('err', 'El soci no està actiu: no es pot dispensar.') : null,
      m.estat === 'actiu' && bloquejat ? msg('err', 'La quota del soci no està al dia: cal cobrar-la abans de dispensar.') : null,
      m.estat !== 'baixa' && bloquejat ? quotaForm(m, out, (mm) => showMember(mm, out)) : null,
      m.estat === 'actiu' && !bloquejat ? productStep(m) : null,
    ].filter(Boolean));
  };
  const search = searchBox(showMember);

  function productStep(m) {
    let chosen = null;
    const out = h('div');
    const list = h('div', { class: 'products' }, productes.map((p) => {
      const b = h('button', { 'aria-pressed': 'false', onclick: () => {
        chosen = p; list.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      } }, h('strong', null, p.nom), h('span', { class: 'muted' }, p.estoc_g + ' g · ' + eur(p.preu_cent_per_g) + '/g'));
      return b;
    }));
    const g = h('input', { inputmode: 'decimal', placeholder: '0,000' });
    const pes = h('input', { inputmode: 'decimal', placeholder: 'Pes de la bàscula (opcional)' });
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Dispensar');
    const scale = scalePanel(g, pes);
    return h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        if (!chosen) throw new Error('Tria un producte');
        const r = await api('/dispensacions', { method: 'POST', body: { member_id: m.id, product_id: chosen.id,
          grams: parseGrams(g.value), pes_bascula_g: pes.value.trim() ? parseGrams(pes.value) : null } });
        step.replaceChildren(chargeStep(m, r));
      });
    } }, h('h3', null, 'Producte'), list,
    scale,
    h('div', { class: 'row' }, field('Quantitat (g)', g), field('Bàscula (g)', pes)),
    h('div', { class: 'actions' }, btn), out);
  }

  function chargeStep(m, r) {
    const out = h('div');
    const pay = (metode) => {
      const b = metode === 'efectiu' ? cash : card;
      return guard(b, out, async () => {
        await api('/cobraments', { method: 'POST', body: { movement_id: r.id, metode } });
        step.replaceChildren(msg('ok', `Cobrat ${eur(r.import_cent)} (${metode}) a ${m.nom}`),
          h('div', { class: 'actions' }, h('button', { class: 'primary', onclick: () => show('dispensar') }, 'Nova dispensació')));
      });
    };
    const cash = h('button', { class: 'primary', onclick: () => pay('efectiu') }, 'Cobrar en efectiu');
    const card = h('button', { onclick: () => pay('targeta') }, 'Cobrar amb targeta');
    return h('div', { class: 'card' }, h('h2', null, 'Dispensació registrada'),
      h('div', { class: 'big' }, eur(r.import_cent)), h('p', { class: 'muted' }, 'Falta cobrar-la.'),
      h('div', { class: 'actions' }, cash, card), out);
  }

  box.append(search, step);
  return box;
};


// Llenç de signatura (ratolí, tàctil o llapis). Només s'envia si s'ha dibuixat alguna cosa.
function signaturePad(memberId, out) {
  const canvas = h('canvas', { class: 'sig', width: 600, height: 220, 'aria-label': 'Espai per signar' });
  const ctx2 = canvas.getContext('2d');
  ctx2.lineWidth = 3; ctx2.lineCap = 'round'; ctx2.lineJoin = 'round'; ctx2.strokeStyle = '#000';
  let drawing = false, dirty = false;
  const pos = (e) => {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height];
  };
  const white = () => { ctx2.fillStyle = '#fff'; ctx2.fillRect(0, 0, canvas.width, canvas.height); };
  white();
  canvas.addEventListener('pointerdown', (e) => { drawing = true; try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* no passa res: seguim dibuixant */ } const [x, y] = pos(e); ctx2.beginPath(); ctx2.moveTo(x, y); });
  canvas.addEventListener('pointermove', (e) => { if (!drawing) return; const [x, y] = pos(e); ctx2.lineTo(x, y); ctx2.stroke(); dirty = true; });
  const stop = () => { drawing = false; };
  canvas.addEventListener('pointerup', stop); canvas.addEventListener('pointercancel', stop);
  const clear = h('button', { type: 'button', onclick: () => { white(); dirty = false; } }, 'Esborrar');
  const save = h('button', { class: 'primary', type: 'button' }, 'Desar signatura');
  const res = h('div');
  save.addEventListener('click', () => guard(save, res, async () => {
    if (!dirty) throw new Error('El soci ha de signar abans de desar');
    const b64 = canvas.toDataURL('image/png').split(',')[1];
    await api(`/socis/${memberId}/signatura`, { method: 'POST', body: { png_base64: b64 } });
    out.replaceChildren(msg('ok', 'Soci donat d\'alta i signatura desada (núm. ' + memberId + ')'));
  }));
  return h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Signa dins del quadre:'), canvas, h('div', { class: 'actions' }, save, clear), res);
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
    BASCULA = new Bascula(loadProfile());
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
