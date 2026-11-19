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
  const carnet = h('input', { class: 'card-input', autocomplete: 'off', name: 'codi-carnet', autocapitalize: 'characters', spellcheck: 'false', placeholder: 'Passa el carnet pel lector', 'aria-label': 'Carnet' });
  // autocomplete=new-password: si no, el gestor de contrasenyes del navegador pren aquest formulari per un segon login i escriu l'usuari al camp del carnet.
  const pinInput = h('input', { class: 'card-input pin-input', type: 'password', inputmode: 'numeric', autocomplete: 'new-password', name: 'pin-carnet', maxlength: 8, placeholder: 'PIN', 'aria-label': 'PIN' });
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
    if (pinInput.value.length < 4) { carnetOut.replaceChildren(msg('err', 'Escriu el teu PIN')); return; }
    guard({}, carnetOut, async () => {
      try {
        const r = await api('/auth/login-carnet', { method: 'POST', noAuthRedirect: true, body: { codi: codiLlegit, pin: pinInput.value } });
        S.token = r.token;
        sessionStorage.setItem('t', r.token);
        await boot();
        if (r.canvi_pin) toast('El teu PIN és antic (menys de 6 xifres): canvia-ho a «Compte» abans no deixi de servir.');
      } catch (err) { tornaAlCarnet(); throw err; }
    });
  } }, h('div', { class: 'carnet-icona', 'aria-hidden': 'true' }, '▦'), h('div', { class: 'carnet-text' }, h('strong', null, 'Entra amb el carnet'), h('span', { class: 'muted' }, 'Carnet més PIN: ràpid i segur.')),
  // Botó d'enviament amagat: amb dos camps de text i cap botó «submit», l'Intro del lector no enviaria el formulari.
  pasCarnet, pasPin, carnetOut, h('button', { type: 'submit', hidden: true, tabindex: '-1', 'aria-hidden': 'true' }, 'Entrar'), h('div', { class: 'separador' }, h('span', null, 'o amb usuari i contrasenya')));
  // Si el servidor no exigeix el segon factor (servidor de proves), el camp no es mostra; si permet el carnet, es mostra i s'enfoca.
  fetch('/auth/opcions').then((r) => r.json()).then((o) => {
    if (!o.totp) {
      codeField.hidden = true; code.required = false;
      // Que ningú ho confongui amb un servidor de producció: aquí només cal usuari i contrasenya.
      form.prepend(msg('err', "Servidor de proves: no demana el codi de l'app d'autenticació. No hi posis dades reals."));
    }
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

// Rol del dia: la gerència (admin, encarregat) té accés a tot; la resta de treballadors tria en iniciar sessió Recepció o Dispensari.
const potRecepcio = () => isManager() || S.me.rol_dia === 'recepcio';
const potDispensari = () => isManager() || S.me.rol_dia === 'dispensari';
const homeView = () => (potRecepcio() && !potDispensari() ? 'acces' : 'dispensar');

// Menú: Socis, Accés, Caixa, Dispensar, Estoc, Horaris, Estadístiques i informes, Configuració.
// Una subentrada pot dur un tercer valor: la vista on porta (així Configuració agrupa pantalles que viuen en altres vistes).
const TABS = [
  ['socis', 'Socis', () => true],
  ['acces', 'Accés', potRecepcio],
  ['caixa', 'Caixa', potRecepcio],
  ['dispensar', 'Dispensar', potDispensari],
  ['estoc', 'Estoc', potDispensari, () => [['productes', 'Productes'], ['existencies', 'Existències i moviments'], ['inventari', 'Inventaris'], ...(te('resultats_inventari') ? [['resultats', "Resultats d'inventaris"]] : []), ...(te('historial') ? [['historial', 'Historial']] : [])]],
  ['fitxatge', 'Horaris', () => true],
  ['estinf', 'Estadístiques i informes', () => te('informes'), [
    ['est:membres', 'Estadístiques · Socis'], ['est:dispensari', 'Estadístiques · Dispensari i bar'], ['est:finances', 'Estadístiques · Finances'],
    ['inf:vendes', 'Informes · Vendes'], ['inf:dispensacions', 'Informes · Dispensacions'], ['inf:evolucio', 'Informes · Evolució del club'], ['inf:demografia', 'Informes · Demografia'],
    ['inf:caixa', 'Informes · Caixa'], ['inf:estoc', 'Informes · Estoc valorat'], ['inf:assistencia', 'Informes · Assistència'], ['inf:visites', 'Informes · Visites de socis'], ['inf:hores', 'Informes · Hores']]],
  ['config', 'Configuració', isManager, () => [
    ...(S.me.role === 'admin' ? [['local', 'Local i límits'], ['quotes', 'Quotes'], ['normes', 'Normes del club'], ['usuaris', 'Usuaris'], ['bascules', 'Bàscules'], ['signatura', 'Tauletes de signatura']] : []),
    ['carnets', 'Carnets i lectors'], ['diagnostic', 'Diagnòstic'], ...(S.me.role === 'admin' ? [['seguretat', 'Seguretat']] : []),
    ['estoc-avancat', 'Estoc avançat (magatzems, categories, descomptes…)', 'estoc-avancat'],
    ['gastos', 'Despeses i comptabilitat', 'gastos'], ['club', 'Controls del club', 'club'], ['rgpd', 'Privacitat i protecció de dades', 'rgpd']]],
];
// Pantalles fora del menú: el compte propi (PIN, carnet) i els descomptes d'un treballador amb el privilegi.
const VIEWS_EXTRA = ['compte', 'descomptes'];
// «Estadístiques i informes» porta a la primera pantalla; la resta s'hi arriba des de les subentrades.
VIEWS.estinf = async () => { sessionStorage.setItem('s:estadistiques', 'membres'); return VIEWS.estadistiques(); };

// Vista → grup del menú que s'ha de desplegar quan hi ets.
function grupDe(view) {
  if (view === 'estadistiques' || view === 'informe') return 'estinf';
  const t = TABS.find(([id, , , subs]) => { const l = typeof subs === 'function' ? subs() : subs; return id === view || (l || []).some((x) => x[2] === view); });
  return t ? t[0] : view;
}

// Marca l'entrada activa del menú (i la subentrada, si n'hi ha) i desplega el grup de la vista actual.
function marcaMenu() {
  const grup = grupDe(S.view);
  document.querySelectorAll('nav.tabs button[data-view]').forEach((b) => {
    const sub = b.dataset.sub;
    let marcat = false;
    if (!sub) marcat = b.dataset.view === grup && !b.classList.contains('has-sub');
    else if (b.dataset.target) marcat = b.dataset.target === S.view;
    else if (b.dataset.view === 'estinf') marcat = (S.view === 'estadistiques' ? 'est:' : 'inf:') + sessionStorage.getItem('s:' + S.view) === sub;
    else marcat = b.dataset.view === S.view && sessionStorage.getItem('s:' + S.view) === sub;
    if (marcat || (!sub && b.dataset.view === grup && b.classList.contains('has-sub') && !document.querySelector(`nav.tabs button.sub[data-view="${grup}"][aria-current]`))) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  document.querySelectorAll('nav.tabs .sub-group').forEach((g) => { g.hidden = g.dataset.view !== grup; });
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
      const grup = h('div', { class: 'sub-group', 'data-view': id, hidden: true }, subs.map(([sid, slabel, target]) => {
        const atr = { 'data-view': id, 'data-sub': sid, class: 'sub' };
        if (target) atr['data-target'] = target;
        atr.onclick = () => {
          if (target) { show(target); return; }                       // porta a una altra vista (la pròpia tria el seu apartat)
          if (id === 'estinf') { const [tipus, apartat] = sid.split(':'); const v = tipus === 'est' ? 'estadistiques' : 'informe'; sessionStorage.setItem('s:' + v, apartat); show(v); return; }
          sessionStorage.setItem('s:' + id, sid); show(id);
        };
        return h('button', atr, h('span', null, slabel));
      }));
      return [main, grup];
    }));
  const side = h('aside', { class: 'side' }, h('div', { class: 'side-in' },
    h('div', { class: 'brand' }, h('img', { class: 'brand-logo', src: '/logo-petit.png', alt: '' }), h('div', null, 'Més que un Club', h('small', null, 'Gestió del club'))),
    nav,
    h('div', { class: 'who' }, h('div', null, h('strong', null, S.me.username), ' · ', isManager() ? S.me.role : (S.me.rol_dia === 'recepcio' ? 'Recepció' : 'Dispensari')), localSelect(), langSelect(),
      ...(isManager() ? [] : [h('button', { class: 'small', onclick: () => renderRolDia() }, 'Canviar de rol')]),
      h('button', { class: 'small', onclick: () => show('compte') }, 'Compte'),
      h('button', { class: 'small', onclick: logout }, "Canviar d'usuari"))));
  const topbar = h('div', { class: 'topbar' }, h('span', { class: 'topbar-marca' }, h('img', { src: '/logo-petit.png', alt: '', width: 30, height: 32 }), h('strong', null, 'Més que un Club')),
    h('div', { class: 'row' }, localSelect(), langSelect(), h('button', { class: 'small', onclick: logout }, 'Sortir')));
  $('#app').replaceChildren(h('div', { class: 'shell' }, side, h('div', null, topbar, h('main', { id: 'main', class: 'main' }))));
}

let tornVista = 0;   // una resposta lenta d'una pantalla anterior no ha de trepitjar la que s'ha obert després
async function show(view) {
  S.view = view;
  document.body.dataset.view = view;
  marcaMenu();
  const main = $('#main');
  const meu = ++tornVista;
  main.replaceChildren(h('p', { class: 'muted' }, 'Carregant…'));
  try { const node = await VIEWS[view](); if (meu === tornVista) main.replaceChildren(node); } catch (e) { if (meu === tornVista) main.replaceChildren(msg('err', e.message)); }
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

// Selecció del rol del dia (només per a treballadors; la gerència entra directament amb accés complet).
function renderRolDia() {
  const out = h('div');
  const tria = (rol) => async () => {
    try {
      await api('/auth/rol-dia', { method: 'POST', body: { rol } });
      S.me.rol_dia = rol;
      S.view = rol === 'recepcio' ? 'acces' : 'dispensar';
      await boot();
    } catch (e) { out.replaceChildren(msg('err', e.message)); }
  };
  const targeta = (rol, titol, text, icona) => {
    const b = h('button', { type: 'button', class: 'rol-targeta', onclick: tria(rol) }, h('div', { class: 'rol-icona', 'aria-hidden': 'true' }, icona), h('strong', null, titol), h('span', { class: 'muted' }, text));
    return b;
  };
  $('#app').replaceChildren(h('div', { class: 'auth' },
    h('aside', { class: 'auth-brand' }, h('img', { class: 'auth-logo', src: '/logo.png', alt: 'Més que un Club' }), h('h1', { class: 'sr-only' }, 'Més que un Club'),
      h('p', null, 'Tria el teu rol per avui: només veuràs els botons que necessites.')),
    h('main', { class: 'auth-panel' }, h('div', { class: 'auth-lang' }, langSelect()),
      h('div', { class: 'card login' }, h('h2', { class: 'auth-title' }, 'Quin és el teu rol avui?'), h('p', { class: 'muted' }, S.me ? S.me.username : ''),
        h('div', { class: 'rol-grup' },
          targeta('recepcio', 'Recepció', 'Accés al club, caixa i donacions dels socis.', '▤'),
          targeta('dispensari', 'Dispensari', 'Dispensar, estoc i inventaris.', '✚')),
        out, h('div', { class: 'actions' }, h('button', { type: 'button', class: 'small', onclick: logout }, 'Sortir'))))));
}

async function boot() {
  try {
    S.me = await api('/me');
  } catch (e) { return; }
  if (!S.me.locals.length && S.me.role === 'admin') { renderFirstLocal(); return; }
  if (!S.me.locals.length) { $('#app').replaceChildren(msg('err', 'Aquest usuari no té cap local assignat.'), h('button', { onclick: logout }, 'Sortir')); return; }
  const saved = Number(sessionStorage.getItem('l'));
  S.local = S.me.locals.some((l) => l.id === saved) ? saved : S.me.locals[0].id;
  if (!isManager() && !S.me.rol_dia) { renderRolDia(); return; }   // el treballador tria Recepció o Dispensari abans d'entrar
  renderShell();
  const permesa = VIEWS_EXTRA.includes(S.view) || TABS.some(([id, , ok]) => ok() && (id === S.view || grupDe(S.view) === id));
  show(permesa ? S.view : homeView());
}

// Versió nova: el service worker nou pren el control (skipWaiting + claim) però la pàgina oberta continua amb el JS vell fins
// que es recarrega. Això ho diu amb un avís que no desapareix sol, i NO recarrega: pot haver-hi una dispensació a mig fer.
function avisaNovaVersio() {
  if ($('#avis-versio')) return;
  const b = h('button', { class: 'small', onclick: () => location.reload() }, 'Recarregar ara');
  document.body.append(h('div', { id: 'avis-versio', class: 'avis-versio', role: 'status' },
    h('span', null, "Hi ha una versió nova del programa. Recarrega la pàgina quan hagis acabat l'operació en curs."), b));
}
if ('serviceWorker' in navigator) {
  const jaTeControlador = !!navigator.serviceWorker.controller;   // si no en tenia, és la primera instal·lació: res a avisar
  navigator.serviceWorker.addEventListener('controllerchange', () => { if (jaTeControlador) avisaNovaVersio(); });
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
if (S.token) boot().then(() => { if (!S.me) renderLogin(); }); else renderLogin();
