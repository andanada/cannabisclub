'use strict';
// Configuració de dispositius: bàscules i tauletes de signatura (perfils per local, guardats al servidor).
// El perfil diu COM parlar amb el dispositiu; quin port/dispositiu físic s'usa ho tria cada navegador en connectar.

const FIELDS = {
  bascula: [
    ['baud_rate', 'Velocitat (bauds)', 'select', [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]],
    ['data_bits', 'Bits de dades', 'select', [7, 8]],
    ['parity', 'Paritat', 'select', ['none', 'even', 'odd']],
    ['stop_bits', 'Bits de parada', 'select', [1, 2]],
    ['flow', 'Control de flux', 'select', ['none', 'hardware']],
    ['read', 'Ordres de lectura (separades per comes, es proven per ordre)', 'list'],
    ['tare', 'Ordre de tara', 'text'],
    ['zero', 'Ordre de zero', 'text'],
    ['unit', 'Unitat de la bàscula', 'select', ['g', 'mg', 'kg', 'oz', 'lb', 'ct']],
  ],
  lector: [
    ['mode', 'Tipus de lector', 'select', ['teclat', 'nfc']],
    ['terminador', 'El lector acaba cada lectura amb', 'select', ['enter', 'tab', 'cap']],
    ['prefix', 'Prefix que afegeix el lector i que cal ignorar (opcional)', 'text'],
    ['longitud_min', 'Longitud mínima del codi', 'number', [4, 64]],
    ['majuscules', 'Passar el codi a majúscules', 'bool'],
    ['prefix_generat', 'Prefix dels carnets que genera el programa (2 a 6 lletres o xifres)', 'text'],
  ],
  signatura: [
    ['amplada', 'Amplada del llenç (px)', 'number', [300, 1200]],
    ['alcada', 'Alçada del llenç (px)', 'number', [120, 600]],
    ['gruix', 'Gruix del traç', 'number', [1, 8]],
    ['color', 'Color del traç', 'color'],
    ['fons', 'Color de fons', 'color'],
    ['pressio', 'Traç sensible a la pressió del llapis', 'bool'],
    ['tracos_min', 'Traços mínims perquè la signatura sigui vàlida', 'number', [1, 20]],
  ],
};

const DEFAULTS = {
  bascula: { baud_rate: 9600, data_bits: 8, parity: 'none', stop_bits: 1, flow: 'none', read: ['IP', 'P', 'SP'], tare: 'T', zero: 'Z', unit: 'g' },
  lector: { mode: 'teclat', terminador: 'enter', prefix: '', longitud_min: 4, majuscules: true, prefix_generat: 'CLB' },
  signatura: { mode: 'llenc', amplada: 600, alcada: 220, gruix: 3, color: '#000000', fons: '#ffffff', pressio: true, tracos_min: 2 },
};

// Construeix el formulari d'un perfil a partir de la definició de camps. Retorna {nodes, read()}.
function profileForm(kind, cfg) {
  const inputs = {};
  const nodes = FIELDS[kind].map(([k, label, type, opts]) => {
    let el;
    if (type === 'select') el = h('select', null, opts.map((o) => h('option', { value: String(o), selected: String(o) === String(cfg[k]) }, String(o))));
    else if (type === 'number') el = h('input', { type: 'number', min: opts[0], max: opts[1], value: cfg[k] });
    else if (type === 'color') el = h('input', { type: 'color', value: cfg[k] });
    else if (type === 'bool') el = h('input', { type: 'checkbox', checked: !!cfg[k] });
    else if (type === 'list') el = h('input', { value: (cfg[k] || []).join(', ') });
    else el = h('input', { value: cfg[k] ?? '' });
    inputs[k] = [type, el];
    return type === 'bool' ? h('label', null, el, ' ', label) : field(label, el);
  });
  const read = () => Object.fromEntries(Object.entries(inputs).map(([k, [type, el]]) => {
    if (type === 'number') return [k, Number(el.value)];
    if (type === 'bool') return [k, el.checked];
    if (type === 'list') return [k, el.value.split(',').map((x) => x.trim()).filter(Boolean)];
    if (type === 'select') return [k, /^\d+$/.test(el.value) ? Number(el.value) : el.value];
    return [k, el.value.trim()];
  }));
  return { nodes, read };
}

