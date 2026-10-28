'use strict';
// Diagnòstic de dispositius: comprova que el navegador els veu i que el programa els reconeix bé.
// Les proves fan servir el perfil per defecte del local (Configuració) i no desen res.

function verdictNode(v) {
  return h('div', { class: 'diag' },
    h('div', null, h('span', { class: 'pill ' + (v.ok ? 'ok' : 'bad') }, v.ok ? 'Tot correcte' : 'Cal revisar')),
    h('ul', { class: 'checks' }, v.checks.map((c) => h('li', { class: c.ok ? 'ok' : 'bad' }, h('span', { class: 'mark', 'aria-hidden': 'true' }, c.ok ? '✓' : '✗'), ' ', c.text))));
}

function capabilities() {
  const env = browserSupport({ serial: navigator.serial, nfc: 'NDEFReader' in window, secure: window.isSecureContext, pointer: 'PointerEvent' in window });
  const row = (ok, text, ajuda) => h('li', { class: ok ? 'ok' : 'bad' }, h('span', { class: 'mark', 'aria-hidden': 'true' }, ok ? '✓' : '✗'), ' ', text, ok ? null : h('div', { class: 'muted' }, ajuda));
  return h('div', { class: 'card' }, h('h3', null, 'Aquest dispositiu i navegador'),
    h('ul', { class: 'checks' },
      row(env.secure, 'Connexió segura (HTTPS o localhost)', 'La bàscula i el NFC només funcionen en connexió segura: serveix el programa per HTTPS (p. ex. tailscale serve).'),
      row(env.serial, 'Ports sèrie (bàscules)', 'Cal Chrome o Edge d\'escriptori.'),
      row(env.pointer, 'Llapis i tàctil (tauletes de signatura)', 'Aquest navegador és massa antic.'),
      row(env.nfc, 'Lectura i gravació NFC', 'Només Chrome per a Android; no funciona a l\'escriptori.')));
}

// ---------- Bàscula ----------
async function scaleDiagnostic() {
  const cfg = Object.assign({}, DEFAULTS.bascula, await defaultProfile('bascula') || {});
  const out = h('div'), res = h('div'), ports = h('div', { class: 'muted' });
  if (!Bascula.supported()) return h('div', { class: 'card' }, h('h3', null, 'Bàscula'), msg('err', 'Aquest navegador o connexió no admet ports sèrie.'));
  navigator.serial.getPorts().then((l) => {
    ports.textContent = l.length ? `Dispositius ja autoritzats en aquest navegador: ${l.map((p) => { const i = p.getInfo(); return i.usbVendorId ? `USB ${i.usbVendorId.toString(16)}:${(i.usbProductId || 0).toString(16)}` : 'port sèrie'; }).join(', ')}.` : 'Encara no hi ha cap dispositiu autoritzat: en provar, el navegador et demanarà que en triïs un.';
  }).catch(() => {});
  const btn = h('button', { class: 'primary', type: 'button' }, 'Connectar i provar la bàscula');
  btn.addEventListener('click', () => guard(btn, out, async () => {
    res.replaceChildren(h('p', { class: 'muted' }, 'Connectant… posa un pes al plat.'));
    const b = new Bascula(profileToOptions(cfg));
    try {
      await b.connect();
      try { await b.readStable(); } catch (_) { /* es valora pel que s'hagi rebut */ }
      const lines = b.rawLog.filter((e) => e.dir === 'rx').map((e) => e.text);
      res.replaceChildren(verdictNode(analyzeScale(lines, cfg, parsePesLine)));
    } finally { try { await b.disconnect(); } catch (_) { /* ja tancada */ } }
  }));
  return h('div', { class: 'card' }, h('h3', null, 'Bàscula'),
    h('p', { class: 'muted' }, `Perfil: ${cfg.baud_rate} bauds, ordres ${cfg.read.join(', ')}, unitat ${cfg.unit}. Posa un pes conegut al plat abans de provar.`),
    ports, h('div', { class: 'actions' }, btn), out, res);
}

// ---------- Lector de carnets (teclat) ----------
async function readerDiagnostic() {
  const cfg = Object.assign({}, DEFAULTS.lector, await defaultProfile('lector') || {});
  const res = h('div');
  const input = h('input', { placeholder: 'Fes clic aquí i passa un carnet pel lector', autocomplete: 'off' });
  let keys = [], timer = null;
  const finish = async () => {
    const a = analyzeKeystrokes(keys, cfg);
    keys = [];
    input.value = '';
    const nodes = [verdictNode(a)];
    if (a.code.length >= 4) {
      try {
        const m = await api(`/locals/${S.local}/socis/carnet?codi=${encodeURIComponent(normalizeScan(a.code, cfg))}`);
        nodes.push(msg('ok', `Aquest carnet és del soci «${m.nom}».`));
      } catch (e) { nodes.push(h('p', { class: 'muted' }, 'El lector funciona, però aquest carnet no està assignat a cap soci d\'aquest local.')); }
    }
    res.replaceChildren(...nodes);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key.length > 1 && e.key !== 'Enter' && e.key !== 'Tab') return;
    keys.push({ key: e.key, t: performance.now() });
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); clearTimeout(timer); finish(); return; }
    clearTimeout(timer);
    timer = setTimeout(finish, 1200); // si el lector no envia terminador, es valora igualment
  });
  return h('div', { class: 'card' }, h('h3', null, 'Lector de carnets (USB o Bluetooth com a teclat)'),
    h('p', { class: 'muted' }, `Perfil: acaba amb ${cfg.terminador}, longitud mínima ${cfg.longitud_min}${cfg.prefix ? ', prefix «' + cfg.prefix + '»' : ''}.`),
    field('Prova de lectura', input), res);
}

