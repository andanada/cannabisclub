'use strict';
// Arrencada, login, estructura i navegació. Les pantalles són a views-*.js (objecte VIEWS).
const VIEWS = {};

function logout() {
  if (S.token) fetch('/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + S.token } }).catch(() => {});
  S.token = null; S.me = null;
  sessionStorage.removeItem('t');
  renderLogin();
}

function renderLogin() {
  const out = h('div');
  const user = h('input', { autocomplete: 'username', required: true });
  const pass = h('input', { type: 'password', autocomplete: 'current-password', required: true });
  const code = h('input', { inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 6, required: true });
  const codeField = field("Codi de l'app d'autenticació", code);
  // Si el servidor no exigeix el segon factor (servidor de proves), el camp no es mostra.
  // Entrada amb carnet + PIN: primer es passa el carnet pel lector (el lector «escriu» el codi i prem Intro) i després es demana el PIN.
  const carnet = h('input', { class: 'card-input', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', placeholder: 'Passa el carnet pel lector', 'aria-label': 'Carnet' });
  const pinInput = h('input', { class: 'card-input pin-input', type: 'password', inputmode: 'numeric', autocomplete: 'off', maxlength: 8, placeholder: 'PIN', 'aria-label': 'PIN' });
  const carnetOut = h('div');
  const pasCarnet = h('div', { class: 'carnet-pas' }, carnet, h('p', { class: 'muted' }, 'El lector escriu el codi tot sol i continua amb el PIN.'));
  const teclat = h('div', { class: 'teclat', role: 'group', 'aria-label': 'Teclat numèric' },
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '⌫', '0', '↵'].map((k) => {
      const b = h('button', { type: 'button', class: k === '↵' ? 'primary' : '', 'aria-label': k === '⌫' ? 'Esborrar' : k === '↵' ? 'Entrar' : k }, k);
      b.addEventListener('click', () => {
        if (k === '⌫') pinInput.value = pinInput.value.slice(0, -1);
        else if (k === '↵') carnetBox.requestSubmit();
        else if (pinInput.value.length < 8) pinInput.value += k;
        pinInput.focus();
      });
      return b;
    }));
  const enrere = h('button', { type: 'button', class: 'small' }, 'Altre carnet');
  const pasPin = h('div', { class: 'carnet-pas', hidden: true }, h('p', { class: 'carnet-hola' }, 'Carnet llegit. Escriu el teu PIN:'), pinInput, teclat, h('div', { class: 'actions' }, enrere));
  let codiLlegit = '';
  const tornaAlCarnet = () => { codiLlegit = ''; pinInput.value = ''; pasPin.hidden = true; pasCarnet.hidden = false; carnet.value = ''; carnet.focus(); };
  enrere.addEventListener('click', tornaAlCarnet);
  const carnetBox = h('form', { class: 'auth-carnet', hidden: true, onsubmit: (e) => {
    e.preventDefault();
    if (!codiLlegit) {
      if (!carnet.value.trim()) return;
      codiLlegit = carnet.value.trim();
      carnet.value = '';
      pasCarnet.hidden = true; pasPin.hidden = false; pinInput.focus();
      return;
    }
    if (pinInput.value.length < 4) { carnetOut.replaceChildren(msg('err', 'Escriu el PIN (de 4 a 8 xifres)')); return; }
    guard({}, carnetOut, async () => {
      try {
        const r = await api('/auth/login-carnet', { method: 'POST', noAuthRedirect: true, body: { codi: codiLlegit, pin: pinInput.value } });
        S.token = r.token;
        sessionStorage.setItem('t', r.token);
        await boot();
      } catch (err) { tornaAlCarnet(); throw err; }
    });
  } }, h('div', { class: 'carnet-icona', 'aria-hidden': 'true' }, '▦'), h('div', { class: 'carnet-text' }, h('strong', null, 'Entra amb el carnet'), h('span', { class: 'muted' }, 'Carnet més PIN: ràpid i segur.')),
  pasCarnet, pasPin, carnetOut, h('div', { class: 'separador' }, h('span', null, 'o amb usuari i contrasenya')));
  // Si el servidor no exigeix el segon factor (servidor de proves), el camp no es mostra; si permet el carnet, es mostra i s'enfoca.
  fetch('/auth/opcions').then((r) => r.json()).then((o) => {
    if (!o.totp) { codeField.hidden = true; code.required = false; }
    if (o.carnet) { carnetBox.hidden = false; carnet.focus(); }
  }).catch(() => {});
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Entrar');
  const form = h('form', { class: 'card login', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api('/auth/login', { method: 'POST', noAuthRedirect: true,
        body: { username: user.value.trim(), password: pass.value, totp: code.value.trim() } });
      S.token = r.token;
      sessionStorage.setItem('t', r.token);
      pass.value = ''; code.value = '';
      await boot();
    });
  } },
  h('h2', { class: 'auth-title' }, 'Inicia la sessió'), h('p', { class: 'muted' }, 'Entra amb el teu usuari per treballar.'),
  field('Usuari', user), field('Contrasenya', pass), codeField,
  h('div', { class: 'actions' }, btn), out);
  const trets = ['Socis, quotes i carnets', 'Estoc, magatzems i inventaris', 'Caixa, informes i fitxatge'];
  $('#app').replaceChildren(h('div', { class: 'auth' },
    h('aside', { class: 'auth-brand' },
      h('img', { class: 'auth-logo', src: '/logo.png', alt: 'Més que un Club' }),
      h('h1', { class: 'sr-only' }, 'Més que un Club'),
      h('p', null, 'Tot el club en un sol lloc: ràpid, segur i fàcil de fer servir.'),
      h('ul', null, trets.map((t) => h('li', null, t)))),
    h('main', { class: 'auth-panel' }, h('div', { class: 'auth-lang' }, langSelect()), carnetBox, form)));
  user.focus();
}