const KIND_TEXT = {
  bascula: { plural: 'Bàscules', nou: 'Nova bàscula', lead: "Perfils de comunicació de les bàscules d'aquest local (OHAUS per port sèrie o USB virtual). El perfil per defecte és el que fan servir les tauletes en dispensar." },
  lector: { plural: 'Lectors de carnets', nou: 'Nou lector', lead: "Com llegeix els carnets el lector d'aquest local. Un lector USB funciona com un teclat: escriu el codi i prem Intro. També es poden llegir etiquetes NFC amb un mòbil Android (Chrome)." },
  signatura: { plural: 'Tauletes de signatura', nou: 'Nova tauleta de signatura', lead: "Com es recull la signatura de l'alta: mida i traç del llenç. Serveix per a pantalla tàctil, llapis o qualsevol tauleta que actuï com a ratolí o llapis (Wacom, Huion…)." },
};

function profileCard(kind, p, reload) {
  const out = h('div');
  const nom = h('input', { value: p.nom });
  const form = profileForm(kind, p.config);
  const save = h('button', { class: 'primary', type: 'button' }, 'Desar');
  save.addEventListener('click', () => guard(save, out, async () => {
    await api(`/dispositius/${p.id}`, { method: 'PUT', body: { nom: nom.value.trim(), config: form.read() } });
    toast('Perfil desat');
    reload();
  }));
  const def = h('button', { type: 'button' }, 'Fer-lo el de per defecte');
  def.disabled = p.per_defecte;
  def.addEventListener('click', () => guard(def, out, async () => { await api(`/dispositius/${p.id}`, { method: 'PUT', body: { per_defecte: true } }); reload(); }));
  const del = h('button', { type: 'button', class: 'danger' }, 'Esborrar');
  del.addEventListener('click', () => guard(del, out, async () => {
    if (!confirm(`Esborrar «${p.nom}»?`)) return;
    await api(`/dispositius/${p.id}`, { method: 'DELETE' });
    reload();
  }));
  return h('div', { class: 'card' }, h('div', null, h('strong', null, p.nom), ' ', p.per_defecte ? h('span', { class: 'pill ok' }, 'per defecte') : null),
    h('div', { class: 'row' }, field('Nom del perfil', nom)), ...form.nodes, h('div', { class: 'actions' }, save, def, del), out,
    kind === 'bascula' ? scaleTester(() => form.read()) : kind === 'signatura' ? signatureTester(() => form.read()) : null);
}

async function deviceSection(kind) {
  const profiles = await api(`/locals/${S.local}/dispositius?kind=${kind}`);
  const reload = () => show('config');
  const nom = h('input', { placeholder: { bascula: 'p. ex. OHAUS Navigator', signatura: 'p. ex. Tauleta recepció', lector: 'p. ex. Lector USB recepció' }[kind] });
  const form = profileForm(kind, DEFAULTS[kind]);
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Afegir');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/dispositius`, { method: 'POST', body: { kind, nom: nom.value.trim(), config: form.read() } });
      toast('Perfil creat');
      reload();
    });
  } }, h('h3', null, KIND_TEXT[kind].nou), field('Nom del perfil', nom), ...form.nodes, h('div', { class: 'actions' }, btn), out);
  return h('div', null, h('p', { class: 'lead' }, KIND_TEXT[kind].lead),
    ...(profiles.length ? profiles.map((p) => profileCard(kind, p, reload)) : [h('div', { class: 'card empty' }, 'Encara no hi ha cap perfil. Crea el primer a sota.')]), nou);
}

// ---------- Proves: connectar la bàscula i llegir un pes amb la configuració del formulari (sense desar-la) ----------