// ---------- Tauleta de signatura ----------
async function tabletDiagnostic() {
  const cfg = Object.assign({}, DEFAULTS.signatura, await defaultProfile('signatura') || {});
  const events = [];
  const res = h('div');
  const pad = signatureCanvas(cfg, () => {}, 'Analitzar');
  const record = (type) => (e) => events.push({ type, pointerType: e.pointerType, pressure: e.pressure });
  pad.canvas.addEventListener('pointerdown', record('down'));
  pad.canvas.addEventListener('pointermove', (e) => { if (e.buttons || e.pointerType === 'touch') record('move')(e); });
  pad.saveButton.addEventListener('click', () => {
    const a = analyzePointer(events, cfg);
    res.replaceChildren(verdictNode(a), h('p', { class: 'muted' }, 'Tipus de dispositiu detectat: ' + (a.pointerTypes.join(', ') || 'cap')));
    events.length = 0;
  });
  return h('div', { class: 'card' }, h('h3', null, 'Tauleta de signatura'),
    h('p', { class: 'muted' }, `Signa amb el dit, el llapis o la tauleta (almenys ${cfg.tracos_min} traços) i prem «Analitzar».`), pad, res);
}

// ---------- NFC: llegir i gravar una etiqueta de prova ----------
function nfcDiagnostic() {
  if (!('NDEFReader' in window)) return h('div', { class: 'card' }, h('h3', null, 'NFC'), msg('err', 'Aquest navegador no admet NFC (només Chrome per a Android amb HTTPS).'));
  const out = h('div'), res = h('div');
  const read = h('button', { type: 'button' }, 'Llegir una etiqueta');
  read.addEventListener('click', () => guard(read, out, async () => {
    out.replaceChildren(msg('ok', 'Acosta una etiqueta NFC al dispositiu…'));
    const ev = await nfcOnce();
    out.replaceChildren();
    res.replaceChildren(msg('ok', `Etiqueta reconeguda (sèrie ${ev.serialNumber || 'desconeguda'}). Registres: ${ev.records.map((r) => r.recordType).join(', ') || 'cap'}.`));
  }));
  const write = h('button', { class: 'primary', type: 'button' }, 'Gravar i verificar una etiqueta de prova');
  write.addEventListener('click', () => guard(write, out, async () => {
    const codi = 'DIAG-' + Math.random().toString(36).slice(2, 8).toUpperCase();
    out.replaceChildren(msg('ok', 'Acosta una etiqueta NFC per gravar-hi un codi de prova…'));
    await new NDEFReader().write({ records: [{ recordType: 'text', data: codi }] });
    out.replaceChildren(msg('ok', 'Gravada. Torna-la a acostar per verificar-la…'));
    const ev = await nfcOnce();
    const text = ev.records.filter((r) => r.recordType === 'text').map((r) => new TextDecoder(r.encoding || 'utf-8').decode(r.data)).join('');
    out.replaceChildren();
    res.replaceChildren(verdictNode({ ok: text === codi, checks: [
      { id: 'gravacio', ok: true, text: 'La gravació ha anat bé.' },
      { id: 'lectura', ok: text === codi, text: text === codi ? 'La lectura coincideix amb el que s\'ha gravat.' : `S'ha llegit «${text}» i s'esperava «${codi}».` }] }));
  }));
  return h('div', { class: 'card' }, h('h3', null, 'Lector i gravador NFC'),
    h('p', { class: 'muted' }, "La gravació de prova sobreescriu el contingut de l'etiqueta que hi acostis."), h('div', { class: 'actions' }, read, write), out, res);
}

function nfcOnce() {
  return new Promise((resolve, reject) => {
    const r = new NDEFReader();
    const stop = new AbortController();
    const t = setTimeout(() => { stop.abort(); reject(new Error("No s'ha detectat cap etiqueta en 20 segons.")); }, 20000);
    r.addEventListener('reading', (ev) => { clearTimeout(t); stop.abort(); resolve(ev); }, { once: true });
    r.addEventListener('readingerror', () => { clearTimeout(t); stop.abort(); reject(new Error("L'etiqueta s'ha detectat però no s'ha pogut llegir.")); }, { once: true });
    r.scan({ signal: stop.signal }).catch((e) => { clearTimeout(t); reject(e); });
  });
}

async function diagnosticSection() {
  return h('div', null, h('p', { class: 'lead' }, 'Comprova un a un que els dispositius estan connectats i que el programa els reconeix. Les proves no desen res.'),
    capabilities(), await scaleDiagnostic(), await readerDiagnostic(), await tabletDiagnostic(), nfcDiagnostic());
}