const TABS = [
  ['dispensar', 'Dispensar', () => true],
  ['socis', 'Socis', () => true],
  ['estoc', 'Estoc', isManager, [
    ['existencies', 'Existències'], ['magatzems', 'Magatzems'], ['linies', 'Línies de preu'], ['contenidors', 'Contenidors'],
    ['tipus-contenidor', 'Tipus de contenidors'], ['moviment', 'Moviments'], ['inventari', 'Inventaris'], ['descomptes', 'Descomptes'],
    ['regles', 'Regles'], ['productes', 'Productes'], ['historial', 'Historial']]],
  ['caixa', 'Caixa', () => true],
  ['fitxatge', 'Fitxatge', () => true],
  ['informe', 'Informes', isManager, [['vendes', 'Vendes'], ['dispensacions', 'Dispensacions'], ['evolucio', 'Evolució del club'], ['demografia', 'Demografia'], ['caixa', 'Caixa'], ['estoc', 'Estoc valorat'], ['assistencia', 'Assistència'], ['hores', 'Hores']]],
  ['config', 'Configuració', isManager, () => (S.me.role === 'admin'
    ? [['local', 'Local i límits'], ['quotes', 'Quotes'], ['usuaris', 'Usuaris'], ['bascules', 'Bàscules'], ['signatura', 'Tauletes de signatura'], ['carnets', 'Carnets i lectors'], ['diagnostic', 'Diagnòstic'], ['seguretat', 'Seguretat']]
    : [['carnets', 'Carnets i lectors'], ['diagnostic', 'Diagnòstic']])],
  ['compte', 'Compte', () => true],
];