function scaleTester(readCfg) {
  const out = h('div');
  if (!Bascula.supported()) {
    return h('div', null, h('h3', null, 'Prova'), h('p', { class: 'muted' }, 'Aquest navegador o connexió no admet ports sèrie: cal Chrome o Edge i HTTPS o localhost.'));
  }
  let b = null;
  const log = h('pre', { class: 'secret' }, "Encara no s'ha rebut res.");
  const paint = () => {
    const lines = (b ? b.rawLog : []).slice(-20).map((e) => (e.dir === 'tx' ? '→ ' : '← ') + JSON.stringify(e.text));
    log.textContent = lines.length ? lines.join('\n') : "Encara no s'ha rebut res.";
  };
  const connect = h('button', { type: 'button' }, 'Connectar');
  connect.addEventListener('click', () => guard(connect, out, async () => {
    if (b && b.connected) await b.disconnect();
    b = new Bascula(Object.assign(profileToOptions(Object.assign({}, DEFAULTS.bascula, readCfg())), { onRaw: paint }));
    await b.connect();
    out.replaceChildren(msg('ok', 'Connectada. Posa un pes al plat i prem «Llegir pes».'));
  }));
  const need = () => { if (!b || !b.connected) throw new Error('Connecta primer la bàscula'); };
  const weigh = h('button', { class: 'primary', type: 'button' }, 'Llegir pes');
  weigh.addEventListener('click', () => guard(weigh, out, async () => {
    need();
    const r = await b.readStable();
    paint();
    out.replaceChildren(msg('ok', 'Pes estable: ' + r.raw + ' (ordre que ha funcionat: ' + b.workingCommand + ')'));
  }));
  const tare = h('button', { type: 'button' }, 'Tara');
  tare.addEventListener('click', () => guard(tare, out, async () => { need(); await b.tare(); toast('Tara enviada'); }));
  const cmd = h('input', { placeholder: 'Ordre manual (p. ex. IP)' });
  const send = h('button', { type: 'button' }, 'Enviar ordre');
  send.addEventListener('click', () => guard(send, out, async () => { need(); await b.send(cmd.value.trim()); setTimeout(paint, 400); }));
  return h('div', null, h('h3', null, 'Prova amb la bàscula'),
    h('p', { class: 'muted' }, 'Fa servir els valors del formulari de dalt, encara que no els hagis desat. Si no respon bé, canvia la velocitat o les ordres i torna a connectar.'),
    h('div', { class: 'actions' }, connect, weigh, tare), h('div', { class: 'row' }, field('Ordre manual', cmd)), h('div', { class: 'actions' }, send), out,
    h('h3', null, 'Comunicació en cru'), log);
}

// ---------- Proves: llenç de signatura amb la configuració del formulari ----------

function signatureTester(readCfg) {
  const holder = h('div');
  const draw = h('button', { type: 'button' }, 'Provar el llenç');
  draw.addEventListener('click', () => holder.replaceChildren(signatureCanvas(Object.assign({}, DEFAULTS.signatura, readCfg()), (r) => {
    holder.append(msg(r.valid ? 'ok' : 'err', r.valid ? `Signatura vàlida (${r.strokes} traços).` : `Falten traços: n'hi ha ${r.strokes} i en calen ${r.min}.`));
  })));
  return h('div', null, h('h3', null, 'Prova'), h('p', { class: 'muted' }, 'Signa amb el dit, el llapis o la tauleta per veure com queda amb aquesta configuració.'), h('div', { class: 'actions' }, draw), holder);
}

// Llenç de signatura configurable. Retorna el node; `onCheck({valid, strokes, min})` s'executa en prémer «Comprovar».
// Les dades de la signatura s'obtenen amb canvas.toDataURL (vegeu signaturePad a views-dispensar.js).
function signatureCanvas(cfg, onCheck) {
  const canvas = h('canvas', { class: 'sig', width: cfg.amplada, height: cfg.alcada, 'aria-label': 'Espai per signar' });
  const ctx2 = canvas.getContext('2d');
  ctx2.lineCap = 'round'; ctx2.lineJoin = 'round'; ctx2.strokeStyle = cfg.color;
  const white = () => { ctx2.fillStyle = cfg.fons; ctx2.fillRect(0, 0, canvas.width, canvas.height); };
  white();
  let drawing = false, strokes = 0;
  const pos = (e) => { const r = canvas.getBoundingClientRect(); return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height]; };
  canvas.addEventListener('pointerdown', (e) => {
    drawing = true; strokes += 1;
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* seguim dibuixant */ }
    const [x, y] = pos(e); ctx2.beginPath(); ctx2.moveTo(x, y);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drawing) return;
    const p = cfg.pressio && e.pointerType === 'pen' && e.pressure > 0 ? e.pressure : 0.5;
    ctx2.lineWidth = cfg.gruix * (0.5 + p);
    const [x, y] = pos(e); ctx2.lineTo(x, y); ctx2.stroke(); ctx2.beginPath(); ctx2.moveTo(x, y);
  });
  const stop = () => { drawing = false; };
  canvas.addEventListener('pointerup', stop); canvas.addEventListener('pointercancel', stop);
  const state = () => ({ valid: strokes >= cfg.tracos_min, strokes, min: cfg.tracos_min });
  const clear = h('button', { type: 'button' }, 'Esborrar');
  clear.addEventListener('click', () => { white(); strokes = 0; });
  const check = h('button', { class: 'primary', type: 'button' }, 'Comprovar');
  check.addEventListener('click', () => onCheck(state()));
  const node = h('div', null, canvas, h('div', { class: 'actions' }, check, clear));
  node.canvas = canvas; node.state = state;
  return node;
}
