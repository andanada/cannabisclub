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

// Donacions del soci: saldo, crèdit afegit (entra a la caixa de recepció) i darrers moviments. Cada soci ha de tenir saldo per dispensar.
function walletPanel(m) {
  const box = h('div', { class: 'card' });
  const out = h('div');
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Import de la donació' });
  const met = h('select', { 'aria-label': 'Mètode de pagament' }, ['efectiu', 'targeta', 'bizum'].map((x) => h('option', { value: x }, x)));
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Afegir donació');
  const ref = { v: novaRef() };   // una recàrrega = una referència; es renova quan s'ha fet
  const pinta = async () => {
    const w = await api(`/socis/${m.id}/moneder`);
    m.saldo_cent = w.saldo_cent;
    const tipus = { recarrega: 'Recàrrega', pagament: 'Pagament', correccio: 'Correcció' };
    box.replaceChildren(h('h3', null, 'Donacions'),
      h('div', { class: 'big' }, eur(w.saldo_cent)),
      h('form', { onsubmit: (e) => {
        e.preventDefault();
        guard(btn, out, async () => {
          await api(`/socis/${m.id}/moneder/recarrega`, { method: 'POST', body: { client_ref: ref.v, import_cent: parseEur(imp.value), metode: met.value } });
          ref.v = novaRef();
          imp.value = '';
          toast('Donació afegida: el saldo del soci i la caixa s\'han actualitzat');
          await pinta();
        });
      } }, ...(potRecepcio() ? [h('div', { class: 'row' }, field('Import (€)', imp), field('Mètode', met)), h('div', { class: 'actions' }, btn)] : [h('p', { class: 'muted' }, 'Les donacions les afegeix recepció.')])),
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
  const tools = onChange ? memberTools(m, out, onChange) : null;
  if (isManager()) {
    // L'estat i el tipus de membre es canvien directament a la fitxa (sense botons de confirmació); «Expulsar» impedeix l'entrada.
    const ESTATS = [['actiu', 'Actiu'], ['suspes', 'Suspès'], ['baixa', 'Baixa'], ['expulsat', 'Expulsar']];
    const sel = h('select', { 'aria-label': 'Estat del soci' }, ESTATS.map(([e, t]) => h('option', { value: e, selected: e === m.estat }, t)));
    sel.addEventListener('change', () => guard(sel, out, async () => {
      if (sel.value === 'expulsat' && !await confirma(`Expulsar ${m.nom}? No podrà entrar al club.`, { perill: true, boto: 'Expulsar' })) { sel.value = m.estat; return; }
      try { await api(`/socis/${m.id}/estat`, { method: 'POST', body: { estat: sel.value } }); } catch (e) { sel.value = m.estat; throw e; }
      m.estat = sel.value;
      toast('Estat actualitzat');
      if (onChange) onChange(m);
    }));
    const TIPUS = [['Ordinari', 'Ordinari'], ['Terapèutic', 'Terapèutic (20 % de descompte)'], ['Família', 'Família (30 % de descompte)']];
    const tip = h('select', { 'aria-label': 'Tipus de membre' }, TIPUS.map(([e, t]) => h('option', { value: e, selected: e === m.tipus }, t)));
    tip.addEventListener('change', () => guard(tip, out, async () => {
      try { await api(`/socis/${m.id}`, { method: 'PATCH', body: { tipus: tip.value } }); } catch (e) { tip.value = m.tipus; throw e; }
      m.tipus = tip.value;
      toast('Tipus de membre actualitzat');
      if (onChange) onChange(await api(`/socis/${m.id}`));
    }));
    card.append(h('div', { class: 'row' }, field('Estat', sel), field('Tipus de membre', tip)));
  } else if (m.tipus) {
    card.append(h('p', { class: 'muted' }, 'Tipus de membre: ' + m.tipus));
  }
  if (tools) bar.append(...tools.bar);
  card.append(bar);
  if (tools) card.append(tools.panel);
  return card;
}

// Ficha del soci + cobrament de quota, dins d'un contenidor propi (es refà quan canvia alguna dada).
function memberPanel() {
  const found = h('div');
  const show1 = (m, out) => found.replaceChildren(memberCard(m, out, (mm) => show1(mm, out)), quotaForm(m, out, (mm) => show1(mm, out)));
  return { found, show: show1 };
}

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