// Marca l'entrada activa del menú (i la subentrada, si n'hi ha) i desplega el grup de la vista actual.
function marcaMenu() {
  document.querySelectorAll('nav.tabs button[data-view]').forEach((b) => {
    const actual = b.dataset.view === S.view;
    const sub = b.dataset.sub;
    const triada = sessionStorage.getItem('s:' + S.view);
    const marcat = sub ? actual && triada === sub : actual && !b.classList.contains('has-sub');
    if (marcat || (actual && b.classList.contains('has-sub') && !triada)) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  document.querySelectorAll('nav.tabs .sub-group').forEach((g) => { g.hidden = g.dataset.view !== S.view; });
}

function localSelect() {
  const sel = h('select', { 'aria-label': 'Local', onchange: () => { S.local = Number(sel.value); sessionStorage.setItem('l', S.local); show(S.view); } },
    S.me.locals.map((l) => h('option', { value: l.id, selected: l.id === S.local }, l.nom)));
  return sel;
}

function renderShell() {
  const nav = h('nav', { class: 'tabs', 'aria-label': 'Seccions' },
    TABS.filter((t) => t[2]()).flatMap(([id, label, , subsDef]) => {
      const subs = typeof subsDef === 'function' ? subsDef() : subsDef;
      const main = h('button', { 'data-view': id, class: subs ? 'has-sub' : '', onclick: () => show(id) }, icon(id), h('span', null, label));
      if (!subs) return [main];
      const grup = h('div', { class: 'sub-group', 'data-view': id, hidden: true }, subs.map(([sid, slabel]) =>
        h('button', { 'data-view': id, 'data-sub': sid, class: 'sub', onclick: () => { sessionStorage.setItem('s:' + id, sid); show(id); } }, h('span', null, slabel))));
      return [main, grup];
    }));
  const side = h('aside', { class: 'side' }, h('div', { class: 'side-in' },
    h('div', { class: 'brand' }, h('img', { class: 'brand-logo', src: '/logo-petit.png', alt: '' }), h('div', null, 'Més que un Club', h('small', null, 'Gestió del club'))),
    nav,
    h('div', { class: 'who' }, h('div', null, h('strong', null, S.me.username), ' · ', S.me.role), localSelect(), langSelect(),
      h('button', { class: 'small', onclick: logout }, "Canviar d'usuari"))));
  const topbar = h('div', { class: 'topbar' }, h('span', { class: 'topbar-marca' }, h('img', { src: '/logo-petit.png', alt: '', width: 30, height: 32 }), h('strong', null, 'Més que un Club')),
    h('div', { class: 'row' }, localSelect(), langSelect(), h('button', { class: 'small', onclick: logout }, 'Sortir')));
  $('#app').replaceChildren(h('div', { class: 'shell' }, side, h('div', null, topbar, h('main', { id: 'main', class: 'main' }))));
}

async function show(view) {
  S.view = view;
  document.body.dataset.view = view;
  marcaMenu();
  const main = $('#main');
  main.replaceChildren(h('p', { class: 'muted' }, 'Carregant…'));
  try { main.replaceChildren(await VIEWS[view]()); } catch (e) { main.replaceChildren(msg('err', e.message)); }
}

// Primer arrencada: encara no hi ha cap local. L'administrador en crea el primer i entra.
function renderFirstLocal() {
  const nom = h('input', { required: true, maxlength: 60, placeholder: 'Nom del club o del local' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear local i entrar');
  const form = h('form', { class: 'card login', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api('/locals', { method: 'POST', body: { nom: nom.value.trim() } });
      await boot();
    });
  } }, h('h1', null, 'Benvingut'), h('p', { class: 'muted' }, "Encara no hi ha cap local. Crea'n el primer per començar; després hi podràs afegir productes, socis i usuaris."),
  field('Nom del local', nom), h('div', { class: 'actions' }, btn, h('button', { type: 'button', onclick: logout }, 'Sortir')), out);
  $('#app').replaceChildren(form);
  nom.focus();
}

async function boot() {
  try {
    S.me = await api('/me');
  } catch (e) { return; }
  if (!S.me.locals.length && S.me.role === 'admin') { renderFirstLocal(); return; }
  if (!S.me.locals.length) { $('#app').replaceChildren(msg('err', 'Aquest usuari no té cap local assignat.'), h('button', { onclick: logout }, 'Sortir')); return; }
  const saved = Number(sessionStorage.getItem('l'));
  S.local = S.me.locals.some((l) => l.id === saved) ? saved : S.me.locals[0].id;
  renderShell();
  show(S.view);
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
if (S.token) boot().then(() => { if (!S.me) renderLogin(); }); else renderLogin();
